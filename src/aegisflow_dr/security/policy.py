# SPDX-License-Identifier: Apache-2.0
"""Host-owned exact leaf/resource grants and pinned egress destinations."""
from dataclasses import dataclass
from ipaddress import ip_address
import re
from uuid import UUID

from .mtls import SecurityError, peer_fingerprint


def valid_pin(value):
    return type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except ValueError:
        return False


@dataclass(frozen=True)
class Grant:
    peer_sha256: str
    incident_id: str
    run_id: str

    def __post_init__(self):
        if not valid_pin(self.peer_sha256) or not _uuid(self.incident_id) or not _uuid(self.run_id):
            raise SecurityError('Invalid resource grant')


@dataclass(frozen=True)
class AccessPolicy:
    grants: frozenset[Grant] = frozenset()

    def __post_init__(self):
        if (type(self.grants) is not frozenset or len(self.grants) > 1024
                or any(type(grant) is not Grant for grant in self.grants)):
            raise SecurityError('Invalid access policy')

    def authorize(self, peer, proposal):
        pin = peer_fingerprint(peer, client=True)
        if Grant(pin, proposal['incident_id'], proposal['run_id']) not in self.grants:
            raise SecurityError('Review access denied')


@dataclass(frozen=True)
class EgressPolicy:
    hostname: str
    port: int
    address: str
    server_sha256: str
    path: str = '/review'
    allow_loopback: bool = False

    def __post_init__(self):
        try:
            if (type(self.hostname) is not str or len(self.hostname) > 253
                    or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', self.hostname)
                    or type(self.port) is not int or not 1 <= self.port <= 65535
                    or type(self.address) is not str or not valid_pin(self.server_sha256)
                    or type(self.path) is not str or not (re.fullmatch(r'/[A-Za-z0-9/_-]{0,127}', self.path)
                        or self.path == '/message:send')
                    or self.path.startswith('//') or type(self.allow_loopback) is not bool):
                raise ValueError('Invalid egress configuration')
            address = ip_address(self.address)
            if (str(address) != self.address or address.is_unspecified or address.is_multicast or address.is_link_local
                    or address.is_reserved and not address.is_loopback
                    or getattr(address, 'ipv4_mapped', None) is not None
                    or address.is_loopback and not self.allow_loopback):
                raise ValueError('Disallowed network destination')
        except (ValueError, TypeError):
            raise SecurityError('Egress configuration rejected') from None
