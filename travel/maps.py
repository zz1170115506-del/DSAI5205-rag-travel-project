"""Fixed-host AMap Web Service adapter. Secrets never reach browser URLs or logs."""
import asyncio
import base64
import math
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from .place_intent import requested_category, matches_category

from .knowledge import get_place, normalize
from .retrieval import exact_places

BASE = 'https://restapi.amap.com'
SEARCH_DOC = 'https://lbs.amap.com/api/webservice/guide/api-advanced/search'
ROUTE_DOC = 'https://lbs.amap.com/api/webservice/guide/api/direction'


def now():
    return datetime.now(timezone.utc).isoformat()


def unavailable(mode='not_configured'):
    return {'mode': mode, 'provider': 'amap', 'results': [], 'source': {'name': '高德地图 Web 服务', 'url': SEARCH_DOC},
            'message': '高德自动查询尚未启用，本次未调用高德接口。' if mode == 'disabled' else
                       '高德 Web 服务 Key 未配置，本次未请求外部地图。' if mode == 'not_configured' else
                       '高德未返回可用数据，请检查服务权限、香港覆盖和网络；未用估算冒充地图结果。'}


def coord(value):
    lon, lat = map(float, value.split(','))
    if not math.isfinite(lon + lat) or not (113.8 < lon < 114.5 and 22.1 < lat < 22.65):
        raise ValueError('outside Hong Kong bounding region')
    return [lon, lat]


def scalar(value, limit=300):
    return value[:limit] if isinstance(value, str) else ''


async def request_json(client, path, key, **params):
    response = await client.get(BASE + path, params={'key': key, 'output': 'JSON', **params})
    response.raise_for_status()
    if len(response.content) > 1_500_000:
        raise ValueError('oversize map response')
    obj = response.json()
    if obj.get('status') != '1':
        raise ValueError('map provider rejected request')
    return obj


async def search_map(query, settings, http_transport=None):
    if not settings.amap_enabled:
        return unavailable('disabled')
    if not settings.amap_api_key:
        return unavailable()
    try:
        async with httpx.AsyncClient(timeout=12, transport=http_transport, follow_redirects=False) as client:
            obj = await request_json(client, '/v3/place/text', settings.amap_api_key, keywords=query,
                                     city='香港', citylimit='true', offset=5, page=1, extensions='base')
        found = []
        for p in obj.get('pois', [])[:5]:
            try:
                location = coord(p.get('location', ''))
                city = scalar(p.get('cityname'))
                province = scalar(p.get('pname'))
                adcode = scalar(p.get('adcode'))
                if not ('香港' in city + province or adcode.startswith('81')):
                    continue
                name = scalar(p.get('name'), 100)
                if not name:
                    continue
                found.append({'id': 'amap-' + scalar(p.get('id'), 80), 'name': name,
                              'address': scalar(p.get('address')), 'district': scalar(p.get('adname')),
                              'category': scalar(p.get('type')), 'location': location,
                              'coordinate_system': 'GCJ-02 (provider supplied)', 'provider': 'amap',
                              'source': {'name': '高德地图 POI 搜索', 'url': SEARCH_DOC, 'fetched_at': now()},
                              'map_url': 'https://uri.amap.com/marker?' + urlencode({'position': ','.join(map(str, location)), 'name': name, 'coordinate': 'gaode', 'src': 'hk-travel-assistant'}),
                              'review_status': 'external_unreviewed', 'curated_knowledge': False})
            except (ValueError, TypeError, AttributeError):
                continue
        found = [p for p in found if matches_category(p, requested_category(query), external=True)]
        encoded = str(found)
        if settings.amap_api_key in encoded:
            raise ValueError('credential reflection')
        return {'mode': 'live' if found else 'empty', 'provider': 'amap', 'results': found,
                'source': {'name': '高德地图 Web 服务', 'url': SEARCH_DOC, 'fetched_at': now()},
                'message': '高德返回以下香港地点候选，请核对同名地点；未自动写入本地资料库。' if found else '高德未返回可用的香港地点，可能未覆盖或名称不够具体。'}
    except Exception:
        return unavailable('unavailable')


async def resolve_place(query, settings, http_transport=None):
    # This endpoint is for a named place, not a broad travel question.
    query = query.strip()
    if not 2 <= len(query) <= 100:
        raise ValueError('地点名称应为 2–100 个字符。')
    local = exact_places(query)
    if local:
        return {'mode': 'local', 'query': query, 'provider': 'curated_local', 'results': local,
                'source': {'name': '本地官方来源资料库'}, 'external_requested': False}
    result = await search_map(query, settings, http_transport)
    return {**result, 'query': query, 'external_requested': settings.amap_enabled and bool(settings.amap_api_key), 'local_match': False,
            'search_links': [
                {'name': '在高德地图搜索', 'url': 'https://uri.amap.com/search?' + urlencode({'keyword': '香港 ' + query, 'city': '香港', 'view': 'map', 'src': 'hk-travel-assistant'})},
                {'name': '在 OpenStreetMap 搜索', 'url': 'https://www.openstreetmap.org/search?' + urlencode({'query': '香港 ' + query})},
            ]}


def poi_name_key(value):
    """Match formatting / mixed-language order, never substrings or nearby shops."""
    value=normalize(unicodedata.normalize('NFKC',value))
    return tuple(sorted(re.findall(r'[a-z0-9]+|[\u3400-\u9fff]+',value)))


def is_food_branch(place, candidate):
    # Only a complete restaurant brand + explicit branch suffix qualifies.
    # A shop inside an attraction (e.g. SOIL(PMQ...店)) must never qualify.
    if place['kind']!='food':
        return False
    canonical=unicodedata.normalize('NFKC',place['name'])
    brand=re.sub(r'\([^()]*\)$','',canonical).strip()
    candidate=unicodedata.normalize('NFKC',candidate)
    branch=re.fullmatch(r'(.+?)\(([^()]*(?:店|门市))\)',candidate)
    return bool(branch and poi_name_key(branch[1])==poi_name_key(brand))


async def route_map(place_ids, settings, http_transport=None, poi_choices=None):
    if not settings.amap_enabled:
        return {**unavailable('disabled'), 'legs': [], 'polylines': [], 'map_image': None}
    if not settings.amap_api_key:
        return {**unavailable(), 'legs': [], 'polylines': [], 'map_image': None}
    if not 2 <= len(place_ids) <= 6 or len(set(place_ids)) != len(place_ids):
        raise ValueError('路线支持 2–6 个不同的本地地点。')
    selected = [get_place(pid) for pid in place_ids]
    try:
        # Resolve provider POIs first. Never feed our approximate WGS84 sketch coordinates
        # into an API expecting provider coordinates.
        async with asyncio.timeout(55):
            locations, candidates = [], {}
            for p in selected:
                result = await search_map(p['name'], settings, http_transport)
                if result['mode'] not in ('live','empty'):
                    return {**result,'legs':[],'polylines':[],'map_image':None}
                aliases = {poi_name_key(v) for v in [p['name'], p['en'], *p['aliases']]}
                matches = [v for v in result['results'] if poi_name_key(v['name']) in aliases or is_food_branch(p,v['name'])]
                if not matches:
                    alias = next((v for v in p['aliases'] if normalize(v) != normalize(p['name']) and 2<=len(v)<=100),None)
                    if alias:
                        result=await search_map(alias,settings,http_transport)
                        if result['mode'] not in ('live','empty'):
                            return {**result,'legs':[],'polylines':[],'map_image':None}
                        matches=[v for v in result['results'] if poi_name_key(v['name']) in aliases or is_food_branch(p,v['name'])]
                if not matches:
                    return {**unavailable('ambiguous_location'),'message':'高德未找到可确认的同名地点，请打开外部地图核对。','legs':[],'polylines':[],'map_image':None}
                candidates[p['id']]=matches
                choice=(poi_choices or {}).get(p['id'])
                chosen=[v for v in matches if v['id']==choice] if choice else matches
                if choice and len(chosen)!=1:
                    return {**unavailable('invalid_selection'),'message':'所选高德位置已失效，请重新核对同名地点。','legs':[],'polylines':[],'map_image':None}
                branch_confirmation=not choice and any(is_food_branch(p,v['name']) for v in matches)
                locations.append(chosen[0] if len(chosen)==1 and not branch_confirmation else None)
            if any(value is None for value in locations):
                return {**unavailable('ambiguous_location'),'message':'高德找到多个同名位置，请选择起点和终点后计算步行路线。','candidates':candidates,'legs':[],'polylines':[],'map_image':None}
            legs = []
            async with httpx.AsyncClient(timeout=12, transport=http_transport, follow_redirects=False) as client:
                for a, b in zip(locations, locations[1:]):
                    obj = await request_json(client, '/v3/direction/walking', settings.amap_api_key,
                                             origin=','.join(map(str, a['location'])), destination=','.join(map(str, b['location'])))
                    path = obj['route']['paths'][0]
                    points = [coord(v) for step in path.get('steps', [])[:100] for v in step.get('polyline', '').split(';') if v]
                    if len(points) < 2 or len(points) > 10000:
                        raise ValueError('invalid route geometry')
                    distance, duration = int(path['distance']), int(path['duration'])
                    if distance <= 0 or duration <= 0:
                        raise ValueError('invalid route metrics')
                    steps = []
                    for step in path.get('steps', [])[:100]:
                        instruction = scalar(step.get('instruction'), 500)
                        if not instruction:
                            continue
                        steps.append({'instruction':instruction, 'road':scalar(step.get('road'),100),
                                      'orientation':scalar(step.get('orientation'),20),
                                      'distance_m':int(step['distance']) if str(step.get('distance','')).isdigit() else None})
                    legs.append({'steps': steps, 'origin': a['name'], 'destination': b['name'], 'distance_m': distance,
                                 'duration_s': duration, 'points': points[::max(1, len(points)//1000)], 'mode': 'walking'})
                points = [point for leg in legs for point in leg['points']]
                sampled = points[::max(1, math.ceil(len(points)/80))]
                if sampled[-1] != points[-1]:
                    sampled.append(points[-1])
                image = None
                # Static image is optional: route geometry remains valid if image service fails.
                try:
                    response = await client.get(BASE + '/v3/staticmap', params={
                        'key': settings.amap_api_key, 'size': '640*400',
                        'markers': '|'.join('mid,0x216653,' + str(i+1) + ':' + ','.join(map(str, p['location'])) for i,p in enumerate(locations)),
                        'paths': '5,0x216653,1,,:' + ';'.join(','.join(map(str, p)) for p in sampled)})
                    raw = response.content
                    if response.status_code == 200 and len(raw) <= 1_500_000 and raw.startswith(b'\x89PNG\r\n\x1a\n'):
                        image = 'data:image/png;base64,' + base64.b64encode(raw).decode()
                except Exception:
                    pass
        result = {'mode': 'live', 'provider': 'amap', 'transport': 'HTTPS Web Service', 'route_mode': 'walking',
                'source': {'name': '高德地图步行路线与静态地图', 'url': ROUTE_DOC, 'fetched_at': now()},
                'coordinate_system': 'provider POI coordinates', 'legs': legs,
                'navigation_url':'https://uri.amap.com/direction?' + urlencode({'from':','.join(map(str,locations[0]['location']))+','+locations[0]['name'], 'to':','.join(map(str,locations[-1]['location']))+','+locations[-1]['name'], 'mode':'walk','coordinate':'gaode','src':'hk-travel-assistant'}),
                'polylines': [leg['points'] for leg in legs], 'map_image': image,
                'distance_m': sum(v['distance_m'] for v in legs), 'duration_s': sum(v['duration_s'] for v in legs),
                'message': '高德返回的步行路线；这是单独的步行参考，不替换行程中的公共交通估算。跨海、山区或覆盖不足时可能无法算路。'}
        if settings.amap_api_key in str(result):
            raise ValueError('credential reflection')
        return result
    except Exception:
        return {**unavailable('unavailable'), 'legs': [], 'polylines': [], 'map_image': None}
