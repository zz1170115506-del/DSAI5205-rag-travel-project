import json
import re
import time
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.rag.provider import ModelProvider
from app.rag.retrieval.search import SearchRequest
from app.rag.text import digest


class Case(BaseModel):
    model_config = ConfigDict(extra='allow')
    case_id: str
    group_id: str
    category: str
    split: str = Field(pattern='^(dev|test)$')
    dataset_version: str
    question: str
    history: list = Field(default_factory=list)
    profile: dict = Field(default_factory=dict)
    relevant_entity_ids: list[str] = Field(default_factory=list)
    relevant_chunk_ids: list[str] = Field(default_factory=list)
    expected_facts: list[str] = Field(default_factory=list)
    constraints: dict = Field(default_factory=dict)
    answerable: bool
    expected_behavior: str
    rubric: dict = Field(default_factory=dict)
    synthetic: bool = False
    verified_by: str
    verified_at: str


def retrieval_metrics(ids, relevant):
    if not relevant:
        return {'recall_at_5': None, 'mrr': None}
    return {'recall_at_5': len(set(ids[:5]) & set(relevant)) / len(set(relevant)),
            'mrr': next((1 / (i+1) for i, x in enumerate(ids) if x in relevant), 0)}


async def evaluate(search, dataset, output, split='dev', channels=None):
    from app.agent.planner import make_plan
    cases = [Case.model_validate(json.loads(line)) for line in Path(dataset).read_text().splitlines() if line.strip()]
    if len({c.case_id for c in cases}) != len(cases):
        raise ValueError('Duplicate case IDs')
    groups = {}
    for c in cases:
        if c.group_id in groups and groups[c.group_id] != c.split:
            raise ValueError('Group leaks across dev/test')
        groups[c.group_id] = c.split
    experiment = uuid4().hex
    out = Path(output) / experiment
    out.mkdir(parents=True, exist_ok=False)
    config = {'experiment_id': experiment, 'model_mode': search.settings.model_mode,
        'llm_model': search.settings.llm_model, 'prompt_version': 'travel-v1',
        'index': search.manifest, 'dataset_hash': digest(Path(dataset).read_text()),
        'split': split, 'channels': channels or ['vector','bm25','entity','graph'],
        'warning': 'synthetic/mock runs are pipeline checks, not real semantic QA quality scores'}
    (out/'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2))
    results = []
    for case in [c for c in cases if c.split == split]:
        row = {'experiment_id': experiment, 'case_id': case.case_id, 'category': case.category,
               'synthetic': case.synthetic, 'error': None}
        start = time.perf_counter()
        try:
            if case.dataset_version != search.manifest['dataset_version']:
                raise ValueError('Case dataset version mismatch')
            provider = ModelProvider(search.settings)
            previous = {}
            for message in case.history:
                if message['role'] == 'user':
                    _, previous = await make_plan(message['content'], [], previous, search, provider)
            plan, _ = await make_plan(case.question, case.history, previous, search, provider)
            found = []
            for query in plan.queries:
                r = await search.search(SearchRequest(query=query, channels=config['channels'],
                    **{**plan.filters, **case.constraints}), provider, case.profile)
                found.extend(x for x in r['results'] if x['chunk_id'] not in {f['chunk_id'] for f in found})
            found = found[:8]
            retrieval_end = time.perf_counter()
            answer = plan.clarification or ''
            ttft = None
            if not answer:
                async for token in provider.generate({'question': case.question, 'history': case.history,
                    'profile': case.profile, 'intent': plan.intent, 'constraints': plan.filters, 'evidence': found}):
                    if ttft is None:
                        ttft = (time.perf_counter()-start)*1000
                    answer += token
            ids = [r['chunk_id'] for r in found]
            cited = [int(x) for x in re.findall(r'\[(\d+)\]', answer)]
            row.update(answer=answer, retrieved_chunk_ids=ids, citations=found,
                relation_paths=[p for f in found for p in f['relation_paths']],
                scores={**retrieval_metrics(ids, case.relevant_chunk_ids),
                    'entity_recall': len({f['attraction_id'] for f in found} & set(case.relevant_entity_ids))/len(set(case.relevant_entity_ids)) if case.relevant_entity_ids else None,
                    'expected_fact_string_coverage': sum(f in answer for f in case.expected_facts)/len(case.expected_facts) if case.expected_facts else None,
                    'citation_indices_valid': all(1 <= i <= len(found) for i in cited),
                    'citation_count': len(cited)},
                latency_ms={'retrieval': (retrieval_end-start)*1000, 'ttft': ttft,
                            'total': (time.perf_counter()-start)*1000},
                usage={'model_calls': provider.calls, 'provider_usage': provider.usage},
                run_status='completed', requires_human_review=True)
        except Exception as exc:
            row.update(error=type(exc).__name__, run_status='failed')
        results.append(row)
    (out/'results.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in results))
    summary = {'experiment_id': experiment, 'cases': len(results),
        'errors': sum(r['error'] is not None for r in results), 'model_mode': search.settings.model_mode,
        'synthetic_cases': sum(r['synthetic'] for r in results)}
    for key in ['recall_at_5', 'mrr', 'entity_recall', 'expected_fact_string_coverage']:
        values = [r.get('scores', {}).get(key) for r in results]
        values = [v for v in values if v is not None]
        summary[key] = sum(values)/len(values) if values else None
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary
