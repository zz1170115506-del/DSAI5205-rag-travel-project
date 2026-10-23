"""官方 MCP SDK 客户端；本地 stdio 与高德 Streamable HTTP 两种真实传输。"""
import asyncio
import json
import os
import re
import sys
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from .config import ROOT, Settings


class ToolError(Exception):
    pass


def unpack(result) -> dict:
    if result.isError:
        # 本地工具的校验消息可公开；外部接口错误在调用层统一脱敏。
        message = ' '.join(c.text for c in result.content if getattr(c, 'type', '') == 'text')
        message = re.sub(r'^Error executing tool [\w-]+:\s*', '', message)
        raise ToolError(message[:300] or '工具调用未成功。')
    if result.structuredContent is not None:
        return result.structuredContent
    parts = [c.text for c in result.content if getattr(c, 'type', '') == 'text']
    try:
        value = json.loads('\n'.join(parts))
        return value if isinstance(value, dict) else {'result': value}
    except (ValueError, TypeError):
        return {'text': '\n'.join(parts)}


@asynccontextmanager
async def local_session():
    # 不把模型／高德密钥传给只需本地资料的子进程。
    env = {k: v for k, v in os.environ.items() if k in ['PATH', 'SYSTEMROOT', 'WINDIR', 'TMP', 'TEMP', 'HOME']}
    env['PYTHONIOENCODING'] = 'utf-8'
    params = StdioServerParameters(command=sys.executable, args=['-m', 'travel.mcp_server'], cwd=ROOT, env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=20)) as session:
            await session.initialize()
            yield session


async def local_call(name, arguments):
    start = time.monotonic()
    async with asyncio.timeout(30):
        async with local_session() as session:
            listing = await session.list_tools()
            if name not in {t.name for t in listing.tools}:
                raise ToolError('本地工具未注册。')
            raw = await session.call_tool(name, arguments)
    # 先关闭协议上下文，再处理业务错误，避免错误被 task group 包装。
    result = unpack(raw)
    return result, {'server': '本地香港旅行 MCP', 'transport': 'stdio',
                    'steps': ['initialize', 'tools/list', f'tools/call → {name}'],
                    'arguments': arguments, 'elapsed_ms': round((time.monotonic()-start)*1000),
                    'status': 'success', 'live_amap': False}


@asynccontextmanager
async def amap_session(settings: Settings, http_transport=None):
    if not settings.amap_api_key:
        raise ToolError('尚未配置高德 Key。请在项目 .env 中填写 AMAP_API_KEY 后重启。')
    url = 'https://mcp.amap.com/mcp?' + urlencode({'key': settings.amap_api_key})
    # 不记录 URL，避免把 query 中的密钥写入日志；保持 TLS 证书校验。
    async with httpx.AsyncClient(timeout=httpx.Timeout(25, read=40), follow_redirects=False, transport=http_transport) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session:
                await session.initialize()
                yield session


async def amap_search(query: str, settings: Settings, http_transport=None) -> dict:
    if not settings.amap_api_key:
        return {'mode': 'not_configured', 'message': '未配置高德 Key；本次没有调用高德。', 'results': None}
    try:
        async with asyncio.timeout(50):
            async with amap_session(settings, http_transport) as session:
                tools = (await session.list_tools()).tools
                # 先发现真实工具及参数。只调用只读地点搜索；不开放任意外部工具执行。
                tool = next((t for t in tools if t.name == 'maps_text_search'), None)
                if tool is None:
                    return {'mode': 'schema_changed', 'message': '已连接，但未找到 maps_text_search。请按高德最新工具列表更新适配器。',
                            'available_tools': [t.name for t in tools], 'results': None}
                props = tool.inputSchema.get('properties', {})
                if 'keywords' not in props:
                    raise ToolError('高德搜索参数已变化。')
                args = {'keywords': query}
                if 'city' in props:
                    args['city'] = '香港'
                if 'citylimit' in props:
                    args['citylimit'] = True if props['citylimit'].get('type') == 'boolean' else 'true'
                unsupported = set(tool.inputSchema.get('required', []))-set(args)
                if unsupported:
                    raise ToolError('高德工具新增必填参数，请更新适配器。')
                data = unpack(await session.call_tool(tool.name, args))
                return {'mode': 'live', 'message': '已通过高德 MCP 返回地点搜索数据。请核对同名地点及地区；不代表已生成导航路线。',
                        'tool': tool.name, 'results': data}
    except Exception:
        # 外部异常可能含 key/URL/请求头，不向浏览器或日志回传异常字符串。
        return {'mode': 'unavailable', 'message': '高德连接或搜索失败。请检查 Key、网络、服务权限及香港地区覆盖；本次没有可用的实时结果。', 'results': None}
