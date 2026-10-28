"""一次运行本地回归，输出可审查证据；从不调用真实模型／高德。"""
import argparse,json,os,shutil,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--node',default=shutil.which('node'));parser.add_argument('--out',type=Path,default=ROOT/'docs/evidence/latest')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ);env.pop('MODEL_API_KEY',None);env.pop('AMAP_API_KEY',None)
    env['RETRIEVAL_MODE']='bm25'
    tasks=[('python-tests',[sys.executable,'-m','pytest','-q','--junitxml='+str(args.out/'pytest.xml')]),('data-validation',[sys.executable,'scripts/manage_data.py','data/places.json']),('development-retrieval',[sys.executable,'scripts/evaluate.py']),('local-doctor',[sys.executable,'scripts/doctor.py','--mcp']),('agent-acceptance',[sys.executable,'scripts/evaluate_agent.py'])]
    if args.node:tasks.append(('frontend-tests',[args.node,'--test',*[str(path.relative_to(ROOT)) for path in sorted((ROOT/'tests').glob('*.test.mjs'))]]))
    results=[]
    for name,command in tasks:
        run=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,timeout=90)
        (args.out/(name+'.txt')).write_text(run.stdout+run.stderr,encoding='utf-8')
        results.append({'check':name,'exit_code':run.returncode});print(name+': '+('PASS' if run.returncode==0 else 'FAIL'),flush=True)
    if not args.node:results.append({'check':'frontend-tests','exit_code':None,'status':'not run; Node.js not found'})
    report={'time_utc':datetime.now(timezone.utc).isoformat(),'external_api_verification':False,'checks':results,'all_passed':all(r['exit_code']==0 for r in results)}
    (args.out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['all_passed'] else 1
if __name__=='__main__':raise SystemExit(main())
