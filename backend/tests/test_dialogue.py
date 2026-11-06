import asyncio

import pytest
from sqlalchemy import select

from app.agent.planner import make_plan
from app.memory.preferences import explicit_preferences, save_preference, validate_preference
from app.models import Conversation, Message, Preference, Run, User
from app.rag.provider import ModelProvider
from app.services.runs import RunManager


def users(factory):
    with factory.begin() as db:
        user = User(auth_token_hash='a'*64,memory_enabled=True)
        db.add(user);db.flush()
        session=Conversation(user_id=user.user_id)
        db.add(session);db.flush()
        return user.user_id,session.session_id


async def test_plan_multiturn_and_current_conditions(stack):
    s,_,search,_=stack
    provider=ModelProvider(s)
    _, previous=await make_plan('演示历史馆介绍',[],{},search,provider)
    plan,_=await make_plan('和它同区还有哪些？',[],previous,search,provider)
    assert plan.filters['source_entity_id']=='attr_history'
    plan,_=await make_plan('改成户外',[],{'setting':'indoor'},search,provider)
    assert plan.filters['setting']=='outdoor'


async def test_graph_request_clarifies_without_referent(stack):
    plan,_=await make_plan('同区还有什么',[],{},stack[2],ModelProvider(stack[0]))
    assert plan.intent=='clarify' and plan.clarification


async def test_completed_run_commits_and_idempotency(stack):
    s,f,search,_=stack
    user,session=users(f)
    manager=RunManager(f,s,search)
    run=await manager.create(session,user,'演示历史馆有什么特色？','request1')
    assert await manager.create(session,user,'重复消息','request1')==run
    await manager.runtime[run].task
    with f() as db:
        assert db.get(Run,run).status=='completed'
        assert db.get(Conversation,session).active_run_id is None
        assert len(list(db.scalars(select(Message).where(Message.session_id==session))))==2
    await manager.close()


async def test_cancel_then_correct_never_commits_old_answer(stack):
    s,f,search,_=stack;s.mock_token_delay=.02
    user,session=users(f);manager=RunManager(f,s,search)
    old=await manager.create(session,user,'记住我喜欢历史文化，介绍演示历史馆','old')
    await asyncio.sleep(.04)
    new=await manager.create(session,user,'改成演示科学馆','new')
    await manager.runtime[new].task
    with f() as db:
        assert db.get(Run,old).status=='cancelled'
        assert db.get(Run,new).status=='completed'
        assert not list(db.scalars(select(Preference)))
        assert not list(db.scalars(select(Message).where(Message.run_id==old,Message.status=='completed')))
    await manager.close()


async def test_memory_written_only_with_explicit_optin(stack):
    s,f,search,_=stack
    user,session=users(f);manager=RunManager(f,s,search)
    run=await manager.create(session,user,'记住我喜欢历史文化','remember')
    await manager.runtime[run].task
    with f() as db:
        assert db.scalar(select(Preference)).value==['历史文化']
    assert explicit_preferences('我喜欢历史文化')=={}
    assert explicit_preferences('记住我避免户外')=={'avoidances':['户外']}
    await manager.close()


async def test_timeout_and_startup_recovery(stack):
    s,f,search,_=stack;s.run_timeout_seconds=.01;s.mock_token_delay=.2
    user,session=users(f);manager=RunManager(f,s,search)
    run=await manager.create(session,user,'演示历史馆介绍','slow')
    await manager.runtime[run].task
    with f.begin() as db:
        assert db.get(Run,run).status=='failed'
        db.get(Run,run).status='running'
    manager.recover()
    with f() as db: assert db.get(Run,run).status=='interrupted'
    await manager.close()


def test_preference_types():
    for key,value in [('interests','not a list'),('budget_hkd',-1),('language','xx'),('anything',1)]:
        with pytest.raises(ValueError): validate_preference(key,value)


async def test_clarification_checkpoint_resumes_relation_query(stack):
    s,f,search,_=stack
    user,session=users(f);manager=RunManager(f,s,search)
    first=await manager.create(session,user,'同区还有什么','ask')
    await manager.runtime[first].task
    with f() as db: assert db.get(Conversation,session).status=='awaiting_input'
    second=await manager.create(session,user,'演示历史馆','reply')
    await manager.runtime[second].task
    with f() as db:
        answer=db.scalar(select(Message).where(Message.run_id==second,Message.role=='assistant'))
        assert answer.citations and all(c['relation_paths'] for c in answer.citations)
    await manager.close()


def test_itinerary_limits_duration_and_reports_prices_without_money_filtering(stack):
    from app.agent.itinerary import arrange
    _,f,search,_=stack
    result=arrange(f,search.rows,{'max_minutes':120})
    assert result['known_visit_minutes']<=120
    assert result['known_admission_hkd']>=0
    assert result['attraction_ids']
    assert arrange(f,search.rows,{'max_minutes':120,'max_price':0})==result


def test_retired_price_preference_is_not_saved_or_used(stack):
    from app.memory.preferences import explicit_preferences, read_profile
    from app.models import User, now
    _,factory,_,_=stack
    with pytest.raises(ValueError):
        validate_preference('budget_hkd',200)
    assert explicit_preferences('记住我的预算200港币')=={}
    with factory.begin() as db:
        user=User(auth_token_hash='b'*64,memory_enabled=True)
        db.add(user);db.flush()
        db.add(Preference(user_id=user.user_id,preference_key='budget_hkd',value=200,status='active',
                          origin='user_edit',confirmed_at=now()))
        db.flush()
        assert read_profile(db,user)=={}


def test_unknown_prices_are_reported_separately_from_known_subtotal(stack):
    from app.agent.itinerary import arrange
    from app.models import Attraction
    _,factory,search,_=stack
    with factory.begin() as db:
        attraction=db.get(Attraction,'attr_history')
        attraction.ticket_price_min_hkd=None
        attraction.ticket_price_max_hkd=None
    result=arrange(factory,search.rows,{})
    assert 'attr_history' in result['attraction_ids']
    assert 'attr_history' in result['unknown_price_ids']
    assert result['admission_prices_complete'] is False
