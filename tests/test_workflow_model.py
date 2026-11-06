import asyncio
import json

import httpx

from travel.core.config import Settings
from travel.core.model import WorkflowModel
from travel.core.prompts import ASSISTANT_IDENTITY
from travel.workflows.rag import GroundedAnswer


def test_structured_model_adapter_and_shared_call_limit():
    requests=[]
    def provider(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"text":"Hello","citations":[]}'}}]})
    model=WorkflowModel(Settings(model_api_key='fixture-only'),True,httpx.MockTransport(provider))
    async def scenario():
        for _ in range(8):
            response=await model.ask('general_conversation','Answer normally',{'question':'Hi'},GroundedAnswer)
            assert response.text=='Hello'
        assert await model.ask('general_conversation','Answer normally',{},GroundedAnswer) is None
    asyncio.run(scenario())
    assert len(requests)==8 and model.calls==8
    assert all(r['response_format']=={'type':'json_object'} for r in requests)
    assert all(r['messages'][0]['content'].startswith(ASSISTANT_IDENTITY) for r in requests)
    assert all('Answer normally' in r['messages'][0]['content'] for r in requests)
    assert all('Return JSON only' in r['messages'][0]['content'] for r in requests)


def test_provider_failure_or_reflected_credential_never_becomes_a_user_answer():
    def provider(request):
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"text":"fixture-only","citations":[]}'}}]})
    model=WorkflowModel(Settings(model_api_key='fixture-only'),True,httpx.MockTransport(provider))
    assert asyncio.run(model.ask('answer','Answer',{},GroundedAnswer)) is None
    assert 'fixture-only' not in json.dumps(model.trace)


def test_provider_timeout_is_identified_without_logging_credentials():
    def provider(request):
        raise httpx.ReadTimeout('fixture-only',request=request)
    model=WorkflowModel(Settings(model_api_key='fixture-only'),True,httpx.MockTransport(provider))
    assert asyncio.run(model.ask('answer','Answer',{},GroundedAnswer)) is None
    assert model.trace[-1]['error_kind']=='provider_timeout'
    assert 'fixture-only' not in json.dumps(model.trace)
