"""One library search: local retrieval first, AMap only after a real local miss."""
from .knowledge import REGIONS, places
from .maps import resolve_place
from .retrieval import retrieve


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
    selected=[p for p in local if region=='全部' or p['region']==region]
    if local:
        return {'mode':'local' if selected else 'filtered_local','provider':'curated_local',
                'query':query,'region':region,'results':selected,'local_match':True,'local_miss':False,
                'local_count':len(local),'external_requested':False,
                'retrieval':retrieval['retrieval'] if retrieval else None,
                'message':'已找到本地资料。' if selected else '资料库中有相关地点，但不符合当前地区筛选。请切换“全部”查看。'}
    external=await resolve_place(query,settings,http_transport)
    # Exact aliases remain a local hit even if lexical retrieval did not recall them.
    if external['mode']=='local':
        local=external['results'];selected=[p for p in local if region=='全部' or p['region']==region]
        return {**external,'mode':'local' if selected else 'filtered_local','region':region,'results':selected,
                'local_match':True,'local_miss':False,'local_count':len(local),
                'message':'已找到本地资料。' if selected else '资料库中有该地点，但不符合当前地区筛选。请切换“全部”查看。'}
    result={**external,'region':region,'local_miss':True,'local_count':0}
    if result['mode']=='live' and region!='全部':
        found=[p for p in result['results'] if poi_region(p)==region]
        if not found:
            result.update(mode='filtered_external',unfiltered_count=len(result['results']),results=[],
                          message='高德返回了香港地点候选，但未能确认符合当前地区筛选。请切换“全部”查看。')
        else:
            result['results']=found
    return result
