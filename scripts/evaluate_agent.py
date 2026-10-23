"""Local workflow acceptance: real stdio, scripted model HTTP, no external model request."""
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from travel.agent import AgentEngine, ModelPolicy
from travel.config import Settings


async def main():
    out = ROOT / 'docs/evidence/agent-v1'
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    engine = AgentEngine()
    a = await engine.turn('acceptance-memory', '带父母九龙一天，少走路，安排行程')
    b = await engine.turn('acceptance-memory', '改成只选室内')
    passed = bool(a['plan'] and b['plan'] and b['trip']['region'] == '九龙' and b['trip']['days'] == 1 and b['trip']['rain'])
    cases.append({'case': 'multi_turn_constraints_real_stdio', 'passed': passed, 'turns': [a, b]})
    a = await engine.turn('acceptance-conflict', '九龙一天安排行程，必去星光大道，只选室内')
    b = await engine.turn('acceptance-conflict', '取消室内限制')
    cases.append({'case': 'conflict_then_user_revision_real_stdio', 'passed': a['stop_reason'] == 'tool_error' and bool(b['plan']), 'turns': [a, b]})
    a = await engine.turn('acceptance-clarify', '带父母九龙，安排行程')
    b = await engine.turn('acceptance-clarify', '改成两天')
    cases.append({'case': 'clarification_then_continue_real_stdio', 'passed': a['stop_reason'] == 'clarify' and bool(b['plan']), 'turns': [a, b]})
    responses = 0
    def model_fixture(request):
        nonlocal responses
        payload = json.loads(request.content)
        responses += 1
        if responses == 1:
            message = {'tool_calls': [{'id': 'fixture1', 'type': 'function', 'function': {'name': 'search_places', 'arguments': '{"query":"大馆"}'}}]}
        elif responses == 2:
            observed = json.loads(payload['messages'][-1]['content'])
            pid = observed['results'][0]['id']
            message = {'tool_calls': [{'id': 'fixture2', 'type': 'function', 'function': {'name': 'place_detail', 'arguments': json.dumps({'place_id': pid})}}]}
        else:
            message = {'content': json.dumps({'text': '大馆提供文化艺术空间 [tai-kwun]', 'citations': ['tai-kwun']})}
        return httpx.Response(200, json={'choices': [{'message': message}]})
    settings = Settings(model_api_key='local-fixture-not-real')
    mocked = AgentEngine(settings)
    mocked.policy = ModelPolicy(settings, httpx.MockTransport(model_fixture))
    a = await mocked.turn('acceptance-function-calling', '中环文化景点')
    cases.append({'case': 'http_fixture_search_detail_finish_with_real_stdio', 'passed': [t['tool'] for t in a['trace']] == ['search_places', 'place_detail'] and a['metrics']['model_calls'] == 3, 'turns': [a]})
    # Session tokens never leave memory in ordinary operation; omit from evidence as well.
    for case in cases:
        for turn in case['turns']:
            turn.pop('session_id', None)
    report = {'time_utc': datetime.now(timezone.utc).isoformat(), 'scope': 'author-written development acceptance, not blind evaluation',
              'external_model_verified': False, 'amap_verified': False,
              'baseline': {'endpoint': '/api/ask + /api/plan', 'conversation_state': False, 'model_chooses_tools': False,
                           'note': 'interface capability comparison only; no real-model accuracy or cost improvement measured'},
              'holdout_sha256': hashlib.sha256((ROOT/'data/holdout_cases.json').read_bytes()).hexdigest(),
              'cases': cases, 'all_passed': all(c['passed'] for c in cases)}
    (out/'acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'all_passed': report['all_passed'], 'cases': [{'case': c['case'], 'passed': c['passed']} for c in cases],
                      'external_model_verified': False}, ensure_ascii=False, indent=2))
    return 0 if report['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
