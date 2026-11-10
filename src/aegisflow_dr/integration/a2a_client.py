# SPDX-License-Identifier: Apache-2.0
"""Official A2A SDK REST client constrained to the verified stateless review profile."""
import asyncio
import math
from time import monotonic

import httpx
from a2a.client import ClientCallContext
from a2a.client.errors import A2AClientError
from a2a.client.transports.rest import RestTransport

from ..coordination.contracts import MAX_MESSAGE_BYTES
from ..integration.secure_review import post_json
from ..security.mtls import TLSFiles
from ..security.policy import EgressPolicy
from .a2a_profile import (VERSION, SEND_PATH, ProtocolError, agent_card, decode_request,
                          decode_response, make_request, wire)


class VerifiedA2AHTTPTransport(httpx.AsyncBaseTransport):
    """No SDK operation can bypass the fixed endpoint, profile or mTLS transport."""
    def __init__(self, endpoint: EgressPolicy, material: TLSFiles, *, timeout=5.0):
        if (type(endpoint) is not EgressPolicy or endpoint.path != SEND_PATH
                or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 10):
            raise ProtocolError('Invalid A2A transport configuration')
        self.endpoint, self.material, self.timeout = endpoint, material, timeout

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url, endpoint = request.url, self.endpoint
        if (request.method != 'POST' or url.scheme != 'https' or url.host != endpoint.hostname
                or (url.port or 443) != endpoint.port or url.raw_path != SEND_PATH.encode()
                or url.query or url.fragment or url.userinfo
                or request.headers.get_list('A2A-Version') != [VERSION]
                or request.headers.get('Content-Type') != 'application/json'
                or any(name in request.headers for name in ('Authorization', 'Proxy-Authorization', 'Cookie',
                    'A2A-Extensions', 'X-Forwarded-Client-Cert'))):
            raise ProtocolError('A2A operation or routing rejected')
        try:
            deadline = monotonic() + self.timeout
            async with asyncio.timeout(self.timeout):
                body = bytearray()
                async for chunk in request.stream:
                    if type(chunk) is not bytes or len(body) + len(chunk) > MAX_MESSAGE_BYTES:
                        raise ProtocolError('A2A request budget exceeded')
                    body.extend(chunk)
                _, proposal = decode_request(bytes(body))
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise ProtocolError('A2A request deadline exceeded')
                data = await asyncio.to_thread(post_json, bytes(body), endpoint=endpoint,
                    material=self.material, timeout=remaining, a2a_version=VERSION)
                decode_response(data, proposal)
                return httpx.Response(200, headers={'Content-Type': 'application/json', 'A2A-Version': VERSION},
                                      content=data, request=request)
        except (ValueError, OSError, TimeoutError):
            raise ProtocolError('A2A review exchange rejected') from None


async def review_a2a(payload: bytes, *, endpoint: EgressPolicy, material: TLSFiles, timeout=5.0) -> dict:
    request = make_request(payload)
    transport = VerifiedA2AHTTPTransport(endpoint, material, timeout=timeout)
    try:
        async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False) as http:
            client = RestTransport(http, agent_card(endpoint), f'https://{endpoint.hostname}:{endpoint.port}',
                                   is_shared_httpx=True)
            response = await client.send_message(request,
                context=ClientCallContext(service_parameters={'A2A-Version': VERSION}))
            _, proposal = decode_request(wire(request))
            return decode_response(wire(response), proposal)[1]
    except (ValueError, OSError, TimeoutError, httpx.HTTPError, A2AClientError):
        raise ProtocolError('A2A review exchange rejected') from None
