"""Bounded, canonical state supplied to the model; never an executable prompt."""
from .knowledge import get_place
from .place_context import clean_ids
from datetime import datetime
from zoneinfo import ZoneInfo


def bounded_history(messages,max_chars=24000,max_messages=24):
    kept=[];size=0
    for message in reversed(messages[-max_messages:]):
        if message.get('role') not in ('user','assistant') or not isinstance(message.get('content'),str):continue
        content=message['content'][:4000]
        if size+len(content)>max_chars:break
        kept.append({'role':message['role'],'content':content});size+=len(content)
    return list(reversed(kept))


def clean_notes(value):
    return list(dict.fromkeys(x.strip()[:160] for x in value[:8] if isinstance(x,str) and x.strip())) if isinstance(value,list) else []


def plan_snapshot(plan):
    if not isinstance(plan,dict):return None
    days=plan.get('days',[])
    if not isinstance(days,list) or not 1<=len(days)<=366:return None
    result=[];seen=set()
    for index,day in enumerate(days):
        ids=day.get('place_ids') if 'place_ids' in day else [s.get('place',{}).get('id') for s in day.get('stops',[])]
        if not isinstance(ids,list) or clean_ids(ids)!=ids or any(pid in seen for pid in ids):return None
        seen.update(ids)
        result.append({'day':index+1,'place_ids':ids})
    return {'start_date':plan.get('start_date'),'end_date':plan.get('end_date'),'days_requested':len(result),'days':result}


def restore_memory(saved):
    checkpoint=saved.get('checkpoint',{})
    latest=plan_snapshot(checkpoint.get('plan_context'))
    if latest is None:
        latest=next((snapshot for turn in reversed(saved.get('turns',[])) if (snapshot:=plan_snapshot(turn.get('result',{}).get('plan')))),None)
    messages=[{'role':role,'content':text} for turn in saved.get('turns',[]) for role,text in [('user',turn.get('question','')),('assistant',turn.get('result',{}).get('answer',{}).get('text',''))]]
    return {'plan_context':latest,'memory_notes':clean_notes(checkpoint.get('memory_notes',[])),'history':bounded_history(messages or checkpoint.get('history',[]))}


def model_memory(state):
    snapshot=plan_snapshot(state.get('plan_context'))
    return {'today_hong_kong':datetime.now(ZoneInfo('Asia/Hong_Kong')).date().isoformat(),'travel_conditions':state['trip'],'remembered_preferences':clean_notes(state.get('memory_notes',[])),
            'visible_places':[{key:[{'id':pid,'name':get_place(pid)['name']} for pid in state.get('place_context',{}).get(key,[])]} for key in ('listed_ids','focus_ids')],
            'itinerary':({**snapshot,'days':[day for day in snapshot['days'] if day['place_ids']],'empty_days_note':'未列出的日期保持休息／自由活动。'} if snapshot else None)}
