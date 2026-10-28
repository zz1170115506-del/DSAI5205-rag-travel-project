from types import SimpleNamespace
import json
import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from app.agent.planner import make_plan, Plan
from app.core.errors import ModelResponseError, public_error, validation_summary
from app.models import User, Conversation, Run, Message
from app.rag.provider import ModelProvider
from app.services.runs import RunManager

class PlannerStub:
    settings=SimpleNamespace(model_mode='remote')
    def __init__(self,response):self.response=response
    async def json_answer(self, *_):
        if isinstance(self.response,Exception):raise self.response
        return self.response

@pytest.mark.parametrize('response',[
    {'intent':'recommendation','queries':['景点'],'filters':{},'clarification':None},
    {'intent':'fact','queries':None,'filters':None},
    {'intent':'fact','queries':['景点'],'filters':{'setting':'室内'}},
    {'intent':'fact','queries':['景点'],'filters':{'max_price':-20}},
    {'intent':'fact','queries':['景点'],'filters':{'sql':'DROP TABLE users'}},
    {'intent':'fact','queries':['x'*2500],'filters':{}},
    {'intent':'fact','queries':['a','b','c','d'],'filters':{}},
    ModelResponseError('invalid structure'),
])
async def test_invalid_model_plans_fall_back_without_losing_local_constraints(stack,response):
    plan,state=await make_plan('演示尖沙咀区有哪些室内景点？',[],{},stack[2],PlannerStub(response))
    assert plan.queries==['演示尖沙咀区有哪些室内景点？']
    assert plan.filters['district']=='district_tst' and plan.filters['setting']=='indoor'
    assert 'sql' not in plan.filters
    assert plan._diagnostics[0]['code']=='PLANNER_SCHEMA_FALLBACK'

async def test_null_model_filters_do_not_erase_current_constraints(stack):
    response={'intent':'fact','queries':['室内景点'],'filters':{'setting':None,'max_price':None}}
    plan,_=await make_plan('室内景点',[],{'max_price':50},stack[2],PlannerStub(response))
    assert plan.filters['setting']=='indoor' and plan.filters['max_price']==50

async def test_long_user_question_uses_bounded_retrieval_queries(stack):
    question='演示景点'*700
    plan,_=await make_plan(question,[],{},stack[2],PlannerStub(ModelResponseError('bad')))
    assert ''.join(plan.queries)==question and all(len(q)<=1800 for q in plan.queries)

async def test_bad_planner_structure_still_completes_the_run(stack,monkeypatch):
    settings,factory,search,_=stack
    class Provider:
        def __init__(self,s):
            self.inner=ModelProvider(s);self.settings=SimpleNamespace(model_mode='remote')
        @property
        def calls(self):return self.inner.calls+1
        @property
        def usage(self):return self.inner.usage
        async def json_answer(self,*_):return {'intent':'recommendation','queries':None,'filters':None}
        async def embed(self,texts):return await self.inner.embed(texts)
        async def generate(self,payload):
            async for token in self.inner.generate(payload):yield token
    monkeypatch.setattr('app.services.runs.ModelProvider',Provider)
    with factory.begin() as db:
        user=User(auth_token_hash='d'*64);db.add(user);db.flush()
        session=Conversation(user_id=user.user_id);db.add(session);db.flush()
        user_id,session_id=user.user_id,session.session_id
    manager=RunManager(factory,settings,search)
    run_id=await manager.create(session_id,user_id,'演示历史馆有什么？','schema-regression')
    await manager.runtime[run_id].task
    with factory() as db:
        run=db.get(Run,run_id)
        assert run.status=='completed'
        assert run.trace[0]['diagnostics'][0]['code']=='PLANNER_SCHEMA_FALLBACK'
        answer=db.scalar(select(Message).where(Message.run_id==run_id,Message.role=='assistant'))
        assert answer.content and answer.citations
    await manager.close()

def test_public_errors_are_specific_and_do_not_echo_sensitive_response():
    request=httpx.Request('POST','https://provider.invalid/chat')
    error=httpx.HTTPStatusError('secret-key-should-not-leak',request=request,response=httpx.Response(401,request=request))
    code,message=public_error(error)
    assert code=='MODEL_AUTH_ERROR' and 'secret-key' not in message
    assert public_error(TimeoutError())[0]=='MODEL_TIMEOUT'
    assert public_error(ModelResponseError('private-input'))[0]=='MODEL_RESPONSE_FORMAT'
    try:Plan.model_validate({'intent':'private-input'})
    except ValidationError as exc:assert 'private-input' not in json.dumps(validation_summary(exc))
