"""Opt-in real-provider smoke of the current browser API, with isolated synthetic history."""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sys
import time
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

import app as application
from travel.api import chat
from travel.core.config import ROOT, Settings
from travel.core.model import WorkflowModel
from travel.core.prompts import ASSISTANT_IDENTITY
from travel.core.web_access import WebAccess
from travel.rag.knowledge import get_place
from travel.rag.place_intent import matches_category
from travel.session.history import HistoryStore
from travel.workflows import conditional


def place_ids(plan):
    return [stop['place']['id'] for day in plan['days'] for stop in day['stops']]


def plan_checks(plan, expected_days):
    if not plan:
        return {'plan_present': False}
    days=plan['days']
    ids=place_ids(plan)
    return {
        'calendar_length': len(days)==expected_days==plan['days_requested'],
        'consecutive_days': [day['day'] for day in days]==list(range(1,expected_days+1)),
        'consecutive_dates': all(day['date']==(datetime.fromisoformat(plan['start_date'])+
            timedelta(days=i)).date().isoformat() for i,day in enumerate(days)),
        'no_duplicate_stops': len(ids)==len(set(ids)),
        'transfers_match_stops': all(len(day['legs'])==max(0,len(day['stops'])-1) for day in days),
        'valid_visit_times': all(stop['start']<stop['end'] for day in days for stop in day['stops']),
        'map_coordinates_available': all(22.1<stop['place'].get('lat',0)<22.65 and
            113.8<stop['place'].get('lon',0)<114.5 for day in days for stop in day['stops']),
        'price_summary_present': isinstance(plan.get('price_summary'),dict),
    }


def recommended_places(result, category):
    cited=set(result['answer'].get('citations',[]))
    found={}
    for row in result.get('evidence',[]):
        if row['id'] not in cited:
            continue
        if row.get('place_id'):
            try:
                place=get_place(row['place_id'])
            except KeyError:
                continue
            found[place['id']]=matches_category(place,category) if category else place.get('kind')=='attraction'
        elif row.get('evidence_type')=='map_location':
            place=json.loads(row['text'])
            found[place['name']]=matches_category(place,category,external=True) if category else True
    return found


async def run(args):
    if not args.live:
        raise SystemExit('真实测试需显式 --live；普通回归不会调用外部服务。')
    cfg=Settings.from_env()
    if not cfg.model_api_key:
        raise SystemExit('未配置模型密钥，未发出请求。')
    started=datetime.now(ZoneInfo('Asia/Hong_Kong'))
    run_id=started.strftime('%Y%m%d-%H%M%S')
    archive=HistoryStore(ROOT/'work'/'qa-conditional'/run_id/'history.sqlite3')
    application.settings=cfg
    application.web_access=WebAccess()
    chat.store=archive
    chat.locks={}
    model_records=[]

    class RecordingModel(WorkflowModel):
        async def ask(self,role,instructions,payload,schema):
            began=time.monotonic()
            before=self.calls
            result=await super().ask(role,instructions,payload,schema)
            model_records.append({'role':role,'requested':self.calls>before,'accepted':result is not None,
                'elapsed_ms':round((time.monotonic()-began)*1000),
                'response':result.model_dump() if result else None})
            return result

    conditional.WorkflowModel=RecordingModel
    report={'time_hk':started.isoformat(),'kind':'synthetic_live_smoke_not_quality_benchmark',
        'model':cfg.model_name,'system_prompt':ASSISTANT_IDENTITY,
        'history':'isolated synthetic data','rows':[]}

    def save():
        rows=report['rows']
        report['summary']={'cases':len(rows),'passed':sum(row['passed'] for row in rows),
            'failed':[row['name'] for row in rows if not row['passed']],
            'actual_model_requests':sum(r['requested'] for row in rows for r in row['model']),
            'accepted_model_responses':sum(r['accepted'] for row in rows for r in row['model'])}
        args.out.parent.mkdir(parents=True,exist_ok=True)
        encoded=json.dumps(report,ensure_ascii=False,indent=2)
        for key in (cfg.model_api_key,cfg.amap_api_key):
            if key:
                encoded=encoded.replace(key,'[redacted]')
        args.out.write_text(encoded)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application.app),base_url='http://testserver',timeout=75) as client:
        async def turn(name,question,*,cid=None,trip=None,expected_days=None,expected_route=None,verify=None,language='zh'):
            before=deepcopy(archive.get(cid)['checkpoint']) if cid else None
            offset=len(model_records)
            body={'question':question,'workflow':'conditional','language':language,
                  'action':'create_plan' if trip else 'message'}
            if cid:
                body.update(conversation_id=cid,expected_plan_version=before['plan_version'])
            if trip:
                body['trip']=trip
            response=await client.post('/api/chat',json=body)
            result=response.json()
            checks={'http_ok':response.status_code==200}
            cp=archive.get(result['conversation_id'])['checkpoint'] if response.status_code==200 else None
            if cp:
                checks['no_handoff_disclosure']=not bool(re.search(r'原助手|转交给|兜底|original assistant|handed off',result['answer']['text'],re.I))
                checks['automatic_model_mode']=archive.get(result['conversation_id'])['use_model'] is True
                if not trip:
                    checks['real_router_response']=any(r['role']=='route_message' and r['accepted'] for r in model_records[offset:])
                if expected_route:
                    checks['correct_route']=result['route']==expected_route
                if expected_days:
                    checks.update(plan_checks(cp['journey_plan'],expected_days))
                    checks['trip_length']=cp['trip']['days']==expected_days
                if expected_route in {'travel_question','general_chat'}:
                    checks['read_only']=not result['plan_changed'] and result['plan'] is None and cp['journey_plan']==before['journey_plan']
                if verify:
                    checks.update(verify(result,cp,before))
            row={'name':name,'question':question,'checks':checks,'passed':all(checks.values()),
                 'result':result,'day_place_ids':[[s['place']['id'] for s in day['stops']] for day in cp['journey_plan']['days']] if cp else [],
                 'model':model_records[offset:]}
            report['rows'].append(row)
            save()
            print(json.dumps({'case':name,'passed':row['passed'],'failed_checks':[k for k,v in checks.items() if not v],
                'model_requests':sum(r['requested'] for r in row['model']),
                'accepted_responses':sum(r['accepted'] for r in row['model']),
                'days':len(cp['journey_plan']['days']) if cp else None,'answer':result.get('answer',{}).get('text','')[:140]},ensure_ascii=False),flush=True)
            return result.get('conversation_id') or cid

        start='2026-11-10'
        def preferences(days,selected=False):
            return {'days':days,'start_date':start,'end_date':(datetime.fromisoformat(start)+timedelta(days=days-1)).date().isoformat(),
                    **({'must_visit':['pmq','hkmoa'],'only_selected':True} if selected else {})}

        if args.group in {'all','days'}:
            for days in range(1,6):
                await turn(f'create_{days}_days',f'规划香港{days}天行程',trip=preferences(days),expected_days=days)
            cid=await turn('duration_seed','规划香港两天行程',trip=preferences(2),expected_days=2)
            for days in range(1,6):
                cid=await turn(f'set_{days}_days',f'把我的行程改成{days}天，出发日期不变。',cid=cid,
                    expected_days=days,expected_route='modify_itinerary')
            cid=await turn('decrease_two_days','少玩两天，出发日期不变。',cid=cid,expected_days=3,expected_route='modify_itinerary')
            await turn('increase_two_days','再多玩两天，出发日期不变。',cid=cid,expected_days=5,expected_route='modify_itinerary')

        if args.group in {'all','places','recommendations'}:
            cid=await turn('place_seed','规划两天，只去元创方和香港艺术馆。',trip=preferences(2,True),expected_days=2)
        if args.group in {'all','places'}:
            def edit_check(added=(),removed=(),preserve_second=False):
                def verify(result,cp,before):
                    ids=set(place_ids(cp['journey_plan']))
                    return {'committed_once':result['plan_changed'] and cp['plan_version']==before['plan_version']+1,
                        'requested_stops_added':set(added)<=ids,'requested_stops_removed':not set(removed)&ids,
                        **({'other_day_unchanged':cp['journey_plan']['days'][1]==before['journey_plan']['days'][1]} if preserve_second else {})}
                return verify
            cid=await turn('add_place','把大馆加到第一天，第二天不要动。',cid=cid,expected_days=2,
                expected_route='modify_itinerary',verify=edit_check(added=['tai-kwun'],preserve_second=True))
            cid=await turn('remove_place','把第一天的大馆删掉，第二天不要动。',cid=cid,expected_days=2,
                expected_route='modify_itinerary',verify=edit_check(removed=['tai-kwun'],preserve_second=True))
            cid=await turn('replace_place','把元创方换成大馆，第二天不要动。',cid=cid,expected_days=2,
                expected_route='modify_itinerary',verify=edit_check(added=['tai-kwun'],removed=['pmq'],preserve_second=True))
            cid=await turn('move_place','把大馆移到第二天，其他地点保留。',cid=cid,expected_days=2,
                expected_route='modify_itinerary',verify=lambda result,cp,before:{
                    'moved_to_day_two':'tai-kwun' in [s['place']['id'] for s in cp['journey_plan']['days'][1]['stops']],
                    'kept_other_place':'hkmoa' in place_ids(cp['journey_plan'])})
        if args.group in {'all','recommendations'}:
            for name,question,category in [
                ('recommend_malls','推荐香港的三个商场，告诉我名称和所在地区，先不要改行程。','mall'),
                ('recommend_museums','推荐三个香港博物馆，简单说说各自的主题，先不要改行程。','museum'),
                ('recommend_attractions','推荐三个适合父母轻松游玩的香港景点，先不要添加到行程。',None),
            ]:
                def recommendation_check(result,cp,before,category=category):
                    recommendations=recommended_places(result,category)
                    return {'verified_model_answer':result['answer'].get('model_output_accepted') is True,
                        'three_distinct_supported_places':len(recommendations)>=3,
                        'requested_category':bool(recommendations) and all(recommendations.values())}
                cid=await turn(name,question,cid=cid,expected_days=2,expected_route='travel_question',verify=recommendation_check)
            await turn('assistant_identity','你是谁？',cid=cid,expected_days=2,expected_route='general_chat',
                verify=lambda result,cp,before:{'hong_kong_identity':'香港' in result['answer']['text']})
    save()
    print(json.dumps(report['summary'],ensure_ascii=False),flush=True)
    return 0 if not report['summary']['failed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--group',choices=['all','days','places','recommendations'],default='all')
    parser.add_argument('--out',type=Path,default=ROOT/'docs/evidence/conditional-2026-11-06/live-smoke.json')
    raise SystemExit(asyncio.run(run(parser.parse_args())))
