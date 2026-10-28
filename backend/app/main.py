import asyncio
import hashlib
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.db import database
from app.memory.preferences import read_profile, save_preference
from app.models import Attraction, Conversation, Entity, Image, Message, Preference, Relation, Run, Source, User, now
from app.rag.ingestion.pipeline import safe_path
from app.rag.retrieval.search import SearchEngine, SearchRequest
from app.services.runs import RunManager, TERMINAL


class NewRun(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(min_length=1, max_length=64)


class PreferencePatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool | None = None
    values: dict = Field(default_factory=dict)


def create_app(settings=None):
    settings = settings or get_settings()
    engine, factory = database(settings.database_url)
    search = SearchEngine(factory, settings)
    manager = RunManager(factory, settings, search)

    @asynccontextmanager
    async def lifespan(app):
        manager.recover()
        try:
            await asyncio.to_thread(search.load)
        except (OSError, ValueError, KeyError):
            pass  # health/ready reports missing/mismatched index; CLI bootstrap fixes it.
        yield
        await manager.close()
        engine.dispose()

    app = FastAPI(title='Hong Kong RAG Travel', version='1.0.0', lifespan=lifespan)
    app.state.factory, app.state.search, app.state.manager = factory, search, manager

    @app.middleware('http')
    async def origin_guard(request, call_next):
        if request.method in {'POST', 'PATCH', 'DELETE', 'PUT'}:
            origin = request.headers.get('origin')
            allowed = {x.strip() for x in settings.allowed_origins.split(',')}
            if origin and origin not in allowed:
                return JSONResponse({'code': 'ORIGIN_DENIED', 'message': 'Origin not allowed'}, status_code=403)
            if request.cookies.get('travel_token') and not request.headers.get('content-type', '').startswith('application/json'):
                return JSONResponse({'code': 'JSON_REQUIRED', 'message': 'Use application/json'}, status_code=415)
        return await call_next(request)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse({'code': f'HTTP_{exc.status_code}', 'message': str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # Never echo secrets or arbitrary input in error responses.
        return JSONResponse({'code': 'INVALID_REQUEST', 'message': 'Invalid fields',
                             'fields': [list(x['loc']) for x in exc.errors()]}, status_code=422)

    def auth(request: Request):
        token = request.cookies.get('travel_token', '')
        with factory() as db:
            user = db.scalar(select(User).where(User.auth_token_hash == hashlib.sha256(token.encode()).hexdigest(), User.status == 'active')) if token else None
            if not user:
                raise HTTPException(401, 'Create a guest session first')
            return user

    def owned_session(session_id, user):
        with factory() as db:
            session = db.get(Conversation, session_id)
            if not session or session.user_id != user.user_id:
                raise HTTPException(404, 'Session not found')
            return session

    def owned_run(run_id, user):
        with factory() as db:
            run = db.get(Run, run_id)
            if not run:
                raise HTTPException(404, 'Run not found')
            owned_session(run.session_id, user)
            return run

    @app.post('/api/v1/auth/guest')
    async def guest(request: Request, response: Response):
        try:
            user = auth(request)
        except HTTPException:
            token = secrets.token_urlsafe(32)
            with factory.begin() as db:
                user = User(auth_token_hash=hashlib.sha256(token.encode()).hexdigest())
                db.add(user)
                db.flush()
            response.set_cookie('travel_token', token, httponly=True, secure=settings.cookie_secure,
                                samesite='strict', max_age=60 * 60 * 24 * 90)
        return {'user_id': user.user_id, 'memory_enabled': user.memory_enabled,
                'model_mode': settings.model_mode, 'enable_graph': settings.enable_graph}

    @app.get('/api/v1/health/live')
    async def live():
        return {'status': 'alive', 'model_mode': settings.model_mode}

    @app.get('/api/v1/health/ready')
    async def ready():
        with factory() as db:
            db.execute(text('SELECT 1'))
        if search.matrix is None:
            raise HTTPException(503, 'Index is not ready; run bootstrap/build-index and restart API')
        return {'status': 'ready', 'index_version': search.manifest['index_version'],
                'model_mode': settings.model_mode,
                'synthetic_data': any(r.get('source_type') == 'synthetic' for r in search.rows)}

    @app.get('/api/v1/attractions')
    async def attractions(district: str | None = None, theme: str | None = None,
                          setting: str | None = None, limit: int = 100, offset: int = 0):
        if not 1 <= limit <= 100 or offset < 0:
            raise HTTPException(422, 'Invalid pagination')
        filters = SearchRequest(query='browse', district=district, theme=theme, setting=setting)
        allowed, _ = search.candidates(filters)
        with factory() as db:
            ids = sorted(allowed)[offset:offset + limit]
            return {'items': [attraction_data(db, x) for x in ids], 'total': len(allowed)}

    def attraction_data(db, key):
        a, e = db.get(Attraction, key), db.get(Entity, key)
        if not a or not e or e.status != 'active':
            raise HTTPException(404, 'Attraction not found')
        result = {c.name: getattr(a, c.name) for c in Attraction.__table__.columns}
        result.update(name_zh=e.name_zh, name_en=e.name_en)
        result['relations'] = [{'predicate': r.predicate, 'object_id': r.object_id,
            'name': db.get(Entity, r.object_id).name_zh, 'source_id': r.source_id}
            for r in db.scalars(select(Relation).where(Relation.subject_id == key, Relation.status == 'active'))]
        result['images'] = [{'id': i.image_id, 'url': f'/api/v1/images/{i.image_id}' if i.asset_path else i.remote_url,
            'caption': i.caption, 'author': i.author, 'license_note': i.license_note}
            for i in db.scalars(select(Image).where(Image.attraction_id == key).order_by(Image.sort_order))]
        return result

    @app.get('/api/v1/attractions/{key}')
    async def attraction(key: str):
        with factory() as db:
            return attraction_data(db, key)

    @app.get('/api/v1/images/{image_id}')
    async def image(image_id: str):
        with factory() as db:
            item = db.get(Image, image_id)
            if not item or not item.asset_path:
                raise HTTPException(404, 'Image not found')
            path = safe_path(settings.data_root, item.asset_path)
            if not path.is_file() or path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
                raise HTTPException(404, 'Image not found')
            return FileResponse(path)

    @app.post('/api/v1/search')
    async def do_search(body: SearchRequest, user=Depends(auth)):
        await ready()
        return await search.search(body)

    @app.post('/api/v1/sessions')
    async def new_session(user=Depends(auth)):
        with factory.begin() as db:
            session = Conversation(user_id=user.user_id)
            db.add(session)
            db.flush()
            return {'session_id': session.session_id}

    @app.get('/api/v1/sessions')
    async def sessions(user=Depends(auth)):
        with factory() as db:
            return [{'session_id': s.session_id, 'title': s.title, 'status': s.status} for s in db.scalars(
                select(Conversation).where(Conversation.user_id == user.user_id).order_by(Conversation.created_at.desc()).limit(50))]

    @app.get('/api/v1/sessions/{session_id}')
    async def session_detail(session_id: str, user=Depends(auth)):
        session = owned_session(session_id, user)
        with factory() as db:
            return {'session_id': session_id, 'constraints': session.constraints,
                'status': session.status, 'active_run_id': session.active_run_id,
                'messages': [{'message_id': m.message_id, 'role': m.role, 'content': m.content,
                              'status': m.status, 'citations': m.citations} for m in db.scalars(
                    select(Message).where(Message.session_id == session_id).order_by(Message.created_at))]}

    @app.post('/api/v1/sessions/{session_id}/runs')
    async def create_run(session_id: str, body: NewRun, user=Depends(auth)):
        await ready()
        owned_session(session_id, user)
        try:
            run_id = await manager.create(session_id, user.user_id, body.message, body.request_id)
            return {'run_id': run_id}
        except OverflowError:
            raise HTTPException(429, 'Too many active runs')

    @app.get('/api/v1/runs/{run_id}')
    async def get_run(run_id: str, user=Depends(auth)):
        run = owned_run(run_id, user)
        with factory() as db:
            messages = list(db.scalars(select(Message).where(Message.run_id == run_id, Message.role == 'assistant')))
            return {'run_id': run_id, 'status': run.status, 'usage': run.usage,
                'error_code': run.error_code, 'trace': run.trace,
                'answer': messages[-1].content if messages else '',
                'citations': messages[-1].citations if messages else []}

    @app.get('/api/v1/runs/{run_id}/events')
    async def events(run_id: str, request: Request, user=Depends(auth)):
        owned_run(run_id, user)
        async def stream():
            try:
                async for event in manager.events(run_id):
                    yield event
            finally:
                # A disconnected stream ends this run; normal completion is idempotent.
                await asyncio.shield(manager.cancel(run_id))
        return StreamingResponse(stream(), media_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @app.post('/api/v1/runs/{run_id}/cancel')
    async def cancel(run_id: str, user=Depends(auth)):
        owned_run(run_id, user)
        return {'run_id': run_id, 'status': await manager.cancel(run_id)}

    @app.get('/api/v1/me/preferences')
    async def preferences(user=Depends(auth)):
        with factory() as db:
            return {'enabled': user.memory_enabled,
                'values': {p.preference_key: p.value for p in db.scalars(select(Preference).where(
                    Preference.user_id == user.user_id, Preference.status == 'active'))}}

    @app.patch('/api/v1/me/preferences')
    async def patch_preferences(body: PreferencePatch, user=Depends(auth)):
        await manager.cancel_user(user.user_id)
        try:
            with factory.begin() as db:
                target = db.get(User, user.user_id)
                if body.enabled is not None:
                    target.memory_enabled = body.enabled
                for key, value in body.values.items():
                    save_preference(db, user.user_id, key, value)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return {'status': 'updated'}

    @app.delete('/api/v1/me/preferences/{key}')
    async def delete_preference(key: str, user=Depends(auth)):
        await manager.cancel_user(user.user_id)
        with factory.begin() as db:
            pref = db.scalar(select(Preference).where(Preference.user_id == user.user_id, Preference.preference_key == key))
            if pref:
                pref.value, pref.source_message_id, pref.status, pref.deleted_at = None, None, 'deleted', now()
        return {'status': 'deleted'}

    # Development preview only; Docker serves the same files through Nginx.
    frontend = settings.data_root.parent / "frontend"
    if not frontend.exists():
        from app.core.config import ROOT
        frontend = ROOT / "frontend"
    if frontend.exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()
