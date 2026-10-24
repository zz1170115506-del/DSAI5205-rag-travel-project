"""约束筛选 + 按街区分组 + 近邻排序。所有时长均为规划假设。"""
import math
from .trip_dates import resolve_dates, date_for_day, parse_date

from .knowledge import INTERESTS, REGIONS, get_place, places
from .transit import access_for, between_places, from_station, transit_data, validate_station


def km_between(a, b):
    lat1, lat2 = math.radians(a['lat']), math.radians(b['lat'])
    dlat = lat2-lat1
    dlon = math.radians(b['lon']-a['lon'])
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371 * 2 * math.asin(min(1, math.sqrt(h)))


def estimate_transfer(origin_id: str, destination_id: str) -> dict:
    a, b = get_place(origin_id), get_place(destination_id)
    km = km_between(a, b)
    # 昂坪—大澳虽直线接近，山路绕行明显，不能用城区步行公式。
    mountain = a['region'] == b['region'] == '大屿山' and a['area'] != b['area']
    hill = 'peak' in [a['id'], b['id']]
    if mountain:
        mode, mins = '山区交通待查', 70
    elif hill:
        mode, mins = '上／下山交通待查', 60
    elif km < 1.0:
        mode, mins = '步行估算', max(10, math.ceil(km * 1.5 / 4 * 60) + 5)
    else:
        mode, mins = '公共交通估算', max(25, math.ceil(km * 1.6 / 18 * 60) + 20)
    guide=between_places(origin_id,destination_id,km,mins)
    mins=max(mins,guide['estimated_minutes'])
    return {'origin_id': origin_id, 'destination_id': destination_id,
            'straight_km': round(km, 2), 'minutes': mins, 'mode': mode,
            'basis': '人工近似坐标、直线距离与固定余量；不是导航路线或实时班次',
            'live': False, 'transit_guide':guide}


def _time(minutes):
    return f'{minutes // 60:02}:{minutes % 60:02}'


def schedule_day(calendar, ordered, title, start_station='', meal_note='其他餐饮请自行安排。'):
    group=ordered[0]['cluster']
    current, stops, legs = (13*60 if group == 'local' else 10*60), [], []
    for i, p in enumerate(ordered):
        if i:
            leg = estimate_transfer(ordered[i-1]['id'], p['id'])
            legs.append(leg)
            current += leg['minutes']
        before_slot = current
        if p['id'] in ['temple-street', 'hing-kee', 'peak']:
            current = max(current, 17*60 if p['id'] != 'hing-kee' else 18*60)
        free_minutes = current - before_slot
        start = current
        current += p['duration']
        stops.append({'place': p, 'start': _time(start), 'end': _time(current), 'minutes': p['duration'],
                      'free_before_minutes': free_minutes, 'transit_access':access_for(p['id'])})
    return {**calendar,'kind':'sightseeing','title':title,'stops':stops,'legs':legs,
            'start_guide':from_station(start_station,stops[0]['place']['id']),
            'transfer_minutes':sum(x['minutes'] for x in legs),'end':_time(current),'meal_note':meal_note}


def plan(days=None, region='全部', interests=None, pace='轻松', rain=False,
         public_only=False, must_visit=None, start_station='', start_date=None, end_date=None, only_selected=False, excluded_places=None) -> dict:
    days = resolve_dates(days, start_date, end_date) or 2
    validate_station(start_station)
    interests = ['海港夜景', '本地美食'] if interests is None else interests
    must_visit = list(dict.fromkeys(must_visit or []))
    if region not in REGIONS or pace not in ['轻松', '充实']:
        raise ValueError('请使用有效地区和游览节奏。')
    if any(t not in INTERESTS for t in interests):
        raise ValueError('发现未知兴趣，请从页面选项选择。')
    if only_selected and not must_visit:
        raise ValueError('请先选择要安排的地点。')
    excluded_places=set(excluded_places or [])
    for pid in excluded_places:get_place(pid)
    required = [get_place(pid) for pid in must_visit]

    def allowed(p):
        return (p['id'] not in excluded_places and (region == '全部' or p['region'] == region)
                and (not rain or p['indoor'])
                and (not public_only or p['cost'] == 'public' or p['kind'] == 'food'))

    conflicts = [p['name'] for p in required if not allowed(p)]
    if conflicts:
        raise ValueError('必去地点与当前地区、室内或公共空间条件冲突：' + '、'.join(conflicts) + '。请调整条件。')
    pool = [p for p in places() if allowed(p) and (not only_selected or p['id'] in must_visit)]
    def visit_candidate(p):return only_selected or p['kind']=='attraction'
    if not any(visit_candidate(p) for p in pool):
        raise ValueError('当前条件下没有可安排的景点资料。可取消“只选室内”、公共空间限制或扩大地区。')
    max_stops = 3 if pace == '轻松' else 4

    def score(p):
        return p['priority'] + 5 * len(set(p['tags']) & set(interests))

    # 每天围绕一个街区组合；必去地点优先，避免把大屿山塞进市区半天。
    groups = {}
    for p in pool:
        groups.setdefault(p['cluster'], []).append(p)
    required_groups = list(dict.fromkeys(p['cluster'] for p in required))
    required_slots=sum(math.ceil(sum(p['cluster']==g for p in required)/max_stops) for g in required_groups)
    if required_slots > days:
        raise ValueError(f'当前天数不足。已选 {len(required)} 个地点，按当前节奏和街区分布至少需要 {required_slots} 天游览；请增加天数或调整节奏。不会遗漏已选地点。')
    group_order = required_groups + sorted((g for g in groups if g not in required_groups),
                        key=lambda g: -sum(sorted([score(p) for p in groups[g] if p['kind'] == 'attraction'], reverse=True)[:3]))
    used = set()
    result, warnings = [], []
    def calendar_day(index):
        value = date_for_day(start_date, index) if start_date else None
        return {'day': index+1, 'date': value,
                'weekday': ['周一','周二','周三','周四','周五','周六','周日'][parse_date(value).weekday()] if value else None}

    def free_day(index):
        return {**calendar_day(index), 'kind':'flex', 'title':'休息与自由活动', 'stops':[], 'legs':[],
                'start_guide':None, 'transfer_minutes':0, 'end':'自由安排',
                'reason':'已按你的选择安排地点，本日保留为休息／自由活动日，未额外添加其他景点。' if only_selected else '当前符合条件的已收录地点不足以覆盖更多不重复游览日；保留此日供休息或自行补充。',
                'activities':[
                    {'period':'上午', 'text':'睡晚一点、酒店周边自由活动；住宿位置尚未提供，请自行确认周边环境。'},
                    {'period':'下午', 'text':'按体力休息、购物或补充自己想去的地点；具体地点及交通尚未核实。'},
                    {'period':'傍晚', 'text':'自由用餐，整理照片与后续行程；如为离港日，另行预留前往机场或车站的时间。'}],
                'meal_note':'本日没有新增已核实地点，餐饮与交通由你自行安排。'}

    visit_slots = min(days, sum(visit_candidate(p) for p in pool))
    visit_days = {round(i*(days-1)/(visit_slots-1)) for i in range(visit_slots)} if visit_slots>1 else {0}
    for day in range(days):
        remaining_days = sum(index>=day for index in visit_days)
        remaining_attractions = sum(visit_candidate(p) and p['id'] not in used for p in pool)
        # Spread visits through the selected calendar when data cannot fill every day.
        if day not in visit_days or not remaining_attractions:
            result.append(free_day(day))
            continue
        # Reserve capacity for every required place before filling optional areas.
        pending=[p for p in required if p['id'] not in used]
        group = next((g for g in group_order if any(p['cluster']==g for p in pending)), None)
        if group is None:
            group = next((g for g in group_order if any(p['id'] not in used and visit_candidate(p) for p in groups[g])), None)
        if group is None:
            result.append(free_day(day))
            continue
        candidates = [p for p in groups[group] if p['id'] not in used]
        essential = [p for p in candidates if p['id'] in must_visit]
        attraction = sorted([p for p in candidates if p['kind'] == 'attraction' and p not in essential], key=lambda p: -score(p))
        daily_target = min(max_stops, max(1, math.ceil(remaining_attractions/remaining_days)))
        other_slots=sum(math.ceil(sum(p['cluster']==g for p in pending)/max_stops) for g in required_groups if g!=group)
        available_days=max(1,remaining_days-other_slots)
        required_target=math.ceil(len(essential)/available_days)
        daily_target=min(max_stops,max(daily_target,required_target))
        essential=sorted(essential,key=lambda p:must_visit.index(p['id']))[:daily_target]
        chosen = essential + attraction[:max(0, daily_target-len(essential))]
        foods = sorted([p for p in candidates if p['kind'] == 'food' and p not in chosen], key=lambda p: -score(p))
        if foods and not only_selected:
            chosen.append(foods[0])
        # 公园／展览先游；晚餐食店和庙街延后。顺序是启发式，不是最优路线证明。
        night = [p for p in chosen if p['id'] in ['temple-street', 'hing-kee', 'peak']]
        visit = [p for p in chosen if p['kind'] == 'attraction' and p not in night]
        ordered = []
        while visit:
            anchor = ordered[-1] if ordered else max(visit, key=score)
            nxt = min(visit, key=lambda p: km_between(anchor, p))
            ordered.append(nxt)
            visit.remove(nxt)
        regular_food = [p for p in chosen if p['kind'] == 'food' and p not in night]
        for p in regular_food:
            ordered.insert(min(1, len(ordered)), p)
        ordered += night
        label = {'central':'中环与山顶', 'harbour':'尖沙咀与西九', 'local':'街区与港式味道', 'garden':'园林与传统文化', 'lantau':'昂坪与大澳','wan-chai':'湾仔文化漫步','causeway':'铜锣湾慢游'}[group]
        meal_note='餐饮候选不包含订位，其他正餐请自行安排。' if any(p['kind']=='food' for p in ordered) else ('按你的选择未额外加入餐饮地点，午餐与晚餐请自行安排。' if only_selected else '这个街区的餐饮资料不足，请自行安排午餐与晚餐。')
        result.append(schedule_day(calendar_day(day),ordered,label,start_station,meal_note))
        used.update(p['id'] for p in ordered)
        # 用过的组若仍有足够地点，可用于后续同地区游览。
        group_order.remove(group)
        group_order.append(group)
    scheduled = {stop['place']['id'] for d in result for stop in d['stops']}
    if not set(must_visit) <= scheduled:
        raise ValueError('现有规划容量无法容纳全部必去地点，请增加天数或减少必去地点。')
    flex_days = sum(d['kind']=='flex' for d in result)
    if flex_days:
        warnings.append(f'按你只安排已选地点的偏好，{flex_days} 天保留为休息／自由活动日，未额外添加其他地点。' if only_selected else f'资料覆盖有限，{flex_days} 天列为休息／自由活动日并保留完整日期；未重复安排相同地点，也未声称已核实自由活动的地点或交通。')
    warnings += ['时间表是可调整草案，未核验开放日、实时天气、票务和交通；出发前请核对各地点官网。',
                 '交通分钟数为本地估算，不含酒店往返，也不是高德导航结果。',
                 '未计算酒店、机票、门票和餐饮总费用，不能据此宣称满足总预算。']
    if rain:
        warnings.append('“只选室内”按资料标签筛选，不代表全天避雨；跨地点移动仍需户外交通。')
    if public_only:
        warnings.append('公共空间优先会排除门票／混合收费景点；用餐与交通仍需付费。')
    warnings.append('港铁线路与出口为官方资料的本地参考；乘车时长、步行和换乘余量为估算。首站时间指抵达景点，需另预留酒店到出发站及首程交通时间。')
    return {'only_selected':only_selected,'selected_place_ids':must_visit if only_selected else [],'start_date': start_date, 'end_date': end_date, 'days_requested': days, 'days': result,
            'coverage':{'calendar_days':len(result),'sightseeing_days':len(result)-flex_days,'flex_days':flex_days,'unique_places':len(scheduled)}, 'warnings': warnings,
            'start_station':start_station,'transit_version':transit_data()['version'],
            'algorithm': '条件筛选 → 街区分组 → 兴趣评分 → 近邻排序 → 停留与交通余量',
            'live_routes': False}
