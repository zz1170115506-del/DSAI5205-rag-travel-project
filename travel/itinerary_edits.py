"""Validate model-proposed edits and rebuild times/transfers from canonical records."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .conversation_memory import plan_snapshot
from .knowledge import get_place
from .planner import schedule_day
from .transit import transit_data
from .trip_dates import date_for_day,parse_date


class ItineraryEdit(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    action:Literal['remove','replace','move','add','swap_days']
    place_id:str|None=Field(default=None,max_length=80)
    replacement_id:str|None=Field(default=None,max_length=80)
    day:int|None=Field(default=None,ge=1,le=366)
    other_day:int|None=Field(default=None,ge=1,le=366)
    position:int|None=Field(default=None,ge=1,le=6)

    @model_validator(mode='after')
    def required(self):
        for value in (self.place_id,self.replacement_id):
            if value:get_place(value)
        if self.action=='swap_days':
            if not self.day or not self.other_day or self.day==self.other_day:raise ValueError('请指定两个不同日期。')
        elif not self.place_id:raise ValueError('请指定地点。')
        if self.action=='replace' and not self.replacement_id:raise ValueError('请指定替换地点。')
        if self.action in ('move','add') and not self.day:raise ValueError('请指定目标日期。')
        return self


class EditArgs(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    edits:list[ItineraryEdit]=Field(min_length=1,max_length=10)


def revise_plan(previous,trip,edits):
    snapshot=plan_snapshot(previous)
    if not snapshot:raise ValueError('还没有可修改的行程，请先生成行程。')
    if (trip['days'],trip.get('start_date'),trip.get('end_date'))!=(snapshot['days_requested'],snapshot['start_date'],snapshot['end_date']):
        raise ValueError('日期已改变，请使用规划工具按新日期生成行程。')
    days=[day['place_ids'][:] for day in snapshot['days']]
    def locate(pid):
        for day in days:
            if pid in day:return day,day.index(pid)
        raise ValueError('要修改的地点不在当前行程中。')
    def at(index):
        if not index or index>len(days):raise ValueError('日期超出当前行程。')
        return days[index-1]
    for raw in edits:
        edit=raw if isinstance(raw,ItineraryEdit) else ItineraryEdit.model_validate(raw)
        if edit.action=='swap_days':
            at(edit.day);at(edit.other_day);days[edit.day-1],days[edit.other_day-1]=days[edit.other_day-1],days[edit.day-1];continue
        if edit.action in ('remove','replace','move'):
            source,index=locate(edit.place_id)
            if edit.action in ('remove','replace') and edit.day is not None and source is not at(edit.day):raise ValueError('该地点不在指定日期，请核对当前行程。')
            if edit.action=='replace':source[index]=edit.replacement_id
            else:source.pop(index)
        if edit.action in ('move','add'):
            target=at(edit.day)
            target.insert(len(target) if edit.position is None else min(edit.position-1,len(target)),edit.place_id)
    ids=[pid for day in days for pid in day]
    if len(ids)!=len(set(ids)):raise ValueError('同一个地点不能重复安排。')
    if not set(trip['must_visit'])<=set(ids):raise ValueError('修改涉及必去地点，请先更新必去选择。')
    if trip['only_selected'] and set(ids)!=set(trip['must_visit']):raise ValueError('当前只安排已选地点，请先更新选择或取消该限制。')
    for pid in ids:
        p=get_place(pid)
        if pid in trip.get('excluded_places',[]) or (trip['region']!='全部' and p['region']!=trip['region']) or (trip['rain'] and not p['indoor']) or (trip['public_only'] and p['kind']!='food' and p['cost']!='public'):
            raise ValueError('修改地点与已确认的旅行条件冲突，请先询问用户调整。')
    result=[]
    for index,ids_on_day in enumerate(days):
        if len(ids_on_day)>(4 if trip['pace']=='轻松' else 5):raise ValueError('一天的停留点过多，请减少地点或分日安排。')
        date=date_for_day(trip['start_date'],index) if trip.get('start_date') else None
        calendar={'day':index+1,'date':date,'weekday':['周一','周二','周三','周四','周五','周六','周日'][parse_date(date).weekday()] if date else None}
        if ids_on_day:
            day=schedule_day(calendar,[get_place(pid) for pid in ids_on_day],'按你的修改安排行程',trip.get('start_station',''),'按你的修改保留地点，其他餐饮请自行安排。')
            if day['end']>'23:00':raise ValueError('本日交通和停留时间过长，请减少地点或分日安排。')
        else:
            day={**calendar,'kind':'flex','title':'休息与自由活动','stops':[],'legs':[],'start_guide':None,'transfer_minutes':0,'end':'自由安排','reason':'本日地点已按你的修改移除或调整，保留完整日期。','activities':[{'period':'自由安排','text':'可继续告诉我想补充的地点或保留休息。'}],'meal_note':'餐饮与交通请自行安排。'}
        result.append(day)
    flex=sum(not day['stops'] for day in result)
    return {'days':result,'start_date':trip.get('start_date'),'end_date':trip.get('end_date'),'days_requested':trip['days'],'only_selected':trip['only_selected'],'selected_place_ids':trip['must_visit'] if trip['only_selected'] else [],
            'coverage':{'calendar_days':len(result),'sightseeing_days':len(result)-flex,'flex_days':flex,'unique_places':len(ids)},
            'warnings':['仅修改你指定的地点或日期，其他日期保留；时间与交通已按当前顺序重新估算。','未核验开放日、实时天气、票务和交通；出发前请核对官网。','交通与时间为本地估算，不是实时导航，不保证最快或无障碍。'],
            'start_station':trip.get('start_station',''),'transit_version':transit_data()['version'],'algorithm':'模型提出修改 → 条件校验 → 保留其余日程 → 重新计算交通与时间','live_routes':False,'edited':True}
