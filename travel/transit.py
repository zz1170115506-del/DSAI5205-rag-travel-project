"""Source-backed local MTR topology and last-mile references, never live routing."""
import copy
import heapq
import itertools
import json
from functools import lru_cache
from urllib.parse import urlparse

from .config import ROOT
from .knowledge import get_place, places

SOURCE_HOSTS={'www.mtr.com.hk','www.pmq.org.hk','www.mplus.org.hk','www.thepeak.com.hk',
              'nlb.com.hk','www.hkzbg.gov.hk','www.ctc.org.hk','www.discoverhongkong.com'}


@lru_cache
def transit_data():
    data=json.loads((ROOT/'data/transit.json').read_text())
    names=set()
    for line in data['lines']:
        assert len(line['stations'])==len(set(line['stations']))>=2
        assert line['id'] not in names
        names.add(line['id'])
    for source in data['sources'].values():
        url=urlparse(source['url'])
        assert url.scheme=='https' and url.hostname in SOURCE_HOSTS and not url.username
    stations={s for line in data['lines'] for s in line['stations']}
    assert set(data['access'])=={p['id'] for p in places()}
    for access in data['access'].values():
        assert access['options'] and access['connector'] in {'','peak_tram','ngong_ping_bus','tai_o_bus'}
        for option in access['options']:
            assert option['station'] in stations and option['exit'] and option['sources']
            assert 0<option['walk_minutes']<=40
            assert set(option['sources'])<=data['sources'].keys()
    return data


def station_options():
    return sorted({s for line in transit_data()['lines'] for s in line['stations']})


def validate_station(station):
    if station and station not in station_options():
        raise ValueError('出发站不在当前支持的港铁线路中，请从列表选择。')
    return station


def rail_path(origin, destination):
    """Dijkstra over (station, line); ride=3, interchange=8 planning minutes."""
    validate_station(origin);validate_station(destination)
    if not origin or not destination:
        raise ValueError('请选择起止港铁站。')
    data=transit_data();lines={line['id']:line for line in data['lines']}
    memberships={s:[line['id'] for line in lines.values() if s in line['stations']] for s in station_options()}
    serial=itertools.count();queue=[];best={}
    for line in memberships[origin]:heapq.heappush(queue,(0,next(serial),(origin,line),[]))
    while queue:
        cost,_,node,path=heapq.heappop(queue)
        if node in best:continue
        best[node]=cost
        station,line_id=node
        if station==destination:return {'edges':path,'cost':cost}
        line=lines[line_id];index=line['stations'].index(station);neighbors=[]
        for direction in [-1,1]:
            j=index+direction
            if 0<=j<len(line['stations']):
                target=line['stations'][j]
                terminal=(line.get('forward_direction',line['stations'][-1]) if direction>0 else line['stations'][0])
                neighbors.append(((target,line_id),3,{'kind':'ride','line_id':line_id,'from':station,'to':target,'direction':terminal}))
        for next_line in memberships[station]:
            if next_line!=line_id:neighbors.append(((station,next_line),8,{'kind':'transfer','station':station,'to_line':next_line}))
        for link in data['walking_interchanges']:
            if station not in link['stations']:continue
            target=next(s for s in link['stations'] if s!=station)
            for next_line in memberships[target]:
                neighbors.append(((target,next_line),link['minutes'],{'kind':'station_walk','from':station,'to':target,'text':link['note']}))
        for target,weight,edge in neighbors:
            if target not in best:heapq.heappush(queue,(cost+weight,next(serial),target,path+[edge]))
    raise ValueError('当前线路资料无法连接这两个站，请使用港铁官方行程指南。')


def rail_steps(path):
    lines={line['id']:line for line in transit_data()['lines']};steps=[]
    for edge in path['edges']:
        if edge['kind']=='ride':
            line=lines[edge['line_id']]
            if steps and steps[-1]['kind']=='ride' and steps[-1]['line_id']==edge['line_id'] and steps[-1]['direction']==edge['direction']:
                steps[-1]['stations'].append(edge['to']);steps[-1]['to']=edge['to']
            else:
                steps.append({**edge,'line_name':line['name'],'color_name':line['color_name'],'stations':[edge['from'],edge['to']]})
        elif edge['kind']=='transfer':
            line=lines[edge['to_line']]
            steps.append({**edge,'text':f"在{edge['station']}站换乘{line['name']}（{line['color_name']}），跟随站内换乘标识。"})
        else:
            steps.append({**edge,'text':f"由{edge['from']}站步行换至{edge['to']}站：{edge['text']}"})
    for step in steps:
        if step['kind']=='ride':
            step['stop_count']=len(step['stations'])-1
            step['text']=f"在{step['from']}站乘{step['line_name']}（{step['color_name']}），往{step['direction']}方向，坐 {step['stop_count']} 站至{step['to']}站下车。"
    return steps


def _sources(keys):
    return [copy.deepcopy(transit_data()['sources'][key]) for key in dict.fromkeys(['network',*keys])]


def access_for(place_id):
    get_place(place_id)
    access=copy.deepcopy(transit_data()['access'][place_id])
    access['sources']=_sources(key for option in access['options'] for key in option['sources'])
    access['checked']=transit_data()['checked']
    return access


def _connector_steps(connector, reverse=False, place_name=''):
    if connector=='peak_tram':
        return [{'kind':'tram','text':'在山顶总站乘山顶缆车下行至花园道中环总站；排队与停运情况须查官方。' if reverse else
                 '在花园道山顶缆车中环总站乘山顶缆车往山顶总站，下车后按山顶观景区标识步行；排队与停运情况须查官方。'}]
    if connector in {'ngong_ping_bus','tai_o_bus'}:
        number,target=('23','昂坪') if connector=='ngong_ping_bus' else ('11','大澳')
        text=(f'步行至{target}巴士总站，乘新大屿山巴士 {number} 号往东涌达东路巴士总站，下车后步行至东涌站 B 入口。' if reverse else
              f'在东涌达东路巴士总站乘新大屿山巴士 {number} 号往{target}，于{target}总站下车，再按{place_name or target}路牌步行。')
        return [{'kind':'bus','number':number,'text':text+' 班次、尾班与停运请查运营方。'}]
    return []


def _connector_minutes(connector):
    return {'':0,'peak_tram':45,'ngong_ping_bus':75,'tai_o_bus':75}[connector]


def _arrival(option,access,place_name):
    return [{'kind':'exit','station':option['station'],'exit':option['exit'],
             'text':f"在{option['station']}站从 {option['exit']} 出口出站。"},
            {'kind':'walk','minutes':option['walk_minutes'],
             'text':option['walk_note']+f" 步行预留约 {option['walk_minutes']} 分钟（项目估算）。"},
            *_connector_steps(access['connector'],place_name=place_name)]


def _guide(steps,mode,minutes,keys,**extra):
    note=('步行衔接按本地近似坐标及街区判断，未核对街道级路径；所附港铁资料不代表该步行路线已经导航验证。' if mode=='walk' else
          '线路与出口依据官方资料整理；站数和换乘由本地线路图计算。时长为估算，不含实时延误，不保证最快或无障碍；出发前核对出口及运营状态。')
    return {'mode':mode,'steps':steps,'estimated_minutes':minutes,'live':False,
            'sources':_sources(keys),'checked':transit_data()['checked'],'version':transit_data()['version'],
            'notice':note,**extra}


def from_station(station,place_id):
    validate_station(station);place=get_place(place_id);access=access_for(place_id)
    if not station:
        option=access['options'][0]
        return _guide(_arrival(option,access,place['name']),'access_only',None,option['sources'],
                      title='如何到达首站',origin_station=None,destination_station=option['station'],
                      missing_origin=True,origin_note='尚未选择出发站：下面先给到站后的出口和接驳；选择出发港铁站后可补全上车与换乘。')
    candidates=[]
    for option in access['options']:
        path=rail_path(station,option['station'])
        candidates.append((path['cost']+option['walk_minutes'],option,path))
    _,option,path=min(candidates,key=lambda c:c[0]);steps=rail_steps(path)
    minutes=path['cost']+option['walk_minutes']+(5 if path['edges'] else 0)+_connector_minutes(access['connector'])
    return _guide([*steps,*_arrival(option,access,place['name'])],'mtr_access',minutes,option['sources'],
                  title=f"从{station}站出发",origin_station=station,destination_station=option['station'],missing_origin=False,
                  origin_note='首站时间指抵达景点时间；另预留从酒店走到出发站的时间。每天均从选定站出发，不自动假设酒店位置。')


def between_places(origin_id,destination_id,distance_km,walking_minutes):
    a,b=get_place(origin_id),get_place(destination_id)
    aa,bb=access_for(origin_id),access_for(destination_id)
    if origin_id==destination_id:
        return _guide([{'kind':'walk','text':'起点和终点是同一地点，无需乘车。'}],'walk',0,[],title='已在目的地')
    # Mountain and tram routes cannot be inferred from straight-line city geometry.
    if {aa['connector'],bb['connector']}=={'ngong_ping_bus','tai_o_bus'}:
        start,end=('大澳','昂坪') if aa['connector']=='tai_o_bus' else ('昂坪','大澳')
        return _guide([{'kind':'walk','text':f"从{a['name']}按路牌步行至{start}巴士总站。"},
                       {'kind':'bus','number':'21','text':f'乘新大屿山巴士 21 号往{end}，于{end}总站下车；先查当日班次与尾班。'},
                       {'kind':'walk','text':f"下车后按{b['name']}标识步行，山路不可按地图直线穿行。"}],
                      'bus',70,['nlb'],title=f"{a['name']} → {b['name']}")
    if ('peak' in {origin_id,destination_id}) and (b if origin_id=='peak' else a)['cluster']=='central':
        reverse=origin_id=='peak'
        steps=([*_connector_steps('peak_tram',True),{'kind':'walk','text':f"从花园道中环总站按街道地图步行至{b['name']}，留意山坡与路面指示。"}] if reverse else
               [{'kind':'walk','text':f"从{a['name']}按街道地图步行至花园道山顶缆车中环总站，预留约 20–30 分钟及上坡时间（项目估算）。"},*_connector_steps('peak_tram')])
        return _guide(steps,'tram',70,['peak','cen'],title=f"{a['name']} → {b['name']}")
    if distance_km<1 and aa['connector']==bb['connector']:
        return _guide([{'kind':'walk','text':f"从{a['name']}步行至{b['name']}。"}],
                      'walk',walking_minutes,[],title='邻近地点步行衔接')
    candidates=[]
    for start in aa['options']:
        for end in bb['options']:
            path=rail_path(start['station'],end['station'])
            candidates.append((start['walk_minutes']+path['cost']+end['walk_minutes'],start,end,path))
    base,start,end,path=min(candidates,key=lambda c:c[0])
    if not path['edges'] and not aa['connector'] and not bb['connector']:
        return _guide([{'kind':'walk','text':f"两地可从{start['station']}站周边街区衔接。由{a['name']}按街道地图步行至{b['name']}，无需进出站绕行；步行方案仍需现场确认。"}],
                      'walk',max(walking_minutes,start['walk_minutes']+end['walk_minutes']),start['sources']+end['sources'],title='同一车站周边，建议步行')
    depart=[{'kind':'walk','text':f"由{a['name']}步行至{start['station']}站 {start['exit']} 入口，预留约 {start['walk_minutes']} 分钟（估算），按站区图核对入口。"}]
    if aa['connector']:
        depart=[*_connector_steps(aa['connector'],True),{'kind':'walk','text':f"按路牌前往{start['station']}站 {start['exit']} 入口，预留约 {start['walk_minutes']} 分钟（估算）。"}]
    minutes=base+(5 if path['edges'] else 0)+_connector_minutes(aa['connector'])+_connector_minutes(bb['connector'])
    return _guide([*depart,*rail_steps(path),*_arrival(end,bb,b['name'])],'mtr',minutes,start['sources']+end['sources'],
                  title=f"{start['station']} → {end['station']}",origin_station=start['station'],destination_station=end['station'])


def enrich_plan(plan,start_station=None):
    """Rebuild old history references on read, without rewriting stored conversations."""
    if not plan:return plan
    from .planner import estimate_transfer
    value=copy.deepcopy(plan);station=validate_station(start_station if start_station is not None else value.get('start_station',''))
    value['history_transport_refreshed']=value.get('transit_version')!=transit_data()['version']
    value['start_station']=station;value['transit_version']=transit_data()['version']
    for day in value['days']:
        for stop in day['stops']:stop['transit_access']=access_for(stop['place']['id'])
        if day['stops']:day['start_guide']=from_station(station,day['stops'][0]['place']['id'])
        # Keep historical times and estimate metadata; add separately computed guide.
        for i,leg in enumerate(day['legs']):
            current=estimate_transfer(day['stops'][i]['place']['id'],day['stops'][i+1]['place']['id'])
            leg['transit_guide']=current['transit_guide']
    return value
