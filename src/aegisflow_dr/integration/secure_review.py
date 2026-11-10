# SPDX-License-Identifier: Apache-2.0
"""Private read-only review HTTPS binding; not an A2A or MCP wire adapter."""
import http.client
import io
import math
import secrets
import socket
from time import monotonic

from ..coordination.contracts import MAX_MESSAGE_BYTES, encode, parse
from ..coordination.service import review_saved_run
from ..security.mtls import SecurityError, TLSFiles, client_context, peer_fingerprint
from ..security.policy import AccessPolicy, EgressPolicy


class TransportError(ValueError):
    pass


def handle_review(peer, payload: bytes, runs, policy: AccessPolicy) -> bytes:
    """Invoke only behind a TLS-aware host; never trust forwarded identity headers."""
    if type(policy) is not AccessPolicy:
        raise SecurityError('Host access policy required')
    proposal = parse('proposal', payload)
    policy.authorize(peer, proposal)
    result = review_saved_run(runs, encode('proposal', proposal))
    return encode('verdict', result['verdict'])


def _remaining(deadline):
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError('Review deadline exceeded')
    return remaining


class _BoundedReader(io.RawIOBase):
    def __init__(self, peer, deadline):
        super().__init__()
        self.peer, self.deadline, self.budget = peer, deadline, MAX_MESSAGE_BYTES * 2

    def readable(self):
        return True

    def readinto(self, buffer):
        self.peer.settimeout(_remaining(self.deadline))
        data = self.peer.recv(min(len(buffer), self.budget + 1))
        if len(data) > self.budget:
            raise TransportError('Review response budget exceeded')
        self.budget -= len(data)
        buffer[:len(data)] = data
        return len(data)


class _HTTPChannel:
    """Give http.client an authenticated socket with one shared I/O deadline."""
    def __init__(self, peer, deadline):
        self.peer, self.deadline = peer, deadline

    def sendall(self, data):
        self.peer.settimeout(_remaining(self.deadline))
        self.peer.sendall(data)

    def makefile(self, mode):
        return io.BufferedReader(_BoundedReader(self.peer, self.deadline), buffer_size=4096)

    def close(self):
        # HTTPConnection can close its handle before HTTPResponse finishes reading.
        # review_https owns the borrowed TLS socket and closes it in its finally block.
        return None


def review_https(payload: bytes, *, endpoint: EgressPolicy, material: TLSFiles, timeout=5.0) -> dict:
    """One connection, no DNS/proxy/redirect/fallback and no persistent credentials."""
    if (type(endpoint) is not EgressPolicy or type(timeout) not in (int, float)
            or not math.isfinite(timeout) or not 0 < timeout <= 10):
        raise TransportError('Secure review configuration rejected')
    proposal = parse('proposal', payload)
    body = encode('proposal', proposal)
    connection = None
    response = None
    peer = None
    raw = None
    try:
        context = client_context(material)
        deadline = monotonic() + timeout
        family = socket.AF_INET6 if ':' in endpoint.address else socket.AF_INET
        raw = socket.socket(family, socket.SOCK_STREAM)
        raw.settimeout(_remaining(deadline))
        # Connect to the operator's literal address; SNI/hostname validation still use the named service.
        raw.connect((endpoint.address, endpoint.port))
        raw.settimeout(_remaining(deadline))
        peer = context.wrap_socket(raw, server_hostname=endpoint.hostname)
        if not secrets.compare_digest(peer_fingerprint(peer, client=False), endpoint.server_sha256):
            raise SecurityError('Server identity denied')
        connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port)
        connection.sock = _HTTPChannel(peer, deadline)
        connection.request('POST', endpoint.path, body=body,
                           headers={'Content-Type': 'application/json', 'Accept': 'application/json', 'Connection': 'close'})
        response = connection.getresponse()
        lengths = response.headers.get_all('Content-Length', [])
        if (response.status != 200 or response.getheader('Content-Type') != 'application/json'
                or response.getheader('Transfer-Encoding') is not None
                or response.getheader('Content-Encoding') is not None or len(lengths) != 1
                or not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 5
                or int(lengths[0]) > MAX_MESSAGE_BYTES):
            raise TransportError('Review response rejected')
        content = response.read(int(lengths[0]))
        if len(content) != int(lengths[0]):
            raise TransportError('Incomplete review response')
        verdict = parse('verdict', content)
        if verdict['run_id'] != proposal['run_id']:
            raise TransportError('Review context mismatch')
        return verdict
    except (OSError, ValueError, http.client.HTTPException):
        raise TransportError('Secure review exchange rejected') from None
    finally:
        if response is not None:
            response.close()
        if connection is not None:
            connection.close()
        if peer is not None:
            peer.close()
        if raw is not None:
            raw.close()
