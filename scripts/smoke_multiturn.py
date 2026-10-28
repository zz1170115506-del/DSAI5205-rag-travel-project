"""Explicit live smoke with synthetic tourist prompts only, never the user's archive."""
import argparse,asyncio,json,sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from travel.agent import AgentEngine,ModelPolicy
from travel.config import Settings,ROOT
from travel.history import HistoryStore
from travel.conversation_memory import restore_memory

async def main(args):
    if not args.live:raise SystemExit('真实联调需显式 --live；普通回归不调用模型。')
    cfg=Settings.from_env()
    if not cfg.model_api_key:raise SystemExit('未配置模型；未发送请求。')
    store=HistoryStore(ROOT/'work'/'qa-model-conversation'/'smoke.sqlite3')
    engine=AgentEngine(cfg);turns=[];cid=None;rows=[]
    class RecordingPolicy(ModelPolicy):
        async def __call__(self,state):
            decision=await super().__call__(state)
            if 'final' in decision:self.last_proposal=decision['final']
            return decision
    engine.policy=RecordingPolicy(cfg)
    start_index=0
    if args.resume:
        prior=json.loads(args.resume.read_text());rows=prior['rows'][:]
        if rows and (rows[-1]['stop']!='complete' or args.retry_last):rows.pop()
        start_index=len(rows);saved=store.get(store.list()[0]['id']);cid=saved['id'];turns=saved['turns'][:start_index]
        await engine.graph.aupdate_state({'configurable':{'thread_id':'synthetic'}},{**saved['checkpoint'],**restore_memory(saved)},as_node='finish')
    questions=['合成游客测试：我与父母同行，想在香港看海，推荐两个适合慢慢散步的地方，先不排行程。',
               '那就刚才这两处吧，2026-10-24到2026-10-25，只去它们，慢慢来。',
               '第一天想休息，不删景点，把两处都挪到第二天。',
               '第二天最后那个换成香港艺术馆，以后也别再加回被换掉的那处，另一处照旧。',
               '把前两天互换一下，其他不要动。',
               '你还记得我跟谁一起，以及现在不想去哪里吗？']
    for index,question in enumerate(questions[start_index:],start_index):
        if index==4:
            engine=AgentEngine(cfg)
            engine.policy=RecordingPolicy(cfg)
            saved=store.get(cid)
            await engine.graph.aupdate_state({'configurable':{'thread_id':'synthetic'}},{**saved['checkpoint'],**restore_memory(saved)},as_node='finish')
        result=await engine.turn('synthetic',question)
        state=(await engine.graph.aget_state({'configurable':{'thread_id':'synthetic'}})).values
        turns.append({'question':question,'result':result})
        cid=store.save(cid,turns,state,True,'合成游客多轮联调')
        day_ids=[[s['place']['id'] for s in day['stops']] for day in (result.get('plan') or {}).get('days',[])]
        row={'turn':index+1,'question':question,'answer':result['answer'],'trip':result['trip'],'notes':result.get('memory_notes',[]),'day_place_ids':day_ids,'trace':result['trace'],'metrics':result['metrics'],'stop':result['stop_reason']}
        rows.append(row)
        if not result['answer']['model_output_accepted']:
            folder=ROOT/'work'/'qa-model-conversation';folder.mkdir(parents=True,exist_ok=True)
            proposal=json.dumps(getattr(engine.policy,'last_proposal',{}),ensure_ascii=False).replace(cfg.model_api_key,'[redacted]')
            (folder/f'unaccepted-proposal-{index+1}.json').write_text(proposal)
            invalid=getattr(engine.policy,'last_invalid_output',None)
            if invalid:(folder/f'invalid-output-{index+1}.json').write_text(json.dumps(invalid,ensure_ascii=False).replace(cfg.model_api_key,'[redacted]'))
        print(json.dumps({'turn':index+1,'stop':row['stop'],'tools':[(t['tool'],t['status']) for t in row['trace']],'days':day_ids,'accepted':row['answer']['model_output_accepted'],'error_kind':row['metrics'].get('model_error_kind')},ensure_ascii=False),flush=True)
        if result['stop_reason']!='complete':break
    checks={'six_turns_completed':len(rows)==6 and all(r['stop']=='complete' for r in rows),
            'selected_exact_two':len(rows)>1 and sum(map(len,rows[1]['day_place_ids']))==2 and rows[1]['trip']['only_selected'],
            'move_preserves_rest_day':len(rows)>2 and len(rows[2]['day_place_ids'])==2 and not rows[2]['day_place_ids'][0] and len(rows[2]['day_place_ids'][1])==2,
            'replace_and_exclude':len(rows)>3 and 'hkmoa' in sum(rows[3]['day_place_ids'],[]) and bool(rows[3]['trip']['excluded_places']),
            'swap_after_database_restore':len(rows)>4 and len(rows[4]['day_place_ids'][0])==2 and not rows[4]['day_place_ids'][1],
            'all_real_model_responses':all(r['metrics']['external_model_verified'] for r in rows),
            'all_model_answers_accepted':len(rows)==6 and all(r['answer']['model_output_accepted'] for r in rows),
            'recalls_companions':len(rows)==6 and any(w in rows[-1]['answer']['text'] for w in ('父母','爸妈'))}
    report={'time_utc':datetime.now(timezone.utc).isoformat(),'kind':'synthetic_live_smoke_not_quality_benchmark','model':cfg.model_name,'checks':checks,'all_passed':all(checks.values()),'rows':rows}
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'all_passed':report['all_passed'],'checks':checks},ensure_ascii=False))
    return 0 if report['all_passed'] else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--resume',type=Path);parser.add_argument('--retry-last',action='store_true');parser.add_argument('--out',type=Path,default=ROOT/'docs/evidence/model-conversation/live-smoke.json')
    raise SystemExit(asyncio.run(main(parser.parse_args())))
