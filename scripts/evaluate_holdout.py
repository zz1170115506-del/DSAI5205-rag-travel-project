"""Frozen author-written challenge set; no tuning, no claim of independent accuracy."""
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from travel.config import ROOT
from travel.knowledge import search,places,normalize
from travel.answers import demo_answer

def names_only(case):
    q=normalize(case['question'])
    pool=[p for p in places() if case.get('region','全部') in ('全部',p['region']) and (not case.get('indoor_only') or p['indoor']) and case.get('kind','all') in ('all',p['kind'])]
    return [p for p in pool if any(len(x)>1 and normalize(x) in q for x in [p['name'],p['en'],*p['aliases']])][:3]

def main():
    path=ROOT/'data/holdout_cases.json';raw=path.read_bytes();data=json.loads(raw)
    rows=[];summary={}
    for name,fn in [('name_alias_substring',names_only),('current_bm25',lambda c:search(c['question'],3,c.get('region','全部'),c.get('indoor_only',False),c.get('kind','all')))]:
        outcomes=[]
        for c in data['cases']:
            hits=fn(c);ids=[p['id'] for p in hits];r=set(c['relevant']);matching=[i+1 for i,p in enumerate(ids) if p in r]
            row={'retriever':name,**c,'retrieved':ids,'hit_at_3':int(bool(matching)) if r else None,'recall_at_3':len(r&set(ids))/len(r) if r else None,'reciprocal_rank_at_3':1/min(matching) if matching else 0,'empty_correct':not ids if not r else None}
            if c.get('dynamic'):
                row['dynamic_notice_present']='无法确认' in demo_answer(c['question'],hits)['text']
            rows.append(row);outcomes.append(row)
        positive=[r for r in outcomes if r['relevant']];negative=[r for r in outcomes if not r['relevant']]
        summary[name]={'positive_n':len(positive),'negative_n':len(negative),'hit_at_3':sum(r['hit_at_3'] for r in positive)/len(positive),'recall_at_3':sum(r['recall_at_3'] for r in positive)/len(positive),'mrr_at_3':sum(r['reciprocal_rank_at_3'] for r in positive)/len(positive),'negative_empty_rate':sum(r['empty_correct'] for r in negative)/len(negative)}
    result={'protocol':data['protocol'],'set_sha256':hashlib.sha256(raw).hexdigest(),'knowledge_sha256':hashlib.sha256((ROOT/'data/places.json').read_bytes()).hexdigest(),'summary':summary,'rows':rows}
    out=ROOT/'docs/evidence/holdout-results.json'
    if out.exists():raise SystemExit('Preserve first-run evidence: output exists. Use a new versioned protocol for future work.')
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
