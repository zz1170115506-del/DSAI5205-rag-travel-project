import json

import pytest

from app.core.config import ROOT
from app.evaluation.runner import evaluate, retrieval_metrics


def test_metrics():
    assert retrieval_metrics(['b','a'],['a'])=={'recall_at_5':1.,'mrr':.5}
    assert retrieval_metrics([],[])=={'recall_at_5':None,'mrr':None}


async def test_evaluation_retains_outputs_and_metadata(stack,tmp_path):
    report=await evaluate(stack[2],ROOT/'data/demo/evaluation.jsonl',tmp_path/'reports')
    assert report['cases']==8
    assert report['errors']==0
    assert report['model_mode']=='mock'
    assert report['synthetic_cases']==8
    output=tmp_path/'reports'/report['experiment_id']
    assert len((output/'results.jsonl').read_text().splitlines())==8
    assert 'embedding_dim' in json.loads((output/'config.json').read_text())['index']
