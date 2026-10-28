"""Explicit place categories are constraints, not embedding similarity hints."""
import re

from .knowledge import normalize


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
    if not category or re.search(r'在哪|地址|怎么去|有什么特色|有什么特点|\bwhere\b', q):
        return False
    if re.search(r'推荐|哪些|有什么|有啥|找|想逛|\b(?:recommend|list|any)\b', q):
        return True
    # A bare category / category plus area is broad; K11商场 is a named lookup.
    remaining = re.sub(PATTERNS[category], '', q)
    remaining = re.sub(r'香港岛|香港|港岛|九龙|大屿山|尖沙咀|旺角|铜锣湾|中环|金钟|湾仔|观塘|深水埗|沙田|新界|东涌|将军澳|荃湾|元朗|屯门|的|\s+', '', remaining)
    return not remaining


def search_region(question, fallback='全部'):
    q = text_key(question)
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
    # Preserve a specifically requested neighbourhood, ahead of the inherited trip region.
    area = next((area for area in AREA_REGIONS if area in q), None)
    selected_region = search_region(question, region)
    return ' '.join(part for part in ['香港', area or (selected_region if selected_region != '全部' else ''),
                                     LABELS[category]] if part)
