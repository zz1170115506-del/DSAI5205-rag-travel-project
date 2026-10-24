import copy
import json

import pytest
from sqlalchemy import func, select

from app.models import Attraction, Chunk, Entity, Relation
from app.rag.ingestion.pipeline import ingest, safe_path
from app.rag.retrieval.search import SearchEngine, SearchRequest, distance_m, rrf


def test_import_is_idempotent(stack):
    s, factory, search, bundle = stack
    with factory() as db:
        count = db.scalar(select(func.count()).select_from(Entity))
    ingest(factory, bundle, 'demo-v1', s.data_root)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Entity)) == count
        assert db.scalar(select(func.count()).select_from(Chunk)) == 6


@pytest.mark.parametrize('field,value', [('latitude', 120), ('setting', 'invalid'), ('ticket_price_min_hkd', -1)])
def test_invalid_import_rolls_back(stack, field, value):
    s, factory, _, original = stack
    bundle = copy.deepcopy(original)
    bundle['entities'][0]['name_zh'] = 'must rollback'
    bundle['attractions'][0][field] = value
    with pytest.raises(ValueError):
        ingest(factory, bundle, 'bad', s.data_root)
    with factory() as db:
        assert db.get(Entity, 'district_tst').name_zh != 'must rollback'


def test_invalid_relation_and_path(stack):
    s, f, _, original = stack
    bundle = copy.deepcopy(original)
    bundle['relations'][0]['object_id'] = 'theme_history'
    with pytest.raises(ValueError):
        ingest(f, bundle, 'bad', s.data_root)
    with pytest.raises(ValueError):
        safe_path(s.data_root, '../../outside')


def test_rrf_and_distance():
    order, scores = rrf({'a':['x','y'], 'b':['y']})
    assert order == ['y','x']
    assert scores['y'] == pytest.approx(1/62+1/61)
    assert distance_m(22.3,114.1,22.3,114.1) == 0
    assert 900 < distance_m(22.3,114.1,22.31,114.1) < 1200


@pytest.mark.parametrize('name', ['演示历史馆','Demo History Museum','测试历史馆','演示歷史館'])
async def test_alias_and_language(stack, name):
    result = await stack[2].search(SearchRequest(query=name))
    assert result['results'][0]['attraction_id'] == 'attr_history'


async def test_filters_applied_before_topk(stack):
    result = await stack[2].search(SearchRequest(query='景点', district='district_tst', setting='indoor', max_price=20))
    assert {r['attraction_id'] for r in result['results']} == {'attr_history','attr_art'}


async def test_two_hop_relation_and_provenance(stack):
    result = await stack[2].search(SearchRequest(query='同主题其他景点', source_entity_id='attr_history', relation='HAS_THEME'))
    assert {r['attraction_id'] for r in result['results']} == {'attr_street'}
    assert result['results'][0]['relation_paths'][0]['entities'] == ['attr_history','theme_history','attr_street']


async def test_no_graph_results_does_not_return_unrelated(stack):
    result = await stack[2].search(SearchRequest(query='同主题科学馆', source_entity_id='attr_science', relation='HAS_THEME'))
    assert result['results'] == []


def test_index_tampering_and_model_mismatch(stack):
    settings, f, search, _ = stack
    settings.embedding_dim = 512
    with pytest.raises(ValueError):
        SearchEngine(f, settings).load()
    settings.embedding_dim = 256
    file = settings.data_root/'indexes'/search.manifest['index_version']/'corpus.json'
    file.write_text('[]')
    with pytest.raises(ValueError):
        SearchEngine(f, settings).load()


def test_document_database_mismatch(stack):
    settings, f, _, _ = stack
    with f.begin() as db:
        db.get(Entity,'attr_history').status='inactive'
    with pytest.raises(ValueError):
        SearchEngine(f, settings).load()
