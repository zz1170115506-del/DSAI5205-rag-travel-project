"""只读本机自检，不访问外部服务，也不输出 Key。"""
import argparse,asyncio,json,platform,sys
from importlib.metadata import version
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from travel.config import ROOT,Settings
from travel.data_validation import load_validated
from travel.embeddings import retrieval_status
from travel.mcp_client import local_call

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mcp',action='store_true',help='额外运行一次真实本地 stdio 调用')
    args=parser.parse_args()
    try:
        data=load_validated(ROOT/'data/places.json');settings=Settings.from_env()
        result={'ok':True,'python':platform.python_version(),'platform':platform.system()+' '+platform.machine(),'packages':{p:version(p) for p in ['fastapi','mcp','httpx','pydantic','uvicorn','langgraph']},'knowledge_version':data['version'],'records':len(data['places']),'model_key_present':bool(settings.model_api_key),'amap_key_present':bool(settings.amap_api_key),'external_requests_made':False}
        result['retrieval']=retrieval_status()
        if args.mcp:
            found,trace=asyncio.run(local_call('search_places',{'query':'深水埗有什么小吃','kind':'food','limit':3}))
            result['mcp']={'trace':trace,'result_ids':[p['id'] for p in found['results']]}
    except Exception:
        result={'ok':False,'message':'本机自检失败。请确认使用项目虚拟环境、依赖完整、data/places.json 校验通过；原始异常未输出，以避免配置泄露。'}
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['ok'] else 1
if __name__=='__main__':raise SystemExit(main())
