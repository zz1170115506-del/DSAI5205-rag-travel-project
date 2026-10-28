import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from travel.answers import rag_answer
from travel.agent import Sessions, Trip
from travel.trip_dates import MAX_TRIP_DAYS
from travel.config import ROOT, Settings
from travel.knowledge import INTERESTS, REGIONS, dataset, get_place, places, search
from travel.mcp_client import ToolError, amap_search, local_call
from travel.chat import build_router
from travel.retrieval import retrieve
from travel.embeddings import retrieval_status
from travel.web_access import WebAccess, DemoRateLimit, EXPENSIVE_PATHS

# 避免外部 HTTP 日志把带 key 的高德 URL 打印出来。
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

@asynccontextmanager
async def lifespan(app):
    # 先验证资料再启动服务，损坏的资料不会在用户点击后才变成不明 500。
    dataset()
    yield


app = FastAPI(title='港慢游 · Hong Kong Travel Assistant', version='1.3.0', docs_url=None, redoc_url=None, lifespan=lifespan)
settings = Settings.from_env()
web_access = WebAccess.from_env()
demo_rate_limit = DemoRateLimit()
app.add_middleware(TrustedHostMiddleware, allowed_hosts=web_access.allowed_hosts)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
# 单机演示：限制同时启动的 MCP 子进程数，避免连续点击堆积。
semaphore = asyncio.Semaphore(1 if web_access.public else 4)
agent_sessions = Sessions()
app.include_router(build_router(lambda: settings, semaphore, lambda: web_access.anonymous))


@app.get('/healthz')
def healthz():
    return {'status': 'ok'}


class AgentRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    session_id: str | None = Field(default=None, min_length=20, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    use_model: bool = False


@app.post('/api/agent')
async def agent_turn(body: AgentRequest):
    if len(body.question.strip()) < 2:
        raise HTTPException(422, '请输入至少两个字。')
    if body.use_model and not settings.model_api_key:
        raise HTTPException(422, '未配置模型，请关闭模型选项后体验本地规则演示。')
    try:
        token, session = agent_sessions.get(body.session_id, body.use_model, settings)
        if session.lock.locked():
            raise HTTPException(409, '此会话正在处理，请等待本轮结束。')
        async with session.lock:
            async with semaphore:
                return await session.engine.turn(token, body.question.strip())
    except KeyError:
        raise HTTPException(410, '会话已结束或过期，请开始新会话。')
    except ValueError:
        raise HTTPException(422, '请使用有效日期或旅行天数及支持的条件；切换模型模式前请清除会话。')
    except RuntimeError:
        raise HTTPException(429, '本地会话已满，请清除旧会话后重试。')


class AgentResetRequest(BaseModel):
    session_id: str = Field(min_length=20, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')


@app.post('/api/agent/reset')
async def delete_agent_session(body: AgentResetRequest):
    try:
        agent_sessions.delete(body.session_id)
    except RuntimeError:
        raise HTTPException(409, '本轮仍在处理，请等待后清除。')
    return {'deleted': True}


@app.middleware('http')
async def request_guard(request: Request, call_next):
    # Public demo credentials cover the UI, all APIs and shared conversation history.
    if web_access.anonymous and (request.url.path == '/api/history' or request.url.path.startswith('/api/history/')):
        return JSONResponse({'detail': '免登录演示不提供共享历史。'}, status_code=404,
                            headers={'Cache-Control': 'no-store'})
    if web_access.public and not web_access.anonymous and request.url.path != '/healthz':
        if not web_access.authorized(request.headers.get('authorization')):
            return JSONResponse({'detail': '请输入小组演示的访问用户名和密码。'}, status_code=401,
                headers={'WWW-Authenticate': 'Basic realm="Travel demo", charset="UTF-8"', 'Cache-Control': 'no-store'})
    if request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
        origin = request.headers.get('origin')
        expected_origin = web_access.origin if web_access.public else f'{request.url.scheme}://{request.headers.get("host")}'
        if origin and origin != expected_origin:
            return JSONResponse({'detail': '只接受同源页面的请求。'}, status_code=403)
        length = request.headers.get('content-length', '0')
        if not length.isdigit() or int(length) > 20_000:
            return JSONResponse({'detail': '请求过大。'}, status_code=413)
    expensive = ((request.method == 'POST' and request.url.path in EXPENSIVE_PATHS)
                 or (request.method == 'GET' and request.url.path == '/api/places' and request.query_params.get('q')))
    if web_access.public and expensive and not demo_rate_limit.allow():
        return JSONResponse({'detail': '演示请求较多，请稍后再试。'}, status_code=429,
                            headers={'Retry-After': '60', 'Cache-Control': 'no-store'})
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-cache' if request.url.path.startswith('/static/') else 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://images.unsplash.com https://tile.openstreetmap.org; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    return response


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    region: Literal['全部', '香港岛', '九龙', '大屿山'] = '全部'
    indoor_only: bool = False
    use_model: bool = False


class PlanRequest(Trip):
    days: int | None = Field(default=None, ge=1, le=MAX_TRIP_DAYS)
    region: Literal['全部', '香港岛', '九龙', '大屿山'] = '全部'
    interests: list[str] = Field(default_factory=lambda: ['海港夜景', '本地美食'], max_length=7)
    pace: Literal['轻松', '充实'] = '轻松'
    rain: bool = False
    public_only: bool = False
    must_visit: list[str] = Field(default_factory=list)
    start_station: str = Field(default='',max_length=30)


class AmapRequest(BaseModel):
    place_id: str = Field(min_length=1, max_length=80)


@app.get('/')
def index():
    return FileResponse(ROOT / 'static' / 'index.html')


@app.get('/api/status')
def status():
    from travel.transit import station_options, transit_data
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return {'history_enabled': not web_access.anonymous, 'today_hk': datetime.now(ZoneInfo('Asia/Hong_Kong')).date().isoformat(), 'max_trip_days': MAX_TRIP_DAYS, 'name': '港慢游', 'version': app.version, 'knowledge_version': dataset()['version'],
            'place_count': len(places()), 'model_configured': bool(settings.model_api_key),
            'retrieval': retrieval_status(),
            'model_name': settings.model_name if settings.model_api_key else None,
            'amap_configured': settings.amap_enabled and bool(settings.amap_api_key),
            'amap_enabled': settings.amap_enabled, 'amap_key_present': settings.amap_key_present or bool(settings.amap_api_key),
            'local_mcp': 'stdio', 'agent_framework': 'LangGraph',
            'interests': INTERESTS, 'regions': REGIONS, 'data_note': dataset()['editorial_note'],
            'transit_stations':station_options(),'transit_version':transit_data()['version']}


@app.get('/api/places')
def list_places(q: str = '', region: Literal['全部', '香港岛', '九龙', '大屿山'] = '全部'):
    if len(q) > 500:
        raise HTTPException(422, '搜索词过长。')
    result = retrieve(q, 10, region) if q.strip() else None
    found = result['results'] if result else [p for p in places() if region == '全部' or p['region'] == region]
    return {'places': found, 'retrieval': result['retrieval'] if result else None}


@app.post('/api/ask')
async def ask(body: AskRequest):
    question = body.question.strip()
    if len(question) < 2:
        raise HTTPException(422, '请输入至少两个字的问题。')
    q = question
    indoor = body.indoor_only or any(s in q for s in ['雨天', '下雨', '室内', '室內'])
    food_only = any(s in q for s in ['吃什么', '吃什麼', '吃饭', '美食', '小吃', '餐厅']) and not any(s in q for s in ['景点', '景點', '游玩'])
    try:
        async with semaphore:
            data, trace = await local_call('search_places', {'query': q, 'limit': 5, 'region': body.region,
                                                           'indoor_only': indoor, 'kind': 'food' if food_only else 'all'})
        hits = data['results']
        # 默认本地演示。即便填了 key，也由用户主动开启模型回答。
        chosen = settings if body.use_model else Settings()
        answer = await rag_answer(q, hits, chosen)
        if body.use_model and not settings.model_api_key:
            answer['notice'] = '未配置模型 Key，本次使用本地资料摘录。'
        cited = [p for p in hits if p['id'] in answer['citations']]
        return {'answer': answer, 'sources': cited, 'retrieved': hits, 'trace': [trace], 'retrieval': data.get('retrieval')}
    except Exception:
        raise HTTPException(503, '本地资料工具暂时不可用，请重试；若持续失败，请查看终端并重新启动。')


@app.post('/api/plan')
async def make_plan(body: PlanRequest):
    try:
        async with semaphore:
            data, trace = await local_call('plan_itinerary', body.model_dump())
        return {**data, 'trace': [trace]}
    except ToolError as exc:
        # SDK 工具校验失败，供用户调整条件。仅本地工具错误可这样返回。
        raise HTTPException(422, str(exc))
    except TimeoutError:
        raise HTTPException(503, '规划工具超时，请稍后重试。')
    except Exception:
        raise HTTPException(503, '规划工具暂不可用，请检查本地服务后重试。')


@app.post('/api/amap/search')
async def search_amap(body: AmapRequest):
    try:
        p = get_place(body.place_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not settings.amap_enabled:
        from travel.maps import unavailable
        return unavailable('disabled')
    async with semaphore:
        return await amap_search('香港 ' + p['name'], settings)
