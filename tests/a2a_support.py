# SPDX-License-Identifier: Apache-2.0
"""A2A test hosting only; no production HTTP listener is provided."""
from dataclasses import replace

from aegisflow_dr.integration.a2a_profile import ProtocolError, SEND_PATH, handle_send
from tls_support import review_server


def a2a_server(certificates, runs, policy, *, response=None):
    def dispatch(peer, payload, headers, path, access):
        try:
            return 200, handle_send(peer, payload, runs, access, method='POST', path=path,
                versions=tuple(headers.get_all('A2A-Version', [])),
                content_types=tuple(headers.get_all('Content-Type', [])))
        except ProtocolError:
            return 400, b'{"error":{"code":3,"message":"A2A profile rejected"}}'
    return review_server(certificates, runs, policy, handler=dispatch, response=response)


def send_endpoint(endpoint):
    return replace(endpoint, path=SEND_PATH)
