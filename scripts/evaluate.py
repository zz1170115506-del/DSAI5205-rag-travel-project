"""运行小型手写检索开发集。此结果不是独立测试集准确率。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from travel.config import ROOT
from travel.knowledge import search

cases=json.loads((ROOT/'data/eval_cases.json').read_text(encoding='utf-8'))
success=0
for case in cases:
    found=[p['id'] for p in search(case['question'],limit=3,kind=case.get('kind','all'),indoor_only=case.get('indoor_only',False))]
    ok=bool(set(found)&set(case['expected'])) if case['expected'] else not found
    success+=int(ok)
    print(('PASS' if ok else 'FAIL'),case['question'],'→',','.join(found) or '无结果')
print(f'\n手写开发例题通过：{success}/{len(cases)}；不得作为独立泛化准确率。')
raise SystemExit(0 if success==len(cases) else 1)
