"""Conditional conversation workflow with a separately committed current itinerary."""
import asyncio
import copy
import re
import time
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from pydantic import BaseModel, ConfigDict, Field

from travel.core.model import WorkflowModel
from travel.itinerary.itinerary_edits import ItineraryEdit, revise_plan
from travel.itinerary.journey import journey_turn, build_plan, local_mentions as mentioned_places, offline_intent
from travel.itinerary.planner import plan as create_plan
from travel.itinerary.preferences import Trip, TripPatch, extract_patch, validate_trip
from travel.itinerary.pricing import with_price_summary
from travel.itinerary.trip_dates import date_for_day
from travel.rag.knowledge import get_place, places
from travel.session.conversation_memory import bounded_history
from travel.workflows.rag import GroundedAnswer, agentic_answer


class RouteDecision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    route:Literal['modify_itinerary','travel_question','general_chat']
    standalone_question:str=Field(min_length=1,max_length=500)
    clarification:str|None=Field(default=None,max_length=500)
    also_answer:bool=False
    edits:list[ItineraryEdit]=Field(default_factory=list,max_length=10)
    changes:TripPatch=Field(default_factory=TripPatch)


class TurnState(TypedDict):
    decision:object
    answer:dict
    plan:object
    trip:dict
    changed:bool
    trace:list
    evidence:list
    discussed:list


def local_mentions(question):
    return [p['id'] for p in mentioned_places(question)]


def current_plan(saved):
    checkpoint=(saved or {}).get('checkpoint',{})
    return copy.deepcopy(checkpoint.get('journey_plan') or next((t['result']['plan']
        for t in reversed((saved or {}).get('turns',[])) if t.get('result',{}).get('plan')),None))


def offline_route(question,checkpoint,language='zh'):
    explicit=bool(re.search(r'\b(?:add|remove|replace|move|swap|change|extend|shorten|make it)\b|加入|加到|加进|添加|换成|换一个|换一下|改一下|替换|移到|挪到|互换|删掉|删除|去掉|取消|改成|改为|多加|多玩|少玩|安排.*行程|^\s*plan\b',question,re.I))
    general=bool(re.search(r'笑话|写诗|编程|数学|\b(?:joke|poem|coding|hello|hi|thank you)\b',question,re.I))
    standalone=question
    discussed=checkpoint.get('discussed_place_ids',[])
    if not local_mentions(question) and len(discussed)==1 and re.search(r'它|那里|\b(?:it|there|that place)\b',question,re.I):
        standalone=(get_place(discussed[0])['name']+' '+question)[:500]
    elif not explicit and not local_mentions(question) and len(discussed)!=1 and re.search(r'它|那里|\b(?:it|that place)\b',question,re.I):
        return RouteDecision(route='travel_question',standalone_question=question,
                             clarification='Which place do you mean?' if language=='en' else '你指的是哪个地点？')
    return RouteDecision(route='modify_itinerary' if explicit else 'general_chat' if general else 'travel_question',
        standalone_question=standalone,also_answer=explicit and bool(re.search(r'是什么|介绍|历史|tell me|what is',question,re.I)))


def requested_day(question):
    day_match=re.search(r'(?:第\s*([一二三四五六七八九十百两\d]+)\s*天|\bday\s*(\d+)\b)',question,re.I)
    day=None
    if day_match:
        value=day_match[1] or day_match[2]
        if value.isdigit():
            day=int(value)
        else:
            day,current=0,0
            for char in value:
                if char in '十百':
                    day+=(current or 1)*{'十':10,'百':100}[char];current=0
                else:
                    current={'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}[char]
            day+=current
    else:
        ordinal=re.search(r'\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth) day\b',question,re.I)
        if ordinal:
            day='first second third fourth fifth sixth seventh eighth ninth tenth'.split().index(ordinal[1].lower())+1
    if day is not None and not 1<=day<=366:
        raise ValueError('Invalid target day')
    return day


def local_edits(question,plan,checkpoint):
    selected=[s['place'] for d in plan['days'] for s in d['stops']]
    intent=offline_intent(question,selected)
    day=requested_day(question)
    edits=[]
    for change in intent.places:
        matches=local_mentions(change.query)
        if len(matches)!=1:
            continue
        pid=matches[0]
        if change.action=='remove':
            edits.append({'action':'remove','place_id':pid,**({'day':day} if day else {})})
        elif change.action=='replace':
            old=local_mentions(change.replaces or '')
            if len(old)==1:
                edits.append({'action':'replace','place_id':old[0],'replacement_id':pid,**({'day':day} if day else {})})
        elif re.search(r'挪|移|\bmove\b',question,re.I) and day:
            edits.append({'action':'move','place_id':pid,'day':day})
        elif re.search(r'加入|加到|加进|添加|\b(?:add|include)\b',question,re.I):
            edits.append({'action':'add','place_id':pid,'day':day or 1})
    if not edits and re.search(r'第二个|second',question,re.I):
        discussed=checkpoint.get('discussed_place_ids',[])
        if len(discussed)>=2 and re.search(r'加|\badd\b',question,re.I):
            edits=[{'action':'add','place_id':discussed[1],'day':day or 1}]
    return edits


async def conditional_turn(question,override,saved,settings,use_model,*,lookup,action='message',
                           expected_version=None,model=None):
    started=time.monotonic()
    checkpoint=copy.deepcopy((saved or {}).get('checkpoint',{}))
    previous=current_plan(saved)
    version=checkpoint.get('plan_version',1 if previous else 0)
    trip=validate_trip({**Trip().model_dump(),**checkpoint.get('trip',{})})
    history=bounded_history(checkpoint.get('history',[]))
    model=model or WorkflowModel(settings,use_model)
    english=settings.response_language=='en'

    def answer(text,kind='answer',**extra):
        return {'text':text,'citations':[],'kind':kind,'mode':'model' if use_model else 'local_demo',
                'notice':'Conversation workflow','retrieval_source':'none',**extra}

    async def route(s):
        if action=='create_plan':
            decision=RouteDecision(route='modify_itinerary',standalone_question=question)
        elif not previous:
            decision=RouteDecision(route='travel_question',standalone_question=question,
                clarification='Please plan your trip from the home page first.' if english else '请先从首页点击规划行程。')
        else:
            decision=await model.ask('route_message',
                'Classify intent using the conversation and current itinerary. '
                'Merely asking about or recommending a place MUST NOT modify an itinerary. '
                'Use modify_itinerary only for an explicit request to change the plan. '
                'Use travel_question for tourism, places, recommendations and travel facts; '
                'general_chat for unrelated topics. Resolve references from discussed places and history. '
                'For mixed requests set also_answer=true and provide the standalone factual question. '
                'Use clarification when the requested target or change is ambiguous. '
                'For local place changes, provide edits with supplied canonical IDs and exact day if specified. '
                'For a single added stop, return one add edit; never copy other existing stops into edits. '
                'Omit unchanged constraints and unused optional fields. Keep the standalone question concise. '
                'changes only contains explicitly requested trip constraints; preserve all other values. '
                'For duration changes, changes.days is the new TOTAL days, not the increment. '
                'Do not calculate start_date or end_date when only the duration changes; the server computes dates. '
                'No client monetary limits or price filtering are supported. Respond in '+settings.response_language+'.',
                {'question':question,'history':history[-8:],'current_trip':trip,'current_plan':{'version':version,'days':[
                    {'day':d['day'],'date':d.get('date'),'stops':[{'id':x['place']['id'],'name':x['place']['name']} for x in d['stops']]}
                    for d in previous['days'] if d['stops']]},
                 'discussed_places':checkpoint.get('discussed_place_ids',[]),
                 'pending_request':checkpoint.get('pending_request'),
                 'known_places':[{'id':p['id'],'name':p['name'],'en':p['en']} for p in places()]},RouteDecision)
            decision=decision or offline_route(question,checkpoint,settings.response_language)
        return {'decision':decision,'trace':[{'tool':'intent_router','status':'success',
                 'route':decision.route,'needs_clarification':bool(decision.clarification)}]}

    async def clarify(s):
        return {'answer':answer(s['decision'].clarification,'clarify')}

    async def tourism(s):
        query=s['decision'].standalone_question
        ids=local_mentions(query)
        rag=await agentic_answer(query,ids,model,settings,lookup,current_itinerary=previous)
        discussed=list(dict.fromkeys(r['place_id'] for r in rag['evidence'] if r.get('place_id') and
                                     any(p['id']==r['place_id'] for p in places())))
        return {'answer':answer(rag['answer']['text'],citations=rag['answer']['citations'],
                                model_output_accepted=rag['answer'].get('model_output_accepted',False),
                                retrieval_source='documents'),
                'evidence':rag['evidence'],'discussed':discussed,
                'trace':s['trace']+rag['trace']}

    async def general(s):
        response=await model.ask('general_conversation',
            'Have a normal helpful conversation in '+settings.response_language+'. '
            'You have no tools in this branch and cannot change the itinerary. Return no citations.',
            {'question':question,'history':history[-12:]},GroundedAnswer)
        if response:
            text=response.text
        elif not settings.model_api_key:
            text=('The AI service is not configured. Open-ended conversation is unavailable.' if english else
                  'AI 服务尚未配置，暂时无法进行自由对话。')
        else:
            text=('The AI service is unavailable. Please try again shortly.' if english else
                  'AI 服务暂时不可用，请稍后重试。')
        return {'answer':answer(text)}

    async def modify(s):
        if expected_version is not None and expected_version!=version:
            return {'answer':answer('The itinerary changed. Reload the latest journey before editing.' if english else
                                     '行程已更新，请载入最新行程后再修改。','clarify')}
        new_trip=copy.deepcopy(trip)
        try:
            if action=='create_plan':
                new_trip=validate_trip({**new_trip,**(override or {})})
                plan=await asyncio.to_thread(create_plan,**new_trip)
                new_trip['days']=plan['days_requested']
            else:
                decision=s['decision']
                changes=decision.changes.model_dump(exclude_unset=True,exclude_none=True)
                explicit=extract_patch(question,new_trip['days'])
                if not changes:
                    changes=explicit
                # Explicit duration arithmetic and inclusive calendar dates are server-owned.
                if 'days' in explicit:
                    changes['days']=explicit['days']
                    if (new_trip.get('start_date') and not re.search(r'\d{4}-\d{2}-\d{2}',question)
                            and not re.search(r'提前|推迟|延后|明天|后天|下周|\b(?:tomorrow|postpone|earlier|later|next week)\b',question,re.I)):
                        changes['start_date']=new_trip['start_date']
                        changes['end_date']=date_for_day(new_trip['start_date'],explicit['days']-1)
                edits=[e.model_dump(exclude_none=True) for e in decision.edits] or local_edits(question,previous,checkpoint)
                ids=[stop['place']['id'] for day in previous['days'] for stop in day['stops']]
                # Keep selected/excluded constraints synchronized with explicit edits.
                for edit in edits:
                    pid=edit.get('place_id')
                    if edit['action'] in ('remove','replace') and pid in ids:
                        ids.remove(pid)
                    if edit['action'] in ('replace','add'):
                        target=edit.get('replacement_id') or pid
                        if target not in ids:
                            ids.append(target)
                if 'days' in changes and new_trip.get('start_date') and not {'start_date','end_date'}&changes.keys():
                    changes['end_date']=date_for_day(new_trip['start_date'],changes['days']-1)
                removed={e['place_id'] for e in edits if e['action'] in ('remove','replace')}
                new_trip=validate_trip({**new_trip,**changes,
                    **({'must_visit':ids,'only_selected':new_trip['only_selected'] and bool(ids),
                        'excluded_places':sorted((set(new_trip['excluded_places'])|removed)-set(ids))} if edits else {})})
                if edits and not set(changes)&{'days','start_date','end_date','region','rain','pace','public_only'}:
                    plan=await asyncio.to_thread(revise_plan,previous,new_trip,edits)
                elif changes:
                    plan=await asyncio.to_thread(create_plan,**new_trip)
                elif (re.search(r'加入|添加|\badd\b',question,re.I) and not local_mentions(question)) or any(
                        stop['place'].get('provider')=='amap' and any(name and name.lower() in question.lower()
                            for name in [stop['place'].get('name'),stop['place'].get('requested_name')])
                        for day in previous['days'] for stop in day['stops']):
                    # Existing external-place lookup remains usable, but only after an explicit edit request.
                    legacy,cp=await journey_turn(question,None,{'checkpoint':{**checkpoint,'journey_plan':previous},
                        'turns':(saved or {}).get('turns',[])},settings,False,lookup=lookup)
                    plan=legacy['plan'];new_trip=cp['trip']
                    old_ids={stop['place']['id'] for day in previous['days'] for stop in day['stops']}
                    new_ids={stop['place']['id'] for day in plan['days'] for stop in day['stops']}
                    if old_ids==new_ids:
                        raise ValueError('Requested place was not resolved')
                    target=requested_day(question)
                    added=new_ids-old_ids
                    if target and added:
                        if target>len(previous['days']):
                            raise ValueError('Target day is outside the current calendar')
                        selected=[stop['place'] for day in plan['days'] for stop in day['stops']]
                        desired=copy.deepcopy(plan)
                        additions=[stop for day in desired['days'] for stop in day['stops'] if stop['place']['id'] in added]
                        for day in desired['days']:
                            day['stops']=[stop for stop in day['stops'] if stop['place']['id'] not in added]
                        desired['days'][target-1]['stops'].extend(additions)
                        plan=build_plan(selected,new_trip,previous=desired)
                        if not added<={stop['place']['id'] for stop in plan['days'][target-1]['stops']}:
                            raise ValueError('Requested day has insufficient capacity')
                    if len(plan['days'])!=len(previous['days']):
                        raise ValueError('The requested edit requires a calendar change')
                else:
                    return {'answer':answer('Which stop should I change, and what should replace it?' if english else
                                             '请说明要修改哪个地点、改成什么或放到哪一天。','clarify')}
            if action!='create_plan' and not set(changes)&{'days','start_date','end_date','region','rain','pace','public_only'}:
                for i,(old_day,new_day) in enumerate(zip(previous['days'],plan['days'])):
                    if [x['place']['id'] for x in old_day['stops']]==[x['place']['id'] for x in new_day['stops']]:
                        plan['days'][i]=copy.deepcopy(old_day)
            plan=with_price_summary(plan)
            response=answer('Your itinerary and map have been updated.' if english else
                            '已更新上方行程与地图。','ack')
            extra={}
            if s['decision'].also_answer:
                extra=await tourism(s)
                response={**extra['answer'],'text':extra['answer']['text']+'\n\n'+response['text']}
            return {**extra,'plan':plan,'trip':new_trip,'changed':True,'answer':response,
                'trace':extra.get('trace',s['trace'])+[{'tool':'commit_itinerary','status':'success',
                                                     'plan_version':version+1}]}
        except ValueError:
            return {'answer':answer('The requested change could not be applied. Please clarify the stop, date or constraints; your previous itinerary is retained.' if english else
                '这项修改无法应用，请明确地点、日期或调整冲突条件；原行程已保留。','clarify')}

    graph=StateGraph(TurnState)
    for name,node in [('route',route),('clarify',clarify),('modify',modify),('tourism',tourism),('general',general)]:
        graph.add_node(name,node)
    graph.add_edge(START,'route')
    graph.add_conditional_edges('route',lambda s:'clarify' if s['decision'].clarification else
        {'modify_itinerary':'modify','travel_question':'tourism','general_chat':'general'}[s['decision'].route])
    for name in ['clarify','modify','tourism','general']:
        graph.add_edge(name,END)
    with tracing_context(enabled=False):
        result=await graph.compile().ainvoke({'answer':{},'plan':previous,'trip':trip,'changed':False,
            'trace':[],'evidence':[],'discussed':checkpoint.get('discussed_place_ids',[])})
    new_version=version+int(result['changed'])
    history=bounded_history([*history,{'role':'user','content':question},
                             {'role':'assistant','content':result['answer']['text']}])
    checkpoint={**checkpoint,'trip':result['trip'],'journey_plan':result['plan'],'plan_version':new_version,
                'history':history,'discussed_place_ids':result['discussed'],'workflow':'conditional',
                'pending_request':{'question':question,'route':result['decision'].route,
                                   'clarification':result['answer']['text']}
                    if result['answer']['kind']=='clarify' else None}
    response={'workflow':'conditional','route':result['decision'].route,'answer':result['answer'],
        'plan':result['plan'] if result['changed'] else None,'plan_changed':result['changed'],'plan_version':new_version,
        'trip':result['trip'],'sources':[],'evidence':result['evidence'],'trace':result['trace']+model.trace,
        'stop_reason':'clarify' if result['answer']['kind']=='clarify' else 'complete',
        'metrics':{'elapsed_ms':round((time.monotonic()-started)*1000),'model_calls':model.calls,
                   'retrieval_rounds':sum(t['tool'].startswith('retrieve_') for t in result['trace'])}}
    return response,checkpoint
