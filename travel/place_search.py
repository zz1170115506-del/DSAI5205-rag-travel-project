"""Local retrieval with category-aware map supplementation when coverage is low."""
from .knowledge import REGIONS, places
from .maps import resolve_place
from .retrieval import retrieve
from .place_intent import requested_category, matches_category, category_search, desired_count, map_category_query, search_region


def poi_region(poi):
    district=poi.get('district','').translate(str.maketrans('灣區東離島觀龍黃','湾区东离岛观龙黄'))
    if any(name in district for name in ['中西','湾仔','东区','南区']):
        return '香港岛'
    if any(name in district for name in ['油尖旺','深水埗','九龙城','黄大仙','观塘']):
        return '九龙'
    # Islands District also contains Cheung Chau and Peng Chau. Do not call all
    # island results Lantau merely because they share a district.
    text=poi.get('name','')+' '+poi.get('address','')
    if '离岛' in district and any(name in text for name in ['大屿山','东涌','昂坪','大澳','梅窝','愉景湾','塘福','贝澳','石壁']):
        return '大屿山'
    return None


async def search_library(query,region,settings,http_transport=None):
    query=query.strip()
    if len(query)>100 or (query and len(query)<2) or region not in REGIONS:
        raise ValueError('请输入 2–100 个字符，并选择有效地区。')
    retrieval=retrieve(query,10) if query else None
    local=retrieval['results'] if retrieval else places()
    category = requested_category(query)
    broad_category = category_search(query)
    if broad_category:
        region = search_region(query, region)
    local = [p for p in local if matches_category(p, category)]
    selected = [p for p in local if region == '全部' or p['region'] == region]
    if local and (not broad_category or len(selected) >= desired_count(query)):
        return {'mode':'local' if selected else 'filtered_local','provider':'curated_local',
                'query':query,'region':region,'results':selected,'local_match':True,'local_miss':False,
                'local_count':len(local),'external_requested':False,
                'retrieval':retrieval['retrieval'] if retrieval else None,
                'message':'已找到本地资料。' if selected else '资料库中有相关地点，但不符合当前地区筛选。请切换“全部”查看。'}
    external=await resolve_place(map_category_query(query,region) if broad_category else query,settings,http_transport)
    # Exact aliases remain a local hit even if lexical retrieval did not recall them.
    if external['mode']=='local':
        local=[p for p in external['results'] if matches_category(p, category)]
        selected=[p for p in local if region=='全部' or p['region']==region]
        return {**external,'mode':'local' if selected else 'filtered_local','region':region,'results':selected,
                'local_match':True,'local_miss':False,'local_count':len(local),
                'message':'已找到本地资料。' if selected else '资料库中有该地点，但不符合当前地区筛选。请切换“全部”查看。'}
    if category:
        external = {**external, 'results': [p for p in external['results'] if matches_category(p, category, external=True)]}
        if external['mode'] == 'live' and not external['results']:
            external.update(mode='filtered_external', message='地图未返回符合指定类别的地点，未使用其他类别充数。')
    if external['mode']=='live' and region!='全部':
        found=[p for p in external['results'] if poi_region(p)==region]
        if not found:
            external={**external, 'mode':'filtered_external', 'unfiltered_count':len(external['results']), 'results':[],
                      'message':'高德返回了香港地点候选，但未能确认符合当前地区筛选。请切换“全部”查看。'}
        else:
            external={**external, 'results':found}
    if selected and external['mode'] != 'live':
        return {'mode':'local','provider':'curated_local','query':query,'region':region,'results':selected,
                'local_match':True,'local_miss':False,'local_count':len(selected),
                'external_requested':external.get('external_requested',False),
                'message':'已保留符合类别的本地候选；地图补充未取得更多可用结果。'}
    return {**external,'region':region,'local_miss':not bool(selected),'local_count':len(selected),
            'local_results':selected}
