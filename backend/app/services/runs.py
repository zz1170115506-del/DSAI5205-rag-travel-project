import asyncio
import json
import logging
import time
from collections import deque
from contextlib import suppress

from sqlalchemy import select

from app.agent.planner import make_plan
from app.core.errors import public_error, validation_summary
from app.agent.itinerary import arrange
from app.memory.preferences import explicit_preferences, read_profile, save_preference
from app.models import Conversation, Message, Run, User, now, uid
from app.rag.provider import ModelProvider
from app.rag.retrieval.search import SearchRequest

TERMINAL = {'completed', 'cancelled', 'failed', 'interrupted'}
log = logging.getLogger(__name__)


class Runtime:
    def __init__(self):
        self.task = None
        self.events = deque(maxlen=2048)
        self.sequence = 0
        self.signal = asyncio.Event()
        self.text = ''
        self.stopped = False

    def emit(self, kind, run_id, **data):
        self.sequence += 1
        self.events.append({'type': kind, 'run_id': run_id, 'seq': self.sequence, **data})
        self.signal.set()


class RunManager:
    def __init__(self, factory, settings, search):
        self.factory, self.settings, self.search = factory, settings, search
        self.runtime = {}
        self.locks = {}

    def lock(self, session_id):
        return self.locks.setdefault(session_id, asyncio.Lock())

    def recover(self):
        with self.factory.begin() as db:
            for run in db.scalars(select(Run).where(Run.status.not_in(TERMINAL))):
                run.status, run.finished_at = 'interrupted', now()
            for session in db.scalars(select(Conversation).where(Conversation.active_run_id.is_not(None))):
                session.active_run_id = None

    async def create(self, session_id, user_id, text, request_id):
        async with self.lock(session_id):
            with self.factory.begin() as db:
                session = db.scalar(select(Conversation).where(Conversation.session_id == session_id).with_for_update())
                if not session or session.user_id != user_id:
                    raise LookupError('Session not found')
                existing = db.scalar(select(Run).where(Run.session_id == session_id, Run.request_id == request_id))
                if existing:
                    return existing.run_id
                active = sum(rt.task is not None and not rt.task.done() for rt in self.runtime.values())
                if active >= self.settings.max_active_runs:
                    raise OverflowError('Too many active requests')
                if session.active_run_id:
                    self.cancel_in_transaction(db, session.active_run_id)
                session.version += 1
                message_id, run_id = uid(), uid()
                db.add(Message(message_id=message_id, session_id=session_id, role='user',
                    content=text, status='submitted'))
                db.flush()
                db.add(Run(run_id=run_id, session_id=session_id, request_id=request_id,
                    input_message_id=message_id, session_version=session.version, status='queued'))
                db.flush()
                db.get(Message, message_id).run_id = run_id
                session.active_run_id = run_id
                if not session.title:
                    session.title = text[:80]
            runtime = self.runtime[run_id] = Runtime()
            runtime.emit('status', run_id, status='queued')
            runtime.task = asyncio.create_task(self.execute(run_id))
            # Retain only a bounded collection of completed event buffers.
            for key in list(self.runtime):
                if len(self.runtime) <= 128:
                    break
                rt = self.runtime[key]
                if rt.task and rt.task.done():
                    del self.runtime[key]
            return run_id

    def cancel_in_transaction(self, db, run_id):
        run = db.get(Run, run_id)
        if not run or run.status in TERMINAL:
            return
        run.status, run.cancel_requested_at, run.finished_at = 'cancelled', now(), now()
        runtime = self.runtime.get(run_id)
        if runtime:
            runtime.stopped = True
            runtime.emit('cancelled', run_id, status='cancelled')
            if runtime.task:
                runtime.task.cancel()
            if runtime.text:
                db.add(Message(session_id=run.session_id, run_id=run_id, role='assistant',
                    content=runtime.text, status='cancelled'))
        session = db.get(Conversation, run.session_id)
        if session.active_run_id == run_id:
            session.active_run_id = None

    async def cancel(self, run_id):
        with self.factory() as db:
            run = db.get(Run, run_id)
            if not run:
                raise LookupError('Run not found')
            session_id = run.session_id
        async with self.lock(session_id):
            with self.factory.begin() as db:
                db.scalar(select(Conversation).where(Conversation.session_id == session_id).with_for_update())
                self.cancel_in_transaction(db, run_id)
                return db.get(Run, run_id).status

    async def cancel_user(self, user_id):
        with self.factory() as db:
            ids = list(db.scalars(select(Conversation.active_run_id).where(
                Conversation.user_id == user_id, Conversation.active_run_id.is_not(None))))
        for run_id in ids:
            await self.cancel(run_id)

    def hook(self, runtime, calls):
        if runtime.stopped:
            raise asyncio.CancelledError
        if calls > self.settings.max_tool_calls:
            raise ValueError('Tool budget exceeded')

    async def execute(self, run_id):
        rt, started = self.runtime[run_id], time.perf_counter()
        provider, trace, evidence, usage = ModelProvider(self.settings), [], [], {}
        try:
            async with asyncio.timeout(self.settings.run_timeout_seconds):
                with self.factory.begin() as db:
                    run = db.get(Run, run_id)
                    if run.status == 'cancelled':
                        return
                    run.status, run.started_at = 'running', now()
                    session = db.get(Conversation, run.session_id)
                    message = db.get(Message, run.input_message_id)
                    user = db.get(User, session.user_id)
                    question, previous = message.content, session.constraints
                    if session.status == 'awaiting_input' and session.checkpoint:
                        question = session.checkpoint['question'] + '\n补充：' + question
                    history = [{'role': m.role, 'content': m.content} for m in db.scalars(
                        select(Message).where(Message.session_id == session.session_id,
                            Message.status.in_(['submitted', 'completed']))
                        .order_by(Message.created_at.desc()).limit(12))][::-1]
                    profile = read_profile(db, user) if self.settings.enable_memory else {}
                    session_id, user_id = session.session_id, user.user_id
                rt.emit('status', run_id, status='planning')
                self.hook(rt, 0)
                plan, state = await make_plan(question, history, previous, self.search, provider)
                trace.append({'tool': 'plan', 'intent': plan.intent, 'queries': plan.queries, 'diagnostics': plan._diagnostics})
                self.hook(rt, 1)
                # Save resolved constraints before slow generation, so an interrupted
                # answer can still be corrected using the current conversation state.
                async with self.lock(session_id):
                    with self.factory.begin() as db:
                        session = db.scalar(select(Conversation).where(Conversation.session_id == session_id).with_for_update())
                        current = db.get(Run, run_id)
                        if current.status in TERMINAL or session.active_run_id != run_id:
                            return
                        session.constraints = state
                        session.status, session.checkpoint = 'active', None
                if plan.clarification:
                    answer = plan.clarification
                    for part in [answer]:
                        rt.text += part
                        rt.emit('token', run_id, text=part)
                else:
                    seen = set()
                    for i, query in enumerate(plan.queries):
                        self.hook(rt, i + 2)
                        rt.emit('status', run_id, status='retrieving')
                        request = SearchRequest(query=query, **plan.filters)
                        result = await self.search.search(request, provider, profile)
                        trace.append({'tool': 'search', 'query': query,
                            'chunk_ids': [r['chunk_id'] for r in result['results']]})
                        for row in result['results']:
                            if row['chunk_id'] not in seen:
                                seen.add(row['chunk_id'])
                                evidence.append(row)
                    evidence = evidence[:8]
                    itinerary = None
                    if plan.intent == 'planning':
                        itinerary = arrange(self.factory, evidence, plan.filters)
                        chosen = set(itinerary['attraction_ids'])
                        evidence = [row for row in evidence if row['attraction_id'] in chosen]
                        trace.append({'tool': 'itinerary', **itinerary})
                    for i, row in enumerate(evidence, 1):
                        rt.emit('citation', run_id, number=i, citation=row)
                    rt.emit('status', run_id, status='generating')
                    self.hook(rt, len(plan.queries) + 2)
                    payload = {'question': question, 'history': history[-6:], 'constraints': plan.filters,
                        'profile': profile, 'intent': plan.intent, 'evidence': evidence,
                        'itinerary': itinerary}
                    first_token = None
                    async for token in provider.generate(payload):
                        self.hook(rt, len(plan.queries) + 2)
                        if first_token is None:
                            first_token = (time.perf_counter() - started) * 1000
                        rt.text += token
                        if len(rt.text) > 20000:
                            raise ValueError('Answer length limit exceeded')
                        rt.emit('token', run_id, text=token)
                    usage['ttft_ms'] = first_token
                self.hook(rt, len(plan.queries) + 2)
                async with self.lock(session_id):
                    with self.factory.begin() as db:
                        session = db.scalar(select(Conversation).where(Conversation.session_id == session_id).with_for_update())
                        run = db.get(Run, run_id)
                        if run.status in TERMINAL or session.active_run_id != run_id or session.version != run.session_version:
                            return
                        usage.update({'model_calls': provider.calls, 'provider_usage': provider.usage,
                            'total_ms': (time.perf_counter() - started) * 1000})
                        run.status, run.finished_at = 'completed', now()
                        run.index_version = self.search.manifest['index_version']
                        run.trace, run.usage = trace, usage
                        session.constraints, session.active_run_id = state, None
                        session.status = 'awaiting_input' if plan.clarification else 'active'
                        session.checkpoint = {'question': question, 'clarification': plan.clarification} if plan.clarification else None
                        db.add(Message(session_id=session_id, run_id=run_id, role='assistant',
                            content=rt.text, status='completed', citations=evidence))
                        message = db.get(Message, run.input_message_id)
                        user = db.get(User, user_id)
                        if self.settings.enable_memory and user.memory_enabled:
                            for key, value in explicit_preferences(question).items():
                                save_preference(db, user_id, key, value, message.message_id)
                        message.memory_processed_at = now()
                rt.emit('done', run_id, status='completed', usage=usage)
        except asyncio.CancelledError:
            # Cancellation is finalized by cancel() or shutdown recovery.
            raise
        except Exception as exc:
            code, public_message = public_error(exc)
            trace.append({'tool': 'error', 'code': code, 'validation': validation_summary(exc)})
            log.warning('run failed: %s code=%s type=%s', run_id, code, type(exc).__name__)
            with self.factory.begin() as db:
                run = db.get(Run, run_id)
                if run and run.status not in TERMINAL:
                    run.status, run.finished_at, run.error_code = 'failed', now(), code
                    run.trace = trace
                    session = db.get(Conversation, run.session_id)
                    if session.active_run_id == run_id:
                        session.active_run_id = None
                    if rt.text:
                        db.add(Message(session_id=run.session_id, run_id=run_id, role='assistant',
                            content=rt.text, status='partial', citations=evidence))
            rt.emit('error', run_id, status='failed', code=code,
                message=public_message + f'（任务编号：{run_id[:8]}）')
        finally:
            rt.signal.set()

    async def events(self, run_id):
        rt = self.runtime.get(run_id)
        if not rt:
            with self.factory() as db:
                run = db.get(Run, run_id)
                yield 'data: ' + json.dumps({'type': 'done', 'run_id': run_id, 'status': run.status}) + '\n\n'
            return
        cursor = 0
        while True:
            rt.signal.clear()
            if rt.events and rt.events[0]['seq'] > cursor + 1:
                yield 'data: ' + json.dumps({'type': 'error', 'run_id': run_id, 'code': 'BUFFER_EXPIRED'}) + '\n\n'
                return
            for event in list(rt.events):
                if event['seq'] > cursor:
                    cursor = event['seq']
                    yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
            if rt.task.done() and cursor == rt.sequence:
                break
            if rt.task.done():
                continue  # A final event may have arrived while yielding earlier tokens.
            try:
                await asyncio.wait_for(rt.signal.wait(), timeout=10)
            except TimeoutError:
                yield ': heartbeat\n\n'

    async def close(self):
        tasks = [r.task for r in self.runtime.values() if r.task and not r.task.done()]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        self.recover()
