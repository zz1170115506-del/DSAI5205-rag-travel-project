"""Validated trip preferences and conservative constraint extraction, shared by workflows."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from travel.rag.knowledge import INTERESTS, get_place, normalize, places
from travel.itinerary.transit import station_options, validate_station
from travel.itinerary.trip_dates import resolve_dates, MAX_TRIP_DAYS, parse_day_change

class Trip(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    days: int | None = Field(default=None, ge=1, le=MAX_TRIP_DAYS)
    start_date: str | None = None
    end_date: str | None = None
    region: Literal['全部', '香港岛', '九龙', '大屿山'] = '全部'
    interests: list[str] = Field(default_factory=lambda: ['海港夜景', '本地美食'], max_length=7)
    pace: Literal['轻松', '充实'] = '轻松'
    rain: bool = False
    public_only: bool = False
    must_visit: list[str] = Field(default_factory=list)
    start_station: str = Field(default='',max_length=30)
    only_selected: bool = False
    excluded_places: list[str] = Field(default_factory=list,max_length=33)

    @model_validator(mode='after')
    def travel_dates(self):
        self.days = resolve_dates(self.days, self.start_date, self.end_date)
        if self.only_selected and not self.must_visit:
            raise ValueError('只安排已选地点时，请先选择地点。')
        return self

    @field_validator('start_station')
    @classmethod
    def station_supported(cls,value):
        return validate_station(value)


def validate_trip(value):
    trip = Trip.model_validate(value)
    if any(i not in INTERESTS for i in trip.interests):
        raise ValueError('未知兴趣')
    for pid in trip.must_visit:
        get_place(pid)
    for pid in trip.excluded_places:get_place(pid)
    if set(trip.must_visit)&set(trip.excluded_places):raise ValueError('必去地点不能同时排除。')
    return trip.model_dump()


def extract_patch(question, current_days=None):
    """Conservative demo parser, also protects explicit supported constraints in model mode."""
    q = normalize(question)
    patch = {}
    for region, term in [('香港岛','hong kong island'), ('九龙','kowloon'), ('大屿山','lantau')]:
        if re.search(r'\b' + term + r'\b', question, re.I):
            patch['region'] = region
    if re.search(r'\b(?:all areas|any area|no area restriction)\b', question, re.I):patch['region']='全部'
    if re.search(r'\b(?:indoor only|indoors only|indoor places only)\b', question, re.I):patch['rain']=True
    if re.search(r'\b(?:include outdoor|indoor and outdoor|remove indoor restriction)\b', question, re.I):patch['rain']=False
    if re.search(r'\b(?:relaxed|gentle|less walking|parents|take it slow)\b', question, re.I):patch['pace']='轻松'
    elif re.search(r'\b(?:packed|full day|busy pace)\b', question, re.I):patch['pace']='充实'
    station_match=re.search(r'从(.{1,12}?)站出发',q)
    if station_match:
        station=next((s for s in station_options() if normalize(s)==station_match[1]),None)
        if station is None:raise ValueError('出发站尚未收录，请从出发港铁站列表选择。')
        patch['start_station']=station
    if any(w in q for w in ['清空出发站','取消出发站']):patch['start_station']=''
    region_question=re.sub(r'从.{1,12}?站出发','',q)
    for region, words in [('全部', ['不限地区', '不限区域']), ('香港岛', ['香港岛', '港岛']),
                          ('九龙', ['九龙']), ('大屿山', ['大屿山'])]:
        if any(w in region_question for w in words):
            patch['region'] = region
    day_change = parse_day_change(q)
    if day_change:
        patch['days'] = day_change.apply(current_days)
    dates = re.search(r'([0-9]{4}-[0-9]{2}-[0-9]{2})\s*(?:至|到|~|～|—|–|\bto\b)\s*([0-9]{4}-[0-9]{2}-[0-9]{2})', q)
    if dates:
        patch.update(start_date=dates[1], end_date=dates[2])
        patch['days'] = resolve_dates(patch.get('days'), dates[1], dates[2])
    if any(w in q for w in ['不限室内', '取消室内', '也去室外', '不用避雨']):
        patch['rain'] = False
    elif any(w in q for w in ['室内', '下雨', '雨天', '避雨']):
        patch['rain'] = True
    if any(w in q for w in ['少走', '父母', '轻松']):
        patch['pace'] = '轻松'
    elif any(w in q for w in ['充实', '多逛']):
        patch['pace'] = '充实'
    if '取消公共空间' in q:
        patch['public_only'] = False
    elif '只选公共空间' in q:
        patch['public_only'] = True
    if '清空必去' in q:
        patch['must_visit'] = []
        patch['only_selected'] = False
    elif '必去' in q or '一定去' in q:
        ids = [p['id'] for p in places() if normalize(p['name']) in q]
        if ids:
            patch['must_visit'] = ids
    if any(w in q for w in ['也安排其他','加些其他','增加其他','不只去','不用只安排']):patch['only_selected']=False
    return patch


class TripPatch(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    days:int|None=Field(default=None,ge=1,le=MAX_TRIP_DAYS)
    start_date:str|None=None
    end_date:str|None=None
    region:Literal['全部','香港岛','九龙','大屿山']|None=None
    interests:list[Literal['海港夜景','本地美食','文化艺术','自然散步','拍照','购物','城市漫步']]|None=Field(default=None,max_length=7)
    pace:Literal['轻松','充实']|None=None
    rain:bool|None=None
    public_only:bool|None=None
    must_visit:list[str]|None=None
    start_station:str|None=Field(default=None,max_length=30)
    only_selected:bool|None=None
    excluded_places:list[str]|None=Field(default=None,max_length=33)


class DayChangeArgs(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    operation:Literal['set','increase','decrease']
    amount:int=Field(ge=1,le=MAX_TRIP_DAYS)


class UpdateTripArgs(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    changes:TripPatch=Field(default_factory=TripPatch)
    notes:list[str]|None=Field(default=None,max_length=8)
    day_change:DayChangeArgs|None=None

    @model_validator(mode='after')
    def separate_duration_operations(self):
        if self.day_change and {'days','start_date','end_date'} & self.changes.model_fields_set:
            raise ValueError('day_change 不能与 days 或起止日期同时修改。')
        return self

    @field_validator('notes')
    @classmethod
    def bounded_notes(cls,value):
        if value is not None and any(not note.strip() or len(note)>160 for note in value):raise ValueError('偏好备注须为 1–160 字。')
        return value
