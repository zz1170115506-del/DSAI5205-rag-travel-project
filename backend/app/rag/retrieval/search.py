import json
import hashlib
import math
import os
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from rank_bm25 import BM25Okapi
from sqlalchemy import select

from app.models import Alias, Attraction, Chunk, Document, Entity, Relation, Source
from app.rag.provider import ModelProvider
from app.rag.text import TOKENIZER_VERSION, digest, normalize, tokens


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1, max_length=2000)
    district: str | None = None
    theme: str | None = None
    setting: str | None = Field(None, pattern='^(indoor|outdoor|mixed)$')
    max_price: float | None = Field(None, ge=0)
    max_minutes: int | None = Field(None, gt=0)
    source_entity_id: str | None = None
    relation: str = Field('LOCATED_IN', pattern='^(LOCATED_IN|HAS_THEME|NEAR_STATION|SUITABLE_FOR|SUPPORTS_ACTIVITY)$')
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    radius_m: int = Field(3000, ge=1, le=100000)
    top_k: int = Field(5, ge=1, le=20)
    channels: list[str] = Field(default_factory=lambda: ['vector', 'bm25', 'entity', 'graph'])


def distance_m(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon1)/2)**2
    return round(6371000 * 2 * math.asin(math.sqrt(min(1, h))))


def rrf(rankings, weights=None):
    scores = {}
    for channel, ids in rankings.items():
        for rank, key in enumerate(ids, 1):
            scores[key] = scores.get(key, 0) + (weights or {}).get(channel, 1) / (60 + rank)
    return sorted(scores, key=lambda key: (-scores[key], key)), scores


def snapshot(factory):
    with factory() as db:
        rows = []
        for chunk, doc, source in db.execute(select(Chunk, Document, Source)
                .join(Document, Chunk.document_id == Document.document_id)
                .join(Source, Document.source_id == Source.source_id)
                .where(Document.status == 'active', Source.status == 'verified')
                .order_by(Chunk.chunk_id)):
            entity = db.get(Entity, chunk.attraction_id) if chunk.attraction_id else None
            if entity is not None and entity.status != 'active':
                continue
            rows.append({'chunk_id': chunk.chunk_id, 'attraction_id': chunk.attraction_id,
                'name': entity.name_zh if entity else doc.title, 'text': chunk.text,
                'content_hash': chunk.content_hash, 'dataset_version': chunk.dataset_version,
                'source_id': source.source_id, 'source_url': source.url,
                'source_type': source.source_type,
                'locator': chunk.locator,
                'verified_at': source.verified_at.isoformat() if source.verified_at else None})
        return rows


def corpus_hash(rows):
    return digest(json.dumps(rows, ensure_ascii=False, sort_keys=True))


async def build_index(factory, settings):
    rows = snapshot(factory)
    if not rows:
        raise ValueError('No verified active documents to index')
    provider = ModelProvider(settings)
    matrix = await provider.embed([row['name'] + ' ' + row['text'] for row in rows])
    version = uuid4().hex
    path = settings.data_root / 'indexes' / version
    path.mkdir(parents=True)
    np.save(path / 'vectors.npy', matrix, allow_pickle=False)
    (path / 'corpus.json').write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    manifest = {'schema_version': '1', 'index_version': version,
        'dataset_version': rows[0]['dataset_version'],
        'model_mode': settings.model_mode, 'embedding_model': settings.embedding_model,
        'embedding_revision': None,
        'embedding_dim': settings.embedding_dim, 'dtype': 'float32', 'metric': 'cosine',
        'normalized': True, 'tokenizer_version': TOKENIZER_VERSION, 'corpus_hash': corpus_hash(rows),
        'splitter_version': 'chars-500-overlap-80-v1',
        'built_at': datetime.now(timezone.utc).isoformat(),
        'chunk_ids': [r['chunk_id'] for r in rows],
        'chunk_hashes': [r['content_hash'] for r in rows],
        'files': {name: hashlib.sha256((path / name).read_bytes()).hexdigest() for name in ['vectors.npy', 'corpus.json']}}
    (path / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    temporary = settings.data_root / 'indexes' / f'.current-{version}'
    temporary.write_text(version)
    os.replace(temporary, settings.data_root / 'indexes' / 'current')
    return manifest


class SearchEngine:
    def __init__(self, factory, settings):
        self.factory, self.settings = factory, settings
        self.rows, self.matrix, self.bm25, self.manifest = [], None, None, None

    def load(self):
        base = self.settings.data_root / 'indexes'
        version = (base / 'current').read_text().strip()
        if not version or not all(c in '0123456789abcdef' for c in version):
            raise ValueError('Invalid index pointer')
        path = base / version
        m = json.loads((path / 'manifest.json').read_text())
        for name in ['vectors.npy', 'corpus.json']:
            if m['files'][name] != hashlib.sha256((path / name).read_bytes()).hexdigest():
                raise ValueError('Index file hash mismatch')
        rows = json.loads((path / 'corpus.json').read_text())
        matrix = np.load(path / 'vectors.npy', allow_pickle=False)
        if (m['embedding_dim'] != self.settings.embedding_dim
            or m['embedding_model'] != self.settings.embedding_model
            or m['model_mode'] != self.settings.model_mode
            or m['tokenizer_version'] != TOKENIZER_VERSION
            or matrix.shape != (len(rows), self.settings.embedding_dim)
            or matrix.dtype != np.float32
            or not np.isfinite(matrix).all()
            or m['chunk_ids'] != [r['chunk_id'] for r in rows]
            or m['chunk_hashes'] != [r['content_hash'] for r in rows]
            or m['corpus_hash'] != corpus_hash(rows)
            or m['corpus_hash'] != corpus_hash(snapshot(self.factory))):
            raise ValueError('Index/model/database mismatch; rebuild index')
        self.rows, self.matrix, self.manifest = rows, matrix, m
        self.bm25 = BM25Okapi([tokens(r['name'] + ' ' + r['text']) or ['_empty_'] for r in rows])

    def matches(self, query):
        q = normalize(query)
        with self.factory() as db:
            matches = {}
            for e in db.scalars(select(Entity).where(Entity.status == 'active')):
                names = [e.name_zh, e.name_en] + list(db.scalars(select(Alias.alias).where(Alias.entity_id == e.entity_id)))
                if any(name and normalize(name) in q for name in names):
                    matches[e.entity_id] = {'id': e.entity_id, 'type': e.entity_type, 'name': e.name_zh}
            return list(matches.values())

    def candidates(self, req):
        with self.factory() as db:
            allowed = set(db.scalars(select(Attraction.entity_id).join(Entity).where(Entity.status == 'active')))
            for kind, value in [('LOCATED_IN', req.district), ('HAS_THEME', req.theme)]:
                if value:
                    targets = set(db.scalars(select(Entity.entity_id).where(
                        (Entity.entity_id == value) | (Entity.name_zh == value) | (Entity.name_en == value))))
                    allowed &= set(db.scalars(select(Relation.subject_id).where(
                        Relation.predicate == kind, Relation.object_id.in_(targets), Relation.status == 'active')))
            for a in db.scalars(select(Attraction)):
                if req.setting and a.setting != req.setting:
                    allowed.discard(a.entity_id)
                if req.max_price is not None and (a.ticket_price_max_hkd is None or a.ticket_price_max_hkd > req.max_price):
                    allowed.discard(a.entity_id)
                if req.max_minutes is not None and (a.visit_minutes is None or a.visit_minutes > req.max_minutes):
                    allowed.discard(a.entity_id)
                if req.latitude is not None and req.longitude is not None:
                    if distance_m(req.latitude, req.longitude, float(a.latitude), float(a.longitude)) > req.radius_m:
                        allowed.discard(a.entity_id)
            paths = {}
            if req.source_entity_id and self.settings.enable_graph and 'graph' in req.channels:
                links = list(db.scalars(select(Relation).where(Relation.subject_id == req.source_entity_id,
                    Relation.predicate == req.relation, Relation.status == 'active').limit(50)))
                for link in links:
                    for other in db.scalars(select(Relation).where(Relation.object_id == link.object_id,
                        Relation.predicate == req.relation, Relation.status == 'active',
                        Relation.subject_id != req.source_entity_id).limit(100)):
                        paths.setdefault(other.subject_id, []).append({
                            'entities': [link.subject_id, link.object_id, other.subject_id],
                            'predicate': link.predicate,
                            'relation_ids': [link.relation_id, other.relation_id],
                            'source_ids': [link.source_id, other.source_id]})
                # A relational request must satisfy its relationship, not fall back to unrelated text.
                allowed &= set(paths)
            return allowed, paths

    async def search(self, req, provider=None, profile=None):
        if self.matrix is None:
            raise ValueError('Index not ready')
        if not set(req.channels) <= {'vector', 'bm25', 'entity', 'graph'}:
            raise ValueError('Unknown search channel')
        allowed, paths = self.candidates(req)
        indices = [i for i, r in enumerate(self.rows) if r['attraction_id'] is None or r['attraction_id'] in allowed]
        matches = self.matches(req.query)
        exact = {m['id'] for m in matches if m['type'] == 'attraction'}
        if len(exact) == 1 and not req.source_entity_id and not any(word in normalize(req.query) for word in ['其他','附近','比较','区别','compare','same','同区','同主题']):
            indices = [i for i in indices if self.rows[i]['attraction_id'] in exact]
        rankings = {}
        if 'vector' in req.channels:
            vector = (await (provider or ModelProvider(self.settings)).embed([req.query]))[0]
            scores = self.matrix @ vector
            rankings['vector'] = [self.rows[i]['chunk_id'] for i in sorted(indices, key=lambda j: -scores[j])[:20] if scores[i] > .05]
        if 'bm25' in req.channels:
            scores = self.bm25.get_scores(tokens(req.query))
            rankings['bm25'] = [self.rows[i]['chunk_id'] for i in sorted(indices, key=lambda j: -scores[j])[:20] if scores[i] > 0]
        if 'entity' in req.channels:
            rankings['entity'] = [self.rows[i]['chunk_id'] for i in indices if self.rows[i]['attraction_id'] in exact]
        if 'graph' in req.channels and self.settings.enable_graph:
            rankings['graph'] = [self.rows[i]['chunk_id'] for i in indices if self.rows[i]['attraction_id'] in paths]
        order, fused = rrf(rankings)
        by_id = {r['chunk_id']: r for r in self.rows}
        # Explicit filters are themselves structured evidence; return matching candidates even without lexical overlap.
        if not order and any([req.district, req.theme, req.setting, req.max_price is not None, req.max_minutes is not None, req.latitude is not None]):
            order = [self.rows[i]['chunk_id'] for i in indices]
        interests = (profile or {}).get('interests', [])
        avoidances = (profile or {}).get('avoidances', [])
        if interests and not req.theme:
            order.sort(key=lambda k: -(fused.get(k, 0) + .003 * sum(normalize(t) in normalize(by_id[k]['text']) for t in interests)))
        if avoidances and not exact:
            order.sort(key=lambda k: sum(normalize(t) in normalize(by_id[k]['text']) for t in avoidances))
        results, counts = [], {}
        for key in order:
            row = by_id[key]
            attraction = row['attraction_id']
            if counts.get(attraction, 0) >= 2:
                continue
            counts[attraction] = counts.get(attraction, 0) + 1
            results.append({**row, 'score': fused.get(key, 0), 'relation_paths': paths.get(attraction, []),
                'channels': [c for c, ids in rankings.items() if key in ids]})
            if len(results) == req.top_k:
                break
        return {'results': results, 'index_version': self.manifest['index_version'], 'model_mode': self.settings.model_mode}
