"""Two-stage local retrieval: SQLite FTS5 BM25 recall, explainable feature reranking.

This is lexical reranking, not a neural cross-encoder or a measured accuracy gain.
The historical knowledge.search baseline and frozen holdout are left intact.
"""
import sqlite3
from functools import lru_cache

from .knowledge import REGIONS, normalize, places, tokens


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


def retrieve(query, limit=5, region='全部', indoor_only=False, kind='all'):
    if not 1 <= limit <= 10 or len(query) > 500 or region not in REGIONS or kind not in {'all', 'food', 'attraction'}:
        raise ValueError('检索数量、地区或地点类型无效。')
    q = normalize(query.strip())
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
