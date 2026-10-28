import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, inspect, select

from app.models import Source, Entity, Alias, Attraction, Relation, Image, Document, Chunk
from app.rag.text import digest, normalize, split_text

TABLES = [('sources', Source), ('entities', Entity), ('entity_aliases', Alias),
          ('attractions', Attraction), ('relations', Relation), ('images', Image),
          ('documents', Document)]
RELATION_TYPES = {'LOCATED_IN': 'district', 'HAS_THEME': 'theme',
                  'NEAR_STATION': 'station', 'SUITABLE_FOR': 'audience',
                  'SUPPORTS_ACTIVITY': 'activity'}


def safe_path(root, relative):
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError('Path escapes data root')
    return path


def read_bundle(path):
    path = Path(path)
    if path.is_file():
        return json.loads(path.read_text(encoding='utf-8'))
    bundle = {}
    for name, _ in TABLES:
        file = path / f'{name}.csv'
        if file.exists():
            with file.open(encoding='utf-8-sig', newline='') as f:
                bundle[name] = list(csv.DictReader(f))
    return bundle


def convert(model, row):
    columns = {c.name: c for c in inspect(model).columns}
    if set(row) - set(columns):
        raise ValueError(f'Unknown fields: {set(row) - set(columns)}')
    result = {}
    for key, value in row.items():
        if value == '' or value is None:
            value = None
        elif isinstance(value, str):
            kind = columns[key].type.__class__.__name__
            if kind == 'JSON':
                value = json.loads(value)
            elif kind in {'DateTime', 'DATETIME'}:
                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                value = value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
            elif kind == 'Integer':
                value = int(value)
            elif kind == 'Numeric':
                value = float(value)
        if value is None and not columns[key].nullable and columns[key].default is not None:
            continue
        length = getattr(columns[key].type, 'length', None)
        if isinstance(value, str) and length and len(value) > length:
            raise ValueError(f'{key} exceeds {length} characters')
        result[key] = value
    return result


def ingest(factory, bundle, version, data_root):
    """One transaction; invalid input rolls back all imported rows."""
    if not version or len(version) > 64:
        raise ValueError('A dataset version of 1..64 characters is required')
    with factory.begin() as db:
        for table, model in TABLES:
            for row_number, raw in enumerate(bundle.get(table, []), 2):
                try:
                    row = convert(model, raw)
                    row['dataset_version'] = version
                    if model is Alias:
                        row['normalized_alias'] = normalize(row['alias'])
                        row['alias_id'] = digest(row['entity_id'] + row['normalized_alias'] + row['language'])[:36]
                    if model is Source:
                        if row['source_type'] not in {'official','authorized','editorial','synthetic'}:
                            raise ValueError('Unknown source type')
                        if not (row.get('url') or row.get('local_path')):
                            raise ValueError('Source needs url or local_path')
                        if row.get('url') and not row['url'].startswith(('https://', 'http://')):
                            raise ValueError('Source URL must be http(s)')
                        if row.get('status') == 'verified' and not row.get('verified_at'):
                            raise ValueError('Verified source requires verified_at')
                        if row.get('local_path'):
                            safe_path(data_root, row['local_path'])
                    if model is Entity and row['entity_type'] not in {'attraction', 'district', 'theme', 'station', 'audience', 'activity'}:
                        raise ValueError('Unknown entity type')
                    if model is Attraction:
                        if row['category'] not in {'museum','park','heritage','viewpoint','market','theme_park','other'}:
                            raise ValueError('Unknown category')
                        entity = db.get(Entity, row['entity_id'])
                        if entity is None or entity.entity_type != 'attraction':
                            raise ValueError('Attraction must reference attraction entity')
                        if not (-90 <= row['latitude'] <= 90 and -180 <= row['longitude'] <= 180):
                            raise ValueError('Invalid WGS84 coordinates')
                        if row['setting'] not in {'indoor', 'outdoor', 'mixed', 'unknown'}:
                            raise ValueError('Unknown setting')
                        lo, hi = row.get('ticket_price_min_hkd'), row.get('ticket_price_max_hkd')
                        if (lo is not None and lo < 0) or (hi is not None and (hi < 0 or (lo is not None and hi < lo))):
                            raise ValueError('Invalid price range')
                        if row.get('visit_minutes') is not None and row['visit_minutes'] <= 0:
                            raise ValueError('Visit duration must be positive')
                        if not isinstance(row.get('field_evidence'), dict) or not row['field_evidence']:
                            raise ValueError('field_evidence must be a non-empty object')
                        for value in row.get('field_evidence', {}).values():
                            if not isinstance(value, dict) or not db.get(Source, value.get('source_id')):
                                raise ValueError('Field evidence needs existing source')
                    if model is Relation:
                        subject, obj = db.get(Entity, row['subject_id']), db.get(Entity, row['object_id'])
                        if (not subject or not obj or subject.entity_type != 'attraction'
                            or obj.entity_type != RELATION_TYPES.get(row['predicate'])
                            or subject.entity_id == obj.entity_id):
                            raise ValueError('Invalid relation endpoint/type')
                    if model is Image:
                        if not (row.get('asset_path') or row.get('remote_url')):
                            raise ValueError('Image needs asset_path or remote_url')
                        if row.get('asset_path'):
                            safe_path(data_root, row['asset_path'])
                        if row.get('remote_url') and not row['remote_url'].startswith('https://'):
                            raise ValueError('Remote image must use HTTPS')
                    if model is Document:
                        if not row.get('clean_text'):
                            row['clean_text'] = safe_path(data_root, row['raw_path']).read_text(encoding='utf-8')
                        row['content_hash'] = digest(row['clean_text'])
                    db.merge(model(**row))
                    db.flush()
                except Exception as exc:
                    raise ValueError(f'{table} row {row_number}: {exc.__class__.__name__}: {exc}') from exc
        # Rebuild chunks transactionally so inactive/updated documents cannot leak old text.
        db.execute(delete(Chunk))
        for doc in db.scalars(select(Document).where(Document.status == 'active')):
            for i, (start, end, text) in enumerate(split_text(doc.clean_text)):
                db.add(Chunk(chunk_id=digest(doc.document_id + doc.content_hash + str(i))[:64],
                    document_id=doc.document_id, attraction_id=doc.attraction_id,
                    chunk_index=i, text=text, char_start=start, char_end=end,
                    locator=f'字符 {start}:{end}', content_hash=digest(text), dataset_version=version))
    return version
