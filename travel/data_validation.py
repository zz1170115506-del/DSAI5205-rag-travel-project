"""入库前校验：结构和来源可追溯，不替代人工阅读原网页。"""
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from typing import Literal

TAGS={'海港夜景','本地美食','文化艺术','自然散步','拍照','购物','城市漫步'}

class PlaceRecord(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    id:str=Field(pattern=r'^[a-z][a-z0-9-]{1,79}$')
    name:str=Field(min_length=1,max_length=100)
    en:str=Field(min_length=1,max_length=150)
    region:Literal['香港岛','九龙','大屿山']
    area:str=Field(min_length=1,max_length=80)
    cluster:Literal['central','harbour','local','garden','lantau','wan-chai','causeway']
    kind:Literal['attraction','food']
    tags:list[str]=Field(min_length=1,max_length=7)
    indoor:bool
    cost:Literal['public','mixed','ticket','meal']
    lat:float=Field(gt=22,lt=23)
    lon:float=Field(gt=113,lt=115)
    duration:int=Field(ge=10,le=240)
    priority:int=Field(ge=1,le=10)
    summary:str=Field(min_length=10,max_length=800)
    tip:str=Field(min_length=5,max_length=500)
    aliases:list[str]=Field(min_length=1,max_length=20)
    source:str
    source_title:str=Field(min_length=1,max_length=200)
    checked:str

    @field_validator('tags')
    @classmethod
    def known_tags(cls,v):
        if len(v)!=len(set(v)) or not set(v)<=TAGS:raise ValueError('标签未知或重复')
        return v

    @field_validator('source')
    @classmethod
    def official_source(cls,v):
        url=urlparse(v);host=url.hostname or ''
        if url.scheme!='https' or url.username or url.password or url.port not in (None,443) or not (host=='discoverhongkong.com' or host.endswith('.discoverhongkong.com')):
            raise ValueError('来源须为香港旅发局 HTTPS 页面；扩展运营方域名须先人工审查')
        return v

    @field_validator('checked')
    @classmethod
    def checked_date(cls,v):
        if date.fromisoformat(v)>date.today():raise ValueError('核对日期不能晚于本机日期')
        return v

    @field_validator('aliases')
    @classmethod
    def aliases_valid(cls,v):
        if any(not s.strip() or len(s)>100 for s in v):raise ValueError('别名为空或过长')
        return v

    @model_validator(mode='after')
    def consistent(self):
        expected={'central':'香港岛','harbour':'九龙','local':'九龙','garden':'九龙','lantau':'大屿山','wan-chai':'香港岛','causeway':'香港岛'}
        if expected[self.cluster]!=self.region:raise ValueError('街区与地区不一致')
        if (self.kind=='food')!=(self.cost=='meal'):raise ValueError('餐饮与费用标签不一致')
        return self

class KnowledgeDataset(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    version:str=Field(min_length=1)
    editorial_note:str=Field(min_length=10)
    places:list[PlaceRecord]=Field(min_length=1,max_length=1000)

    @model_validator(mode='after')
    def unique_ids(self):
        ids=[p.id for p in self.places]
        if len(ids)!=len(set(ids)):raise ValueError('地点 id 重复')
        return self

def load_validated(path:Path)->dict:
    return KnowledgeDataset.model_validate_json(path.read_text(encoding='utf-8')).model_dump()
