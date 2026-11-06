"""Build portable, traceable chunks from reviewed JSONL documents (stdlib only)."""
import hashlib
import json
import re
from collections import Counter

VERSION = 'paragraphs-v1'
PAGE = re.compile(r'^\[Page ([1-9]\d*)\][ \t]*$', re.M)
HEADING = re.compile(r'^(?:#{1,6}\s+(.+)|((?:\d+\.)+\s+\S.+))$')


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def regions(text):
    """Retain PDF physical page numbers; never infer them from character counts."""
    matches = list(PAGE.finditer(text))
    cursor, page = 0, None
    for match in matches:
        if text[cursor:match.start()].strip():
            yield cursor, match.start(), page
        cursor, page = match.end(), int(match[1])
    if text[cursor:].strip():
        yield cursor, len(text), page


def sections(text, begin, end):
    """Only explicit Markdown/numbered headings; plain extracted titles stay unknown."""
    cursor, title = begin, None
    for match in re.finditer(r'[^\n]+', text[begin:end]):
        line = match[0].strip()
        heading = HEADING.fullmatch(line) if len(line) <= 120 else None
        if heading:
            position = begin + match.start()
            if text[cursor:position].strip():
                yield cursor, position, title
            cursor, title = position, heading[1] or heading[2]
    if text[cursor:end].strip():
        yield cursor, end, title


def split_spans(text, begin, end, size, overlap):
    """Prefer paragraphs, then lines/sentences, with bounded boundary-aligned overlap."""
    fragment = text[begin:end]
    paragraphs = [begin + m.end() for m in re.finditer(r'\n\s*\n', fragment)]
    boundaries = sorted(set([end] + paragraphs + [begin + m.end() for m in
        re.finditer(r'\n|[。！？!?；;](?:[”’」』])?|\.(?=\s|$)', fragment)]))
    start = begin
    while start < end:
        ceiling = min(start + size, end)
        stop = ceiling
        if ceiling < end:
            for choices in (paragraphs, boundaries):
                candidates = [p for p in choices if start + size // 2 <= p <= ceiling]
                if candidates:
                    stop = max(candidates)
                    break
            else:
                # Avoid cutting an English word when a nearby space exists.
                space = text.rfind(' ', start + size // 2, ceiling)
                if space != -1:
                    stop = space + 1
        left, right = start, stop
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            yield left, right
        if stop == end:
            break
        candidates = [p for p in boundaries if max(start + 1, stop - overlap) <= p < stop]
        start = min(candidates) if overlap and candidates else stop


def build(documents, size=800, overlap=100):
    if size < 100 or not 0 <= overlap < size // 2:
        raise ValueError('size must be >= 100; overlap must be >= 0 and < size/2')
    chunks, records, seen = [], [], set()
    for doc in documents:
        docid = doc.get('document_id')
        if not isinstance(docid, str) or not docid.strip() or docid in seen:
            raise ValueError('Missing or duplicate document_id')
        seen.add(docid)
        text = doc.get('text', '')
        if not isinstance(text, str):
            raise ValueError(f'{docid}: text must be a string')
        reasons = []
        if doc.get('include_in_retrieval') is not True:
            reasons.append('document_not_approved')
        if not text.strip():
            reasons.append('empty_text')
        url = doc.get('source_url', '')
        if not isinstance(url, str) or not url.startswith(('https://', 'http://')):
            reasons.append('missing_source_url')
        count = 0
        if not reasons:
            associated = doc.get('associated_place_ids') or []
            multi = len(set(associated)) > 1
            place = doc.get('place_id')
            review = ['multi_place_assignment_required'] if multi else ([] if place else ['missing_place_id'])
            for page_start, page_end, page in regions(text):
                for section_start, section_end, heading in sections(text, page_start, page_end):
                    for start, end in split_spans(text, section_start, section_end, size, overlap):
                        body = text[start:end]
                        identity = json.dumps([VERSION, size, overlap, docid, digest(text), start, end])
                        chunk = {
                            'schema_version': 1,
                            'chunk_id': docid + '-' + digest(identity)[:20],
                            'document_id': docid, 'chunk_index': count,
                            'text': body, 'text_sha256': digest(body),
                            'char_start': start, 'char_end': end,
                            'place_id': None if multi else place,
                            'place_name': None if multi else doc.get('place_name'),
                            'candidate_place_ids': associated if multi else ([place] if place else []),
                            'source_url': url, 'title': doc.get('title'),
                            'section_title': heading, 'page_number': page,
                            'review_required': bool(review), 'review_reasons': review,
                            'include_in_retrieval': not review,
                        }
                        for key in ('publisher', 'collected_at', 'source_updated_at', 'source_year',
                                    'temporal_note', 'quality_note', 'usage_note', 'translation_note',
                                    'scope_note', 'review_status', 'language_hint', 'extraction_method'):
                            chunk[key] = doc.get(key)
                        chunks.append(chunk)
                        count += 1
        records.append({'document_id': docid, 'chunk_count': count, 'excluded_reasons': reasons})
    groups = {}
    for chunk in chunks:
        groups.setdefault(chunk['text_sha256'], []).append(chunk['chunk_id'])
    report = {
        'pipeline_version': VERSION, 'schema_version': 1,
        'parameters': {'max_characters': size, 'overlap_max_characters': overlap},
        'input_document_count': len(documents), 'chunk_count': len(chunks),
        'retrieval_ready_count': sum(c['include_in_retrieval'] for c in chunks),
        'review_required_count': sum(c['review_required'] for c in chunks),
        'excluded_document_count': sum(bool(r['excluded_reasons']) for r in records),
        'chunks_with_pages': sum(c['page_number'] is not None for c in chunks),
        'chunks_with_sections': sum(c['section_title'] is not None for c in chunks),
        'short_chunk_count': sum(len(c['text']) < 80 for c in chunks),
        'chunk_lengths': {'min': min((len(c['text']) for c in chunks), default=0),
                          'max': max((len(c['text']) for c in chunks), default=0)},
        'by_place': dict(Counter(c['place_id'] or 'unassigned' for c in chunks)),
        'documents': records,
        'duplicate_text_groups': [ids for ids in groups.values() if len(ids) > 1],
        'review_items': [{'chunk_id': c['chunk_id'], 'reasons': c['review_reasons']}
                         for c in chunks if c['review_required']],
        'limitations': [
            'Page numbers are 1-based PDF physical pages, not printed page labels.',
            'Only explicit Markdown/numbered section headings are recognized; others remain null.',
            'Multi-place documents require manual chunk assignment before retrieval.',
            'Short fragments and exact duplicate texts are reported, not silently deleted.',
            'PDF layout, tables, OCR and translated/near-duplicate evidence require manual review.',
            'Retrieval indexes and online application integration are not built by this script.',
        ],
    }
    report['dataset_version'] = digest(json.dumps(chunks, ensure_ascii=False, sort_keys=True))
    return chunks, report
