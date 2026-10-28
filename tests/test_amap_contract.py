"""本地测试服务校验 MCP HTTP 兼容性；不等于真实高德联调。"""
import asyncio
import json

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from travel.config import Settings
from travel.mcp_client import amap_search


def test_streamable_http_adapter_with_local_test_server():
    server = FastMCP('Local contract fixture', stateless_http=True, json_response=True,
        log_level='ERROR', transport_security=TransportSecuritySettings(allowed_hosts=['mcp.amap.com']))

    @server.tool()
    def maps_text_search(keywords: str, city: str, citylimit: bool) -> dict:
        assert city == '香港' and citylimit is True
        return {'fixture_only': True, 'keywords': keywords, 'pois': [{'name':'测试地点，不是真实查询结果'}]}

    async def run():
        transport=httpx.ASGITransport(app=server.streamable_http_app())
        async with server.session_manager.run():
            return await amap_search('香港大馆', Settings(amap_api_key='test-only-key'), transport)
    result=asyncio.run(run())
    assert result['mode']=='live' and result['tool']=='maps_text_search'
    assert result['results']['fixture_only'] is True
    assert 'test-only-key' not in json.dumps(result)


def test_amap_failure_does_not_expose_key():
    def fail(request):
        raise httpx.ConnectError('https://mcp.amap.com/mcp?key=test-secret-key')
    result=asyncio.run(amap_search('香港大馆',Settings(amap_api_key='test-secret-key'),httpx.MockTransport(fail)))
    assert result['mode']=='unavailable'
    assert 'test-secret-key' not in json.dumps(result)
