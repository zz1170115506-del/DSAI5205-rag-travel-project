"""Keep slow chat responses active without exposing partial model/tool output."""
import asyncio
from contextlib import suppress
import json

from fastapi import HTTPException

HEARTBEAT_SECONDS = 5
REQUEST_SECONDS = 68


async def chat_events(run):
    async def bounded():
        async with asyncio.timeout(REQUEST_SECONDS):
            return await run()

    task = asyncio.create_task(bounded())
    try:
        yield b'\n'
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
            if not done:
                yield b'\n'
        try:
            event = {'type': 'result', 'status': 200, 'data': task.result()}
        except HTTPException as exc:
            event = {'type': 'result', 'status': exc.status_code, 'detail': exc.detail}
        except TimeoutError:
            event = {'type': 'result', 'status': 504, 'detail': '等待超时，请稍后重试或简化问题。'}
        except Exception:
            # Provider exception text may contain credentials. Never return it.
            event = {'type': 'result', 'status': 500, 'detail': '服务处理失败，请稍后重试。'}
        yield (json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n').encode()
    finally:
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task
