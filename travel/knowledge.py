"""小型中文 BM25 检索：先匹配名字，再比较有区分度的词片段。无需向量服务。"""
import math
import re
from collections import Counter
from functools import lru_cache

from .config import ROOT
from .data_validation import load_validated

TRAD = str.maketrans('灣環藝術館廟蘭園蓮淨嶼纜車飯腸創觀維區來個裡麼邊間遊開門時錢價點貴嗎風景廣場',
                     '湾环艺术馆庙兰园莲净屿缆车饭肠创观维区来个里么边间游开门时钱价点贵吗风景广场')
STOP = {'香港', '地方', '推荐', '哪些', '什么', '可以', '想去', '有没有', '适合', '介绍', '一下', '怎么', '哪里', '一下', '我们', '一天'}
INTERESTS = ['海港夜景', '本地美食', '文化艺术', '自然散步', '拍照', '购物', '城市漫步']
REGIONS = ['全部', '香港岛', '九龙', '大屿山']

ENGLISH_SEARCH_TERMS = {
    'hong kong island': '香港岛', 'hong kong': '香港', 'kowloon': '九龙', 'lantau': '大屿山',
    'central': '中环', 'sheung wan': '上环', 'wan chai': '湾仔', 'mong kok': '旺角',
    'tsim sha tsui': '尖沙咀', 'west kowloon': '西九', 'sham shui po': '深水埗',
    'causeway bay': '铜锣湾', 'ngong ping': '昂坪', 'tai o': '大澳',
    'historic': '历史', 'history': '历史', 'heritage': '历史建筑', 'culture': '文化艺术',
    'cultural': '文化艺术', 'art': '艺术', 'arts': '艺术', 'museum': '博物馆', 'museums': '博物馆',
    'food': '本地美食', 'snacks': '小吃', 'tea': '奶茶', 'harbour': '海港夜景', 'harbor': '海港夜景',
    'waterfront': '海滨', 'park': '公园', 'garden': '园林', 'indoor': '室内',
    'shopping': '购物', 'mall': '商场', 'malls': '商场', 'tokyo': '东京', 'paris': '巴黎',
}


def retrieval_query(query):
    """Bridge English presentation queries to the existing bilingual source index."""
    extra = [value for term, value in ENGLISH_SEARCH_TERMS.items()
             if re.search(r'\b' + re.escape(term) + r'\b', query, re.I)]
    return query + (' ' + ' '.join(dict.fromkeys(extra)) if extra else '')


def normalize(text: str) -> str:
    return text.translate(TRAD).lower()


def tokens(text: str) -> list[str]:
    text = normalize(text)
    out = re.findall(r'[a-z0-9+]+', text)
    for block in re.findall(r'[\u4e00-\u9fff]+', text):
        out.extend(block[i:i+2] for i in range(len(block)-1) if block[i:i+2] not in STOP)
    return out


@lru_cache
def dataset() -> dict:
    return load_validated(ROOT / 'data' / 'places.json')


def places() -> list[dict]:
    return dataset()['places']


def get_place(place_id: str) -> dict:
    for place in places():
        if place['id'] == place_id:
            return dict(place)
    raise ValueError('未找到这个地点，请从资料库重新选择。')


def _document(place):
    return ' '.join([place['name']] * 2 + [place['en'], place['region'], place['area'],
                    place['summary'], place['tip'], *place['tags'], *place['aliases']])


def search(query: str, limit: int = 5, region: str = '全部', indoor_only: bool = False,
           kind: str = 'all') -> list[dict]:
    if not 1 <= limit <= 10:
        raise ValueError('检索数量须在 1–10 之间。')
    if region not in REGIONS or kind not in ['all', 'food', 'attraction']:
        raise ValueError('检索地区或地点类型无效。')
    if len(query) > 500:
        raise ValueError('搜索词过长。')
    q = normalize(retrieval_query(query.strip()))
    if not q:
        return []
    if '香港' not in q and any(city in q for city in ['东京', '大阪', '北京', '上海', '巴黎', '澳门', '深圳', '新加坡', '伦敦']):
        return []
    # 简单的查询扩展，公开可解释；不是大模型理解。
    expanded = q
    for terms, addition in [(['下雨', '雨天', '室内'], ' 博物馆 室内 艺术'),
                            (['美食', '吃什么', '吃饭'], ' 本地美食 餐厅'),
                            (['海港', '维港', '夜景'], ' 海港夜景')]:
        if any(term in q for term in terms):
            expanded += addition
    qtokens = set(tokens(expanded))
    docs = [Counter(tokens(_document(p))) for p in places()]
    avg = sum(sum(doc.values()) for doc in docs) / len(docs)
    df = Counter(t for doc in docs for t in doc)
    candidates = []
    generic = any(normalize(x) in q for x in ['第一次来香港', '香港有什么好玩', '香港景点', '香港旅游推荐'])
    for p, doc in zip(places(), docs):
        if region != '全部' and p['region'] != region:
            continue
        if indoor_only and not p['indoor']:
            continue
        if kind != 'all' and p['kind'] != kind:
            continue
        score = 0.0
        for t in qtokens:
            if t in doc:
                idf = math.log(1 + (len(docs) - df[t] + 0.5)/(df[t]+0.5))
                f = doc[t]
                score += idf * f * 2.2/(f + 1.2*(0.25 + 0.75*sum(doc.values())/avg))
        aliases = [p['name'], p['en'], *p['aliases']]
        exact = [x for x in aliases if len(x) > 1 and normalize(x) in q]
        if exact:
            score += 12
        # 具体街区比“吃饭”等通用别名更能限定用户意图。
        areas = p['area'].split('／')
        if any(normalize(area) in q for area in areas):
            score += 18
        if generic:
            score += p['priority'] / 3
        if score > 1.4:
            candidates.append({**p, 'score': round(score, 3),
                               'match_reason': '匹配名称或别名：' + '、'.join(exact[:2]) if exact else '匹配介绍、区域或主题关键词'})
    ranked = sorted(candidates, key=lambda x: (-x['score'], -x['priority'], x['id']))
    # 找到明确地点时，去掉仅因“特色”等泛词碰巧命中的低分条目。
    threshold = max(1.4, ranked[0]['score'] * 0.36) if ranked else 1.4
    return [p for p in ranked if p['score'] >= threshold][:limit]
