"""Explicit place categories are constraints, not embedding similarity hints."""
import re

from .knowledge import normalize
from .place_context import REFERENCE


LABELS = {'mall': '商场', 'museum': '博物馆'}
PATTERNS = {
    'mall': r'商场|购物中心|\b(?:shopping (?:mall|cent(?:er|re))s?|malls?)\b',
    'museum': r'博物馆|\bmuseums?\b',
}
AREA_REGIONS = {
    '尖沙咀': '九龙', '旺角': '九龙', '观塘': '九龙', '深水埗': '九龙',
    '铜锣湾': '香港岛', '中环': '香港岛', '金钟': '香港岛', '湾仔': '香港岛',
    '东涌': '大屿山', '沙田': '全部', '新界': '全部', '将军澳': '全部',
    '荃湾': '全部', '元朗': '全部', '屯门': '全部',
}


def text_key(text):
    return normalize(text).translate(str.maketrans({
        '購':'购', '場':'场', '業':'业', '貨':'货', '廈':'厦', '銅':'铜', '鑼':'锣',
        '龍':'龙', '將':'将', '軍':'军', '東':'东', '門':'门', '兩':'两', '處':'处'}))


def explicit_name(question):
    """Extract a single lookup target, without treating general travel wishes as names.

    This is a retrieval constraint, not a replacement for model itinerary editing.
    Unsupported compound requests remain with the normal agent.
    """
    q = question.strip(' \t\n？?。！!.')
    if REFERENCE.search(q) or re.search(r'行程|安排|规划|加入|添加|不要|不想|不去|别去|\b(?:itinerary|plan|add|instead|not|avoid)\b', q, re.I):
        return None
    english = re.fullmatch(
        r'(?:please\s+)?(?:where\s+is|where\'s|tell\s+me\s+about|introduce|show\s+me|'
        r'(?:(?:i\s+(?:want|would\s+like|wish)\s+to|i\'d\s+like\s+to|can\s+i)\s+)?'
        r'(?:visit|see|check\s+out|go\s+to|have\s+a\s+look\s+(?:at|on)))\s+(.+?)'
        r'(?:\s+located)?(?:,?\s+please)?', q, re.I)
    if english:
        name = re.sub(r'\s+in\s+(?:hong kong(?: island)?|kowloon|lantau|tsim sha tsui|'
                      r'central|mong kok|wan chai|causeway bay)$', '', english[1], flags=re.I)
    else:
        name = re.sub(r'^(?:请问|请介绍|介绍一下|帮我查一下|帮我找一下|介绍|查找|'
                      r'(?:我(?:们)?(?:想要|想|打算)|想)(?:去)?(?:看一眼|看一下|看看|逛逛|逛一下|参观|游览|看|逛|去)|去看看)\s*', '', q)
        name = re.sub(r'(?:在哪里|在哪儿|在哪|怎么去|的地址|地址是什么|是什么地方|有什么特色|有什么特点)$', '', name).strip()
        if name == q:
            # A bare brand name is also a lookup, not a broad recommendation.
            if not re.fullmatch(r'k11(?:\s*(?:musea?|art\s*mall|商场|购物中心))?', q, re.I):
                return None
    name = name.strip(' \"“”\'？?。！!.')
    if (not 2 <= len(name) <= 60 or
            re.search(r'推荐|有哪些|有什么|景点|行程|几天|天气|票价|一些|什么|和|以及|、|，|,'
                      r'|\b(?:what|which|recommend|some|any|places|things|malls|museums|and|or|near|around|in|day|days|it|them|this|that|these|those)\b', name, re.I)):
        return None
    generic = re.sub(r'^(?:the|a|an)\s+', '', text_key(name))
    generic = re.sub(r'(?:游玩|玩玩|逛逛|走走|散步|一下|一趟|玩)$', '', generic)
    if (category_search(generic) or generic in {
            '全部', '香港', '香港岛', '港岛', '九龙', '大屿山', *AREA_REGIONS,
            '文化', '艺术', '美食', '海港', '购物', '室内', '公园', '海边',
            'hong kong', 'hong kong island', 'kowloon', 'lantau', 'central', 'mong kok',
            'tsim sha tsui', 'wan chai', 'causeway bay', 'culture', 'art', 'food',
            'harbour', 'harbor', 'shopping', 'indoors', 'park', 'waterfront'}):
        return None
    # A common incomplete spelling in presentation queries; bare K11 stays
    # ambiguous so that the provider can return MUSEA / Art Mall candidates.
    if re.fullmatch(r'k11\s*musea?', name, re.I):
        return 'K11 MUSEA'
    return name


def matches_named_place(place, name):
    """Similarity and historical context cannot replace an explicitly named place."""
    target = text_key(name).strip(' ？?。！!.')
    return target in {text_key(value).strip(' ？?。！!.')
                      for value in [place['name'], place.get('en', ''), *place.get('aliases', [])]}


def requested_category(question):
    q = text_key(question)
    found = []
    for category, pattern in PATTERNS.items():
        for match in re.finditer(pattern, q):
            if re.search(r'(?:不要|不去|不想去|不推荐|别推荐|排除|不是|不用)(?:去|的)?$', q[:match.start()]):
                continue
            found.append((match.start(), category))
    return max(found)[1] if found else None


def matches_category(place, category, *, external=False):
    if not category:
        return True
    name = text_key(place.get('name', '') + ' ' + place.get('en', ''))
    label = text_key(place.get('category', ''))
    if external:
        # A restaurant or parking lot inside a mall is not itself a mall.
        if re.search(r'停车|餐饮|餐厅|便利店|服装|洗手间|卫生间', label + ' ' + name):
            return False
    if category == 'mall':
        if re.search(PATTERNS['museum'], label + ' ' + name):
            return False
        return label == 'mall' or bool(re.search(PATTERNS['mall'], label + ' ' + name))
    if category == 'museum':
        return label == 'museum' or bool(re.search(PATTERNS['museum'], label + ' ' + name))
    return False


def desired_count(question):
    """A bounded candidate list, never a claim to cover every place in Hong Kong."""
    q = text_key(question)
    match = re.search(r'([1-9]|10|[一二两三四五六七八九十])\s*(?:个|家|间|处)', q)
    if match:
        raw = match[1]
        count = int(raw) if raw.isascii() else {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
                '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}[raw]
        return min(count, 5)
    return 3


def category_search(question):
    category = requested_category(question)
    q = text_key(question).strip(' ？?。')
    if not category or re.search(r'在哪|地址|怎么去|有什么特色|有什么特点', q):
        return False
    if re.search(r'推荐|哪些|有什么|有啥|找|想逛|\b(?:recommend|list|any|what|which|suggest|find|malls|museums)\b', q):
        return True
    # A bare category / category plus area is broad; K11商场 is a named lookup.
    remaining = re.sub(PATTERNS[category], '', q)
    remaining = re.sub(r'香港岛|香港|港岛|九龙|大屿山|尖沙咀|旺角|铜锣湾|中环|金钟|湾仔|观塘|深水埗|沙田|新界|东涌|将军澳|荃湾|元朗|屯门|的|\s+', '', remaining)
    return not remaining


def search_region(question, fallback='全部'):
    q = text_key(question)
    for area, region in [('hong kong island','香港岛'), ('kowloon','九龙'), ('lantau','大屿山'),
                         ('mong kok','九龙'), ('tsim sha tsui','九龙'), ('causeway bay','香港岛'),
                         ('central','香港岛'), ('wan chai','香港岛')]:
        if re.search(r'\b'+area+r'\b', q):return region
    for region, aliases in [('香港岛', ['香港岛', '港岛']), ('九龙', ['九龙']), ('大屿山', ['大屿山'])]:
        if any(alias in q for alias in aliases):
            return region
    for area, region in AREA_REGIONS.items():
        if area in q:
            return region
    return fallback


def map_category_query(question, region='全部'):
    category = requested_category(question)
    q = text_key(question)
    for english, chinese in [('mong kok','旺角'), ('tsim sha tsui','尖沙咀'), ('causeway bay','铜锣湾'),
                             ('central','中环'), ('wan chai','湾仔'), ('sham shui po','深水埗')]:
        q=re.sub(r'\b'+english+r'\b',chinese,q)
    # Preserve a specifically requested neighbourhood, ahead of the inherited trip region.
    area = next((area for area in AREA_REGIONS if area in q), None)
    selected_region = search_region(question, region)
    return ' '.join(part for part in ['香港', area or (selected_region if selected_region != '全部' else ''),
                                     LABELS[category]] if part)
