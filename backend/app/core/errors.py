import asyncio
import json

import httpx
from pydantic import ValidationError


class ModelResponseError(ValueError):
    """The model returned an unusable structure. Never include raw payloads."""


def public_error(exc):
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return 'MODEL_TIMEOUT', '模型响应超时，请稍后重试或缩短问题。'
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            return 'MODEL_AUTH_ERROR', '模型服务拒绝访问，请检查密钥和模型使用权限。'
        if status == 429:
            return 'MODEL_RATE_LIMIT', '模型服务请求过于频繁，请稍后重试。'
        return 'MODEL_HTTP_ERROR', f'模型服务返回错误（HTTP {status}），请稍后重试。'
    if isinstance(exc, httpx.NetworkError):
        return 'MODEL_NETWORK_ERROR', '无法连接模型服务，请检查网络后重试。'
    if isinstance(exc, (ValidationError, ModelResponseError, json.JSONDecodeError)):
        return 'MODEL_RESPONSE_FORMAT', '模型返回的数据格式异常，请重试或换一种问法。'
    if isinstance(exc, ValueError):
        # Only match program-controlled markers; never expose exception text.
        text = str(exc)
        if text.startswith(('Index ', 'Index/', 'No verified ', 'Invalid index')):
            return 'INDEX_NOT_READY', '知识索引尚未就绪，请完成索引构建后重试。'
        if text.startswith('EMBEDDING_DIM'):
            return 'EMBEDDING_DIMENSION_ERROR', '向量维度与配置不一致，需要核对配置并重建索引。'
        if text == 'Tool budget exceeded':
            return 'TOOL_BUDGET_EXCEEDED', '问题处理步骤超过上限，请拆成更具体的问题。'
    return 'TASK_FAILED', '任务未能完成，请稍后重试；若持续出现，请提供任务编号。'


def validation_summary(exc):
    """Only program-known locations and error types, without input/body/secrets."""
    if isinstance(exc, ValidationError):
        known = {'intent','queries','filters','clarification','query','district','theme','setting','max_price','max_minutes'}
        return [{'field': str(item['loc'][0]) if item['loc'] and item['loc'][0] in known else 'unknown_field',
                 'type': item['type']} for item in exc.errors(include_input=False, include_url=False)]
    return [{'field': 'response', 'type': type(exc).__name__}]
