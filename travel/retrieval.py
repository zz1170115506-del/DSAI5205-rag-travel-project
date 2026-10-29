"""BM25 retrieval with optional local dense retrieval and reciprocal-rank fusion.

The historical knowledge.search baseline and frozen holdout are left intact.
"""
import sqlite3
from functools import lru_cache

from .config import RetrievalSettings
from .embeddings import EmbeddingUnavailable, semantic_search
from .knowledge import REGIONS, normalize, places, tokens, retrieval_query
from .place_intent import requested_category, matches_category


@lru_cache(maxsize=1)
def index():
    db = sqlite3.connect(':memory:', check_same_thread=False)
    db.execute('CREATE VIRTUAL TABLE docs USING fts5(id UNINDEXED, terms)')
    for p in places():
        text = ' '.join([p['name']] * 3 + [p['en'], *p['aliases'], p['area'], p['summary'], *p['tags']])
        db.execute('INSERT INTO docs VALUES (?,?)', (p['id'], ' '.join(tokens(text))))
    db.commit()
    return db


def exact_places(query):
    q = normalize(query).strip(' ？?。')
    return [p for p in places() if q in {normalize(v) for v in [p['name'], p['en'], *p['aliases']]}]


def _lexical_retrieve(query, limit=5, region='全部', indoor_only=False, kind='all'):
    if not 1 <= limit <= 10 or len(query) > 500 or region not in REGIONS or kind not in {'all', 'food', 'attraction'}:
        raise ValueError('检索数量、地区或地点类型无效。')
    q = normalize(retrieval_query(query.strip()))
    category = requested_category(query)
    query_tokens = set(tokens(q)) - {'哪里', '在哪', '请问', '帮我', '介绍', '地址', '怎么', '么去', '如何', '一下', '推荐'}
    meta = {'recall': 'SQLite FTS5 BM25', 'reranker': '名称/别名、词覆盖、街区与主题特征重排（非神经模型）',
            'candidate_count': 0, 'returned_count': 0, 'knowledge_records': len(places())}
    if not query_tokens or ('香港' not in q and any(v in q for v in ['东京', '大阪', '北京', '上海', '巴黎', '澳门', '深圳', '新加坡', '伦敦'])):
        return {'results': [], 'retrieval': meta, 'source': 'curated_local_knowledge'}
    expr = ' OR '.join('"' + t.replace('"', '""') + '"' for t in sorted(query_tokens))
    rows = index().execute('SELECT id,bm25(docs) FROM docs WHERE docs MATCH ? ORDER BY bm25(docs) LIMIT 24', (expr,)).fetchall()
    lookup = {p['id']: p for p in places()}
    ranked = []
    for pid, raw_score in rows:
        p = lookup[pid]
        if not matches_category(p, category):
            continue
        if (region != '全部' and p['region'] != region) or (indoor_only and not p['indoor']) or (kind != 'all' and p['kind'] != kind):
            continue
        aliases = [p['name'], p['en'], *p['aliases']]
        exact = any(len(v) > 1 and normalize(v) in q for v in aliases)
        overlap = len(query_tokens & set(tokens(' '.join([p['name'], *p['aliases'], p['summary'], *p['tags']])))) / len(query_tokens)
        area = any(normalize(v) in q for v in p['area'].split('／'))
        theme = sum(normalize(t) in q for t in p['tags'])
        generic = any(v in q for v in ['第一次来香港', '香港景点', '香港旅游推荐', '文化景点', '室内场馆', '雨天', '美食', '小吃'])
        # Avoid returning a random place for a lone incidental bigram in an unknown name.
        if not exact and not area and not theme and not generic and overlap < .28:
            continue
        score = 12 * exact + 3 * overlap + 3 * area + theme + min(1, -raw_score / 10)
        ranked.append({**p, 'score': round(score, 4), 'recall_score': round(-raw_score, 4),
                       'match_reason': '名称/别名命中' if exact else '街区与文本覆盖重排',
                       'ranking_features': {'name_match': exact, 'token_coverage': round(overlap, 3), 'area_match': area, 'theme_matches': theme}})
    ranked.sort(key=lambda p: (-p['score'], p['id']))
    meta.update(candidate_count=len(ranked), returned_count=min(limit, len(ranked)))
    return {'results': ranked[:limit], 'retrieval': meta, 'source': 'curated_local_knowledge'}


def retrieve(query, limit=5, region='全部', indoor_only=False, kind='all', *, settings=None):
    if not 1 <= limit <= 10:
        raise ValueError('检索数量须在 1–10 之间。')
    lexical = _lexical_retrieve(query, 10, region, indoor_only, kind)
    settings = settings or RetrievalSettings.from_env()
    meta = lexical['retrieval']
    meta.update(mode='bm25', configured_mode=settings.mode, embedding_used=False,
                embedding_model=settings.model_name if settings.mode == 'hybrid' else None)
    q = normalize(retrieval_query(query.strip()))
    out_of_scope = '香港' not in q and any(v in q for v in ['东京', '大阪', '北京', '上海', '巴黎', '澳门', '深圳', '新加坡', '伦敦'])
    if settings.mode == 'bm25' or not tokens(q) or out_of_scope:
        lexical['results'] = lexical['results'][:limit]
        meta['returned_count'] = len(lexical['results'])
        return lexical
    try:
        semantic = semantic_search(retrieval_query(query), places(), settings, limit=len(places()))
    except EmbeddingUnavailable as exc:
        lexical['results'] = lexical['results'][:limit]
        meta.update(returned_count=len(lexical['results']), fallback_reason=str(exc))
        return lexical
    semantic = [p for p in semantic if (region == '全部' or p['region'] == region)
                and (not indoor_only or p['indoor']) and (kind == 'all' or p['kind'] == kind)
                and matches_category(p, requested_category(query))]
    combined = {}
    for rank, place in enumerate(lexical['results'], 1):
        combined[place['id']] = {**place, 'lexical_rank': rank, 'semantic_rank': None,
                                 'semantic_score': None, 'fusion_score': 1 / (60 + rank)}
    for rank, place in enumerate(semantic[:24], 1):
        item = combined.setdefault(place['id'], {**place, 'lexical_rank': None,
                                                'ranking_features': {'name_match': False}, 'fusion_score': 0.0})
        item.update(semantic_rank=rank, semantic_score=place['semantic_score'])
        item['fusion_score'] += 1 / (60 + rank)
    ranked = sorted(combined.values(), key=lambda p: (-int(p['ranking_features']['name_match']), -p['fusion_score'], p['id']))
    for place in ranked:
        place['score'] = round(place['fusion_score'], 6)
        place['match_reason'] = ('名称/别名命中；' if place['ranking_features']['name_match'] else '') + ('关键词与语义共同命中' if place['lexical_rank'] and place['semantic_rank'] else '语义相似' if place['semantic_rank'] else '关键词匹配')
        place.pop('fusion_score')
    meta.update(mode='hybrid', embedding_used=True, recall='SQLite FTS5 BM25 + local dense embeddings',
                reranker='RRF 排名融合与名称优先（非神经重排）', candidate_count=len(ranked),
                semantic_candidates=len(semantic), returned_count=min(limit, len(ranked)))
    return {'results': ranked[:limit], 'retrieval': meta, 'source': 'curated_local_knowledge'}
