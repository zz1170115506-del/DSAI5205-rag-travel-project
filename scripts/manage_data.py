"""先验证完整候选资料，再生成审核副本。永不覆盖活动资料和已存在文件。"""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from travel.data_validation import load_validated
from travel.config import ROOT

def main():
    parser=argparse.ArgumentParser();parser.add_argument('candidate',type=Path);parser.add_argument('--stage',type=Path)
    args=parser.parse_args();data=load_validated(args.candidate)
    info={'valid':True,'records':len(data['places']),'version':data['version'],'sha256':hashlib.sha256(args.candidate.read_bytes()).hexdigest(),'validation':'structure and provenance fields only; human source review still required'}
    if args.stage:
        if args.stage.resolve()==(ROOT/'data/places.json').resolve():parser.error('不能覆盖活动资料，请先输出审核副本')
        args.stage.parent.mkdir(parents=True,exist_ok=True)
        with args.stage.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
        info['staged']=str(args.stage)
    print(json.dumps(info,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
