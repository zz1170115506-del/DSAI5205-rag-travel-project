import re
import logging

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError
from app.core.errors import ModelResponseError, validation_summary

from app.rag.retrieval.search import SearchRequest
from app.rag.text import normalize


log = logging.getLogger(__name__)


def fallback_queries(question):
    return [question[i:i+1800] for i in range(0, len(question), 1800)][:3] or ['旅行问题']


class Plan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    _diagnostics: list = PrivateAttr(default_factory=list)
    intent: str = Field('fact', pattern='^(fact|compare|planning|clarify)$')
    queries: list[str] = Field(default_factory=list, max_length=3)
    filters: dict = Field(default_factory=dict)
    clarification: str | None = Field(None, max_length=500)


async def make_plan(question, history, previous, search, provider):
    q = normalize(question)
    constraints = {k: v for k, v in previous.items() if k in SearchRequest.model_fields and k not in {'query', 'channels', 'top_k'}}
    matches = search.matches(question)
    attractions = [x['id'] for x in matches if x['type'] == 'attraction']
    if '清除条件' in q or '重新开始' in q:
        constraints = {}
    for item in matches:
        if item['type'] == 'district':
            constraints['district'] = item['id']
        elif item['type'] == 'theme':
            constraints['theme'] = item['id']
    if any(t in q for t in ['室内', 'indoor']):
        constraints['setting'] = 'outdoor' if '不要室内' in q else 'indoor'
    if any(t in q for t in ['室外', '户外', 'outdoor']):
        constraints['setting'] = 'indoor' if any(t in q for t in ['不要户外', '不去户外', '不喜欢户外']) else 'outdoor'
    if '不限室内外' in q:
        constraints.pop('setting', None)
    price = re.search(r'(?:预算|budget|不超过)\D{0,6}(\d+(?:\.\d+)?)', q)
    if price:
        constraints['max_price'] = float(price.group(1))
    duration = re.search(r'(\d+)\s*(小时|分钟|hours?|minutes?)', q)
    if duration:
        constraints['max_minutes'] = int(duration.group(1)) * (60 if duration.group(2) in {'小时', 'hour', 'hours'} else 1)
    if '不限预算' in q:
        constraints.pop('max_price', None)
    intent = 'planning' if any(t in q for t in ['行程', '安排', '规划', 'itinerary', 'plan a']) else 'compare' if any(t in q for t in ['比较', '区别', 'compare', ' vs ']) else 'fact'
    plan = Plan(intent=intent, queries=fallback_queries(question))
    if provider.settings.model_mode == 'remote':
        try:
            data = await provider.json_answer(
                'Extract a tourism retrieval plan. Return a JSON object only. '
                'intent MUST be exactly fact, compare, planning or clarify. '
                'queries MUST be an array of 1..3 strings, each at most 1800 characters. '
                'filters MUST be an object, use {} if no filters; allowed keys only '
                'district/theme/setting/max_price/max_minutes. setting MUST be indoor/outdoor/mixed; '
                'max_price MUST be a non-negative number; max_minutes MUST be a positive integer. '
                'clarification MUST be null or one short question. No extra keys. '
                'Current explicit requirements override history. No arbitrary SQL or tool calls.',
                {'question': question, 'history': history[-6:], 'current_constraints': constraints})
            candidate = Plan.model_validate(data)
            allowed = {'district', 'theme', 'setting', 'max_price', 'max_minutes'}
            if set(candidate.filters) - allowed:
                raise ModelResponseError('Unsupported planner filter')
            # Null means no new condition; do not erase validated explicit constraints.
            candidate.filters = {k: v for k, v in candidate.filters.items() if v is not None}
            candidate.queries = candidate.queries or fallback_queries(question)
            for query in candidate.queries:
                SearchRequest(query=query, **{**constraints, **candidate.filters})
            if candidate.intent == 'clarify' and not candidate.clarification:
                candidate.clarification = '你希望了解哪个景点，或有哪些旅行条件？'
            plan = candidate
            constraints.update(candidate.filters)
        except (ValidationError, ModelResponseError) as exc:
            # Retrieval still receives the original question and deterministic constraints.
            # Do not execute invalid model fields or retry with the user's conversation.
            detail = validation_summary(exc)
            plan._diagnostics = [{'code': 'PLANNER_SCHEMA_FALLBACK', 'validation': detail}]
            log.warning('planner schema fallback: %s', detail)
    prior_ids = previous.get('_entities', [])
    if not attractions and any(t in q for t in ['它', '那里', 'that place', '同区', '同主题', '同一地区']):
        attractions = prior_ids
    if any(t in q for t in ['同区', '同一地区', '同地区', 'same district', '同主题', 'same theme']):
        if not attractions:
            plan.intent, plan.clarification = 'clarify', '你希望以哪个景点作为关联查询的起点？'
        else:
            constraints['source_entity_id'] = attractions[0]
            constraints['relation'] = 'HAS_THEME' if any(t in q for t in ['同主题', 'same theme']) else 'LOCATED_IN'
    else:
        constraints.pop('source_entity_id', None)
    queries = plan.queries or fallback_queries(question)
    if attractions and not matches and 'source_entity_id' not in constraints:
        # Carry resolved referent into lexical/semantic search.
        with search.factory() as db:
            from app.models import Entity
            names = [db.get(Entity, x).name_zh for x in attractions if db.get(Entity, x)]
        queries = fallback_queries(question + ' ' + ' '.join(names))
    for query in queries:
        SearchRequest(query=query, **constraints)
    plan.queries, plan.filters = queries, constraints
    state = {**constraints, '_entities': attractions or prior_ids}
    return plan, state
