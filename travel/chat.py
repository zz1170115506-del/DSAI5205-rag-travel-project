"""Unified question / itinerary / follow-up API with local SQLite history."""
import asyncio
import json
import re
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ConfigDict, StrictBool

from .agent import AgentEngine, Trip
from .place_context import hydrate_context, next_context
from .conversation_memory import restore_memory
from .config import Settings
from .history import HistoryStore
from .maps import resolve_place, route_map
from .transit import enrich_plan, from_station
from .place_search import search_library
from .map_rag import supplement_with_map
from .streaming import chat_events
from typing import Literal

store = HistoryStore()
locks = {}
creation_lock = asyncio.Lock()


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    conversation_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    use_model: bool = False
    trip: Trip | None = None


class HistoryRequest(BaseModel):
    id: str = Field(pattern=r'^[a-f0-9]{32}$')


class HistoryFlagsRequest(HistoryRequest):
    model_config=ConfigDict(extra='forbid')
    favorite: StrictBool | None = None
    pinned: StrictBool | None = None


class HistoryRenameRequest(HistoryRequest):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=1,max_length=60)


class ResolveRequest(BaseModel):
    query: str = Field(min_length=2, max_length=100)


class LibrarySearchRequest(BaseModel):
    query: str = Field(default='',max_length=100)
    region: Literal['全部','香港岛','九龙','大屿山'] = '全部'


class RouteRequest(BaseModel):
    place_ids: list[str] = Field(min_length=2, max_length=6)


class WalkingMapRequest(BaseModel):
    origin_poi_id: str | None = Field(default=None,min_length=1,max_length=100)
    destination_poi_id: str | None = Field(default=None,min_length=1,max_length=100)
    origin_id: str = Field(min_length=1,max_length=80)
    destination_id: str = Field(min_length=1,max_length=80)


class TransitRequest(BaseModel):
    destination_id: str = Field(min_length=1,max_length=80)
    origin_station: str = Field(default='',max_length=30)
    origin_id: str | None = Field(default=None,min_length=1,max_length=80)


def explicit_name(question):
    q = question.strip(' ？?。')
    q = re.sub(r'^(请问|请介绍|介绍一下|帮我查一下|帮我找一下|介绍|查找)', '', q)
    q = re.sub(r'(在哪里|在哪儿|在哪|怎么去|的地址|地址是什么|是什么地方|有什么特色|有什么特点)$', '', q).strip()
    if 2 <= len(q) <= 60 and q != question.strip(' ？?。') and not any(w in q for w in ['推荐', '有哪些', '什么景点', '行程', '几天', '天气', '票价']):
        return q
    return None


def build_router(settings_getter, semaphore):
    router = APIRouter()

    @router.get('/api/history')
    def history_list():
        return {'conversations': store.list(), 'storage': 'local_sqlite', 'capacity': store.capacity}

    @router.post('/api/history/read')
    def history_read(body: HistoryRequest):
        try:
            saved=store.get(body.id)
            for turn in saved['turns']:
                if turn['result'].get('plan'):
                    turn['result']['plan']=enrich_plan(turn['result']['plan'],turn['result'].get('trip',{}).get('start_station',''))
            return saved
        except KeyError:
            raise HTTPException(404, '这段历史不存在或已删除。')

    @router.post('/api/history/delete')
    def history_delete(body: HistoryRequest):
        if locks.get(body.id) and locks[body.id].locked():
            raise HTTPException(409, '这段对话仍在处理中，请等待完成后删除。')
        store.delete(body.id)
        locks.pop(body.id, None)
        return {'deleted': True}

    @router.post('/api/history/update')
    def history_update(body: HistoryFlagsRequest):
        try:
            saved=store.update_flags(body.id,favorite=body.favorite,pinned=body.pinned)
            return {key:saved[key] for key in ('id','favorite','pinned')}
        except KeyError:
            raise HTTPException(404,'这段历史不存在或已删除。')
        except ValueError as exc:
            raise HTTPException(422,str(exc))

    @router.post('/api/history/rename')
    def history_rename(body: HistoryRenameRequest):
        try:return store.rename(body.id,body.title)
        except KeyError:raise HTTPException(404,'这段历史不存在或已删除。')
        except ValueError as exc:raise HTTPException(422,str(exc))

    @router.post('/api/places/resolve')
    async def resolve(body: ResolveRequest):
        async with semaphore:
            return await resolve_place(body.query, settings_getter())

    @router.post('/api/places/search')
    async def library_search(body: LibrarySearchRequest):
        try:
            async with semaphore:
                return await search_library(body.query,body.region,settings_getter())
        except ValueError as exc:
            raise HTTPException(422,str(exc))

    @router.post('/api/transit/route')
    def transit_route(body: TransitRequest):
        try:
            if body.origin_id:
                if body.origin_station:raise ValueError('请选择出发站或起点景点其中一种。')
                from .planner import estimate_transfer
                return estimate_transfer(body.origin_id,body.destination_id)['transit_guide']
            return from_station(body.origin_station,body.destination_id)
        except ValueError:
            raise HTTPException(422,'请使用已收录的港铁站或景点，并且只指定一种起点。')

    @router.post('/api/amap/route')
    async def route(body: RouteRequest):
        try:
            async with semaphore:
                return await route_map(body.place_ids, settings_getter())
        except ValueError:
            raise HTTPException(422, '请使用 2–6 个不同且有效的本地地点。')

    @router.post('/api/walking-map')
    async def walking_map(body: WalkingMapRequest):
        from .planner import estimate_transfer
        from .knowledge import get_place
        try:
            get_place(body.origin_id);get_place(body.destination_id)
            if body.origin_id == body.destination_id or estimate_transfer(body.origin_id,body.destination_id)['transit_guide']['mode'] != 'walk':
                raise ValueError('not a local walking leg')
        except (ValueError,KeyError):
            raise HTTPException(422,'请选择行程中两个不同的邻近步行地点；港铁、山区及跨海段请使用对应交通指引。')
        async with semaphore:
            choices={pid:choice for pid,choice in [(body.origin_id,body.origin_poi_id),(body.destination_id,body.destination_poi_id)] if choice}
            return await route_map([body.origin_id,body.destination_id],settings_getter(),poi_choices=choices)

    async def chat(body: ChatRequest):
        cfg = settings_getter()
        if body.use_model and not cfg.model_api_key:
            raise HTTPException(422, '模型尚未配置，请关闭模型选项后重试。')
        q = body.question.strip()
        if len(q) < 2:
            raise HTTPException(422, '请输入至少两个字。')
        for key in [cfg.model_api_key, cfg.amap_api_key]:
            if key:
                q = q.replace(key, '[redacted]')
        cid = body.conversation_id or secrets.token_hex(16)
        async with creation_lock:
            if cid not in locks:
                if len(locks) >= store.capacity + 4:
                    # Only idle entries may be discarded; persisted history remains on disk.
                    for old in list(locks):
                        if not locks[old].locked():
                            del locks[old]
                locks.setdefault(cid, asyncio.Lock())
        lock = locks[cid]
        if lock.locked():
            raise HTTPException(409, '当前对话仍在处理，请稍等。')
        async with lock:
            saved = None
            if body.conversation_id:
                try:
                    saved = store.get(cid)
                except KeyError:
                    raise HTTPException(404, '历史已删除，请开始新对话。')
            elif len(store.list()) >= store.capacity:
                raise HTTPException(409, '历史已达 25 段，请先删除一段。')
            engine = AgentEngine(cfg if body.use_model else Settings())
            config = {'configurable': {'thread_id': 'chat'}}
            if saved:
                await engine.graph.aupdate_state(config, {**saved['checkpoint'],**restore_memory(saved),'place_context':hydrate_context(saved)}, as_node='finish')
            try:
                async with semaphore:
                    turn_started = time.monotonic()
                    result = await engine.turn('chat', q, body.trip.model_dump() if body.trip else None)
                    result.pop('session_id', None)
                    # Explicit named-place questions should not be satisfied by an incidental
                    # bigram match. General travel/itinerary queries keep ordinary retrieval.
                    name = explicit_name(q)
                    intent = (await engine.graph.aget_state(config)).values.get('intent')
                    if intent == 'search' and result['stop_reason']=='complete' and not result['plan']:
                        from .retrieval import exact_places
                        named_miss = bool(name and not exact_places(name))
                        if (named_miss or not result['sources']) and (named_miss or result['answer'].get('kind')!='clarify'):
                            query=next((step.get('arguments',{}).get('query') for step in reversed(result['trace']) if step.get('tool')=='search_places' and step.get('status') in ('success','empty')),q)
                            await supplement_with_map(result,q,(name or query)[:100],cfg,body.use_model,
                                lookup=resolve_place,time_budget=max(.1,65-(time.monotonic()-turn_started)))
                    result['metrics']['elapsed_ms'] = round((time.monotonic()-turn_started)*1000)
                state = (await engine.graph.aget_state(config)).values
                history = state.get('history', [])
                if history:
                    history[-1] = {'role': 'assistant', 'content': result['answer']['text']}
                context=next_context(state.get('place_context',{}),result) if result.get('external_lookup') else state.get('place_context',{})
                result['place_context']=context
                checkpoint = {'trip': result['trip'], 'history': history[-24:] if body.use_model else history[-8:], 'intent': state.get('intent', 'search'),'place_context':context,'plan_context':state.get('plan_context'),'memory_notes':state.get('memory_notes',[])}
                # No credentials or session capability token in persisted result/checkpoint.
                result['conversation_id'] = cid
                encoded = json.dumps({'result': result, 'checkpoint': checkpoint}, ensure_ascii=False)
                for key in [cfg.model_api_key, cfg.amap_api_key]:
                    if key:
                        encoded = encoded.replace(key, '[redacted]')
                clean = json.loads(encoded)
                turns = (saved['turns'] if saved else []) + [{'question': q, 'result': clean['result']}]
                store.save(cid, turns, clean['checkpoint'], body.use_model, saved['title'] if saved else q)
                return clean['result']
            except ValueError as exc:
                # Only locally generated validation messages are exposed; never provider exceptions.
                raise HTTPException(422, '请检查日期、旅行天数及行程条件；历史过大时请开始新对话。') from None

    @router.post('/api/chat')
    async def chat_endpoint(body: ChatRequest, request: Request, stream: bool = False):
        if stream or 'application/x-ndjson' in request.headers.get('accept', ''):
            return StreamingResponse(chat_events(lambda: chat(body)), media_type='application/x-ndjson',
                                     headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-store'})
        return await chat(body)

    return router
