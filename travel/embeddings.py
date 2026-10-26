"""Local dense embeddings and exact cosine search for the small curated catalog.

Model downloads are allowed only by the explicit index-building command. Queries
load cached models offline; missing dependencies, stale indexes and inference
errors are reported to the caller so BM25 can continue serving requests.
"""
import hashlib
import json
import math
import os
import tempfile
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path

from .config import ROOT, RetrievalSettings

INDEX_PATH = ROOT / 'data' / 'indexes' / 'places-embeddings.json'
MODEL_CACHE = ROOT / 'work' / 'models'
INDEX_VERSION = 1


class EmbeddingUnavailable(RuntimeError):
    """A public reason code, without provider errors or credentials."""


def document_text(place):
    return '\n'.join([place['name'], place['en'], '、'.join(place['aliases']),
                      place['region'] + ' ' + place['area'], '、'.join(place['tags']),
                      '餐饮' if place['kind'] == 'food' else '景点',
                      place['summary'], place['tip']])


def fingerprint(records):
    raw = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def query_prefix(model_name):
    return '为这个句子生成表示以用于检索相关文章：' if model_name == 'BAAI/bge-small-zh-v1.5' else ''


def unit_vector(values):
    vector = [float(value) for value in values]
    if not vector or len(vector) > 4096 or not all(math.isfinite(value) for value in vector):
        raise EmbeddingUnavailable('invalid_vectors')
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0 or not math.isfinite(norm):
        raise EmbeddingUnavailable('invalid_vectors')
    return [value / norm for value in vector]


def create_encoder(model_name, *, download=False):
    try:
        import onnxruntime
        onnxruntime.disable_telemetry_events()
        from fastembed import TextEmbedding
    except ImportError:
        raise EmbeddingUnavailable('dependency_missing') from None
    except Exception:
        raise EmbeddingUnavailable('dependency_unavailable') from None
    try:
        return TextEmbedding(model_name=model_name, cache_dir=str(MODEL_CACHE),
                             threads=2, providers=['CPUExecutionProvider'],
                             local_files_only=not download)
    except Exception:
        raise EmbeddingUnavailable('model_not_cached_or_unavailable') from None


@lru_cache(maxsize=2)
def encoder(model_name):
    return create_encoder(model_name)


def build_index(records, model_name, *, download=False, index_path=INDEX_PATH, model=None):
    model = model if model is not None else create_encoder(model_name, download=download)
    vectors = [unit_vector(v) for v in model.embed([document_text(p) for p in records], batch_size=16)]
    if not records or len(vectors) != len(records) or len({len(v) for v in vectors}) != 1:
        raise EmbeddingUnavailable('invalid_vectors')
    payload = {'version': INDEX_VERSION, 'model': model_name, 'dimension': len(vectors[0]),
               'knowledge_sha256': fingerprint(records), 'query_prefix': query_prefix(model_name),
               'ids': [p['id'] for p in records], 'vectors': vectors}
    destination = Path(index_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent,
                                         prefix='.embedding-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    _read_index.cache_clear()
    return {key: payload[key] for key in ('model', 'dimension', 'knowledge_sha256')} | {'records': len(records)}


@lru_cache(maxsize=4)
def _read_index(filename, mtime_ns, size, model_name, digest, ids):
    del mtime_ns, size  # File signature invalidates the cache after an atomic rebuild.
    try:
        payload = json.loads(Path(filename).read_text(encoding='utf-8'))
        if (payload['version'] != INDEX_VERSION or payload['model'] != model_name
                or payload['knowledge_sha256'] != digest or tuple(payload['ids']) != ids
                or payload['query_prefix'] != query_prefix(model_name)):
            raise EmbeddingUnavailable('index_stale')
        vectors = [unit_vector(row) for row in payload['vectors']]
        dimension = payload['dimension']
        if len(vectors) != len(ids) or not vectors or any(len(v) != dimension for v in vectors):
            raise EmbeddingUnavailable('invalid_vectors')
        return vectors
    except EmbeddingUnavailable:
        raise
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        raise EmbeddingUnavailable('index_invalid') from None


def load_index(records, model_name, index_path=INDEX_PATH):
    try:
        stat = Path(index_path).stat()
    except OSError:
        raise EmbeddingUnavailable('index_missing') from None
    return _read_index(str(index_path), stat.st_mtime_ns, stat.st_size, model_name,
                       fingerprint(records), tuple(p['id'] for p in records))


def semantic_search(query, records, settings, *, limit=24, index_path=INDEX_PATH):
    vectors = load_index(records, settings.model_name, index_path)
    try:
        query_vectors = list(encoder(settings.model_name).embed([query_prefix(settings.model_name) + query], batch_size=1))
        if len(query_vectors) != 1:
            raise EmbeddingUnavailable('invalid_vectors')
        query_vector = unit_vector(query_vectors[0])
        if len(query_vector) != len(vectors[0]):
            raise EmbeddingUnavailable('index_stale')
    except EmbeddingUnavailable:
        raise
    except Exception:
        raise EmbeddingUnavailable('encoding_failed') from None
    found = []
    for place, vector in zip(records, vectors):
        similarity = sum(a * b for a, b in zip(query_vector, vector))
        if similarity >= settings.min_score:
            found.append({**place, 'semantic_score': round(similarity, 6)})
    return sorted(found, key=lambda p: (-p['semantic_score'], p['id']))[:limit]


def retrieval_status(settings=None):
    settings = settings or RetrievalSettings.from_env()
    try:
        from .knowledge import places
        load_index(places(), settings.model_name)
        ready, reason = True, None
    except EmbeddingUnavailable as exc:
        ready, reason = False, str(exc)
    return {'configured_mode': settings.mode, 'embedding_model': settings.model_name,
            'dependency_available': find_spec('fastembed') is not None,
            'index_ready': ready, 'index_reason': reason,
            'note': '索引就绪不代表本轮已执行语义检索；以回答中的 retrieval.embedding_used 为准。'}
