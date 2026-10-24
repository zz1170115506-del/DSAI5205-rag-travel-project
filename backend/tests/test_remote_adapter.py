import httpx
import pytest

from app.core.config import Settings
from app.rag.provider import ModelProvider


async def test_remote_protocol_embeddings_router_and_stream(monkeypatch):
    calls=[]
    def handle(request):
        calls.append(request.url.path)
        assert request.headers['authorization']=='Bearer test-only'
        if request.url.path.endswith('/embeddings'):
            return httpx.Response(200,json={'data':[{'index':0,'embedding':[1.0]+[0.0]*7}]})
        import json
        body=json.loads(request.content)
        if not body.get('stream'):
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"intent":"fact","queries":["museum"],"filters":{},"clarification":null}'}}]})
        return httpx.Response(200,headers={'content-type':'text/event-stream'},
            content='data: {"choices":[{"delta":{"content":"答案 [1]"}}]}\n\ndata: [DONE]\n\n')
    client=httpx.AsyncClient
    monkeypatch.setattr('app.rag.provider.httpx.AsyncClient',lambda **kwargs:client(transport=httpx.MockTransport(handle),**kwargs))
    settings=Settings(_env_file=None,model_mode='remote',embedding_dim=8,
        llm_base_url='https://provider.invalid/v1',llm_api_key='test-only',llm_model='test',
        embedding_base_url='https://provider.invalid/v1',embedding_api_key='test-only',embedding_model='test')
    p=ModelProvider(settings)
    vector=await p.embed(['test'])
    assert vector.shape==(1,8)
    assert (await p.json_answer('test',{}))['intent']=='fact'
    assert ''.join([x async for x in p.generate({'evidence':[]})])=='答案 [1]'
    assert p.calls==3


async def test_remote_dimension_mismatch(monkeypatch):
    client=httpx.AsyncClient
    monkeypatch.setattr('app.rag.provider.httpx.AsyncClient',lambda **kwargs:client(
        transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'data':[{'index':0,'embedding':[1,2]}]})),**kwargs))
    settings=Settings(_env_file=None,model_mode='remote',embedding_dim=8,
        llm_base_url='https://provider.invalid/v1',llm_api_key='test',llm_model='test',
        embedding_base_url='https://provider.invalid/v1',embedding_api_key='test',embedding_model='test')
    with pytest.raises(ValueError,match='EMBEDDING_DIM'):
        await ModelProvider(settings).embed(['text'])
