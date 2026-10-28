"""Offline contracts for dense retrieval, index invalidation and safe fallback."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

import app
from travel import config, embeddings, retrieval
from travel.config import RetrievalSettings
from travel.embeddings import EmbeddingUnavailable, build_index, load_index, semantic_search
from travel.knowledge import get_place, places


class FixedEncoder:
    def __init__(self, vectors):
        self.vectors = vectors

    def embed(self, texts, **kwargs):
        assert len(texts) == len(self.vectors)
        return iter(self.vectors)


def test_dense_search_uses_cosine_and_excludes_below_threshold(tmp_path, monkeypatch):
    records = copy.deepcopy(places()[:3])
    index = tmp_path / 'vectors.json'
    cfg = RetrievalSettings(mode='hybrid', min_score=.8)
    built = build_index(records, cfg.model_name, index_path=index,
                        model=FixedEncoder([[2, 0, 0], [0, 3, 0], [0, 0, 4]]))
    monkeypatch.setattr(embeddings, 'encoder', lambda name: FixedEncoder([[0, 5, 0]]))
    found = semantic_search('不共享地点名称的意图', records, cfg, index_path=index)
    assert built['dimension'] == 3 and built['records'] == 3
    assert [p['id'] for p in found] == [records[1]['id']]
    assert found[0]['semantic_score'] == pytest.approx(1)


@pytest.mark.parametrize('change', ['data', 'model'])
def test_changed_knowledge_or_model_requires_rebuild(tmp_path, change):
    records = copy.deepcopy(places()[:2])
    index = tmp_path / 'vectors.json'
    cfg = RetrievalSettings()
    build_index(records, cfg.model_name, index_path=index, model=FixedEncoder([[1, 0], [0, 1]]))
    model_name = cfg.model_name
    if change == 'data':
        records[0]['summary'] += '更新后的事实。'
    else:
        model_name = 'different-model'
    with pytest.raises(EmbeddingUnavailable, match='index_stale'):
        load_index(records, model_name, index)


@pytest.mark.parametrize('bad_vector', [[0, 0], [float('nan'), 1], [float('inf'), 1]])
def test_invalid_vectors_do_not_replace_existing_index(tmp_path, bad_vector):
    index = tmp_path / 'vectors.json'
    index.write_text('existing-index')
    with pytest.raises(EmbeddingUnavailable, match='invalid_vectors'):
        build_index(places()[:1], 'fixture', index_path=index, model=FixedEncoder([bad_vector]))
    assert index.read_text() == 'existing-index'


def test_corrupt_index_is_reported_without_decoding_errors(tmp_path):
    index = tmp_path / 'vectors.json'
    index.write_text('{broken-json')
    with pytest.raises(EmbeddingUnavailable, match='index_invalid'):
        load_index(places(), RetrievalSettings().model_name, index)


def test_query_encoder_dimension_mismatch_is_rejected(tmp_path, monkeypatch):
    records = places()[:1]
    index = tmp_path / 'vectors.json'
    cfg = RetrievalSettings()
    build_index(records, cfg.model_name, index_path=index, model=FixedEncoder([[1, 0]]))
    monkeypatch.setattr(embeddings, 'encoder', lambda name: FixedEncoder([[1, 0, 0]]))
    with pytest.raises(EmbeddingUnavailable, match='index_stale'):
        semantic_search('文化景点', records, cfg, index_path=index)


def test_hybrid_can_add_semantic_only_results_and_keeps_filters(monkeypatch):
    def candidates(*args, **kwargs):
        return [{**get_place(pid), 'semantic_score': .9} for pid in ['tai-kwun', 'science-museum', 'avenue-stars']]
    monkeypatch.setattr(retrieval, 'semantic_search', candidates)
    result = retrieval.retrieve('xxyyzz', 5, '九龙', True, 'attraction', settings=RetrievalSettings(mode='hybrid'))
    assert [p['id'] for p in result['results']] == ['science-museum']
    assert result['results'][0]['lexical_rank'] is None
    assert result['results'][0]['semantic_rank'] == 1
    assert result['retrieval']['embedding_used'] and result['retrieval']['mode'] == 'hybrid'


def test_hybrid_preserves_exact_name_priority_and_explains_both_ranks(monkeypatch):
    monkeypatch.setattr(retrieval, 'semantic_search', lambda *a, **kw: [
        {**get_place('pmq'), 'semantic_score': .95}, {**get_place('tai-kwun'), 'semantic_score': .9}])
    result = retrieval.retrieve('大馆', 5, settings=RetrievalSettings(mode='hybrid'))
    hit = result['results'][0]
    assert hit['id'] == 'tai-kwun'
    assert hit['lexical_rank'] == 1 and hit['semantic_rank'] == 2
    assert hit['score'] == pytest.approx(1 / 61 + 1 / 62, abs=1e-6)


@pytest.mark.parametrize('reason', ['dependency_missing', 'index_missing', 'index_stale', 'encoding_failed'])
def test_embedding_failure_preserves_bm25_results_and_reports_reason(monkeypatch, reason):
    def unavailable(*args, **kwargs):
        raise EmbeddingUnavailable(reason)
    baseline = retrieval.retrieve('蓝屋', settings=RetrievalSettings())
    monkeypatch.setattr(retrieval, 'semantic_search', unavailable)
    result = retrieval.retrieve('蓝屋', settings=RetrievalSettings(mode='hybrid'))
    assert result['results'] == baseline['results']
    assert result['retrieval']['fallback_reason'] == reason
    assert result['retrieval']['mode'] == 'bm25' and not result['retrieval']['embedding_used']


def test_out_of_scope_queries_never_encode(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('out-of-scope input must not invoke embeddings')
    monkeypatch.setattr(retrieval, 'semantic_search', forbidden)
    cfg = RetrievalSettings(mode='hybrid')
    assert not retrieval.retrieve('巴黎旅游', settings=cfg)['results']
    assert not retrieval.retrieve('   ', settings=cfg)['results']


def test_retrieval_config_does_not_export_credentials(tmp_path, monkeypatch):
    (tmp_path / '.env').write_text('MODEL_API_KEY=fixture-private\nRETRIEVAL_MODE=hybrid\nEMBEDDING_MIN_SCORE=0.65\n')
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    monkeypatch.delenv('RETRIEVAL_MODE', raising=False)
    monkeypatch.delenv('EMBEDDING_MODEL', raising=False)
    monkeypatch.delenv('EMBEDDING_MIN_SCORE', raising=False)
    monkeypatch.delenv('MODEL_API_KEY', raising=False)
    settings = RetrievalSettings.from_env()
    assert settings.mode == 'hybrid' and settings.min_score == .65
    assert 'MODEL_API_KEY' not in config.os.environ
    monkeypatch.setenv('RETRIEVAL_MODE', 'bm25')
    assert RetrievalSettings.from_env().mode == 'bm25'


@pytest.mark.parametrize('kwargs', [{'mode': 'unknown'}, {'min_score': float('nan')}, {'min_score': 1.1}])
def test_invalid_retrieval_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        RetrievalSettings(**kwargs)


def test_http_route_exposes_actual_hybrid_retrieval_without_credentials(monkeypatch):
    monkeypatch.setenv('RETRIEVAL_MODE', 'hybrid')
    monkeypatch.setattr(retrieval, 'semantic_search', lambda *a, **kw: [{**get_place('tai-kwun'), 'semantic_score': .9}])
    with TestClient(app.app) as client:
        response = client.get('/api/places', params={'q': '大馆'})
        assert response.status_code == 200
        result = response.json()
        assert result['retrieval']['embedding_used']
        assert result['places'][0]['id'] == 'tai-kwun'
        status = client.get('/api/status').json()
        assert status['retrieval']['configured_mode'] == 'hybrid'
        assert 'api_key' not in json.dumps(status)


@pytest.mark.parametrize('env_text, expected', [
    ('EMBEDDING_MODEL=legacy-local-model\n', 'legacy-local-model'),
    ('MODEL_MODE=remote\nEMBEDDING_MODEL=remote-only-model\n', 'BAAI/bge-small-zh-v1.5'),
    ('MODEL_MODE=remote\nEMBEDDING_MODEL=remote-only-model\nLOCAL_EMBEDDING_MODEL=explicit-local-model\n', 'explicit-local-model'),
])
def test_local_and_fullstack_embedding_configuration_are_isolated(tmp_path, monkeypatch, env_text, expected):
    (tmp_path / '.env').write_text(env_text)
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    for key in ('LOCAL_EMBEDDING_MODEL', 'EMBEDDING_MODEL', 'MODEL_MODE'):
        monkeypatch.delenv(key, raising=False)
    assert RetrievalSettings.from_env().model_name == expected
