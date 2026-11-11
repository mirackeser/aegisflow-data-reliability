# SPDX-License-Identifier: Apache-2.0
"""Bounded cooperative async-stream bridge for the synchronous trusted dispatcher."""
import asyncio
from contextlib import aclosing
from dataclasses import dataclass

from .contracts import AdvisoryError
from .dispatch import Adapter, AdapterResult, AdapterRequest
from .usage import integer


@dataclass(frozen=True)
class UsageFrame:
    """Final trusted transport usage, separate from generated response bytes."""
    input_tokens: int
    output_tokens: int


async def collect_stream(request, source):
    """Require an owned async generator with aclose; always close on every exit.

    Source must yield control and honor cancellation. This is not process isolation
    or a way to interrupt blocking Python or a cancellation-suppressing provider.
    """
    payload = bytearray()
    usage = None
    chunks = 0
    async with aclosing(source):
        async for item in source:
            chunks += 1
            if chunks > 256 or usage is not None:
                raise AdvisoryError('Stream framing rejected')
            if type(item) is bytes:
                if not item or len(item) > request.max_response_bytes - len(payload):
                    raise AdvisoryError('Stream byte budget exceeded')
                payload.extend(item)
            elif type(item) is UsageFrame:
                integer(item.input_tokens, 0, 10**6)
                integer(item.output_tokens, 0, request.output_limit)
                usage = item
            else:
                raise AdvisoryError('Stream frame rejected')
    if usage is None or not payload:
        raise AdvisoryError('Incomplete stream')
    return AdapterResult(bytes(payload), usage.input_tokens, usage.output_tokens)


def stream_adapter(revision, source_factory):
    """Bridge host-owned async generators; no network/provider is configured.

    Run from a synchronous worker without an already running event loop. A stream
    factory receives exact immutable dispatch input and limits. Its final usage
    must come from trusted transport metadata, never from generated JSON.
    """
    if type(revision) is not str or not revision or not callable(source_factory):
        raise AdvisoryError('Trusted stream configuration required')

    def send(request):
        if type(request) is not AdapterRequest:
            raise AdvisoryError('Trusted stream request required')
        integer(request.remaining_ms, 1, 600_000)
        integer(request.max_response_bytes, 1, 16_384)
        integer(request.output_limit, 1, 10**6)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise AdvisoryError('Synchronous stream worker required')

        async def bounded():
            async with asyncio.timeout(request.remaining_ms / 1000):
                return await collect_stream(request, source_factory(request))

        return asyncio.run(bounded())

    return Adapter(revision, send)
