# SPDX-License-Identifier: Apache-2.0
"""TLS 1.3 with explicit CA trust and mandatory client certificates."""
from dataclasses import dataclass, field
from hashlib import sha256
import os
from pathlib import Path
import ssl


class SecurityError(ValueError):
    """Sanitized identity/configuration rejection."""


@dataclass(frozen=True)
class TLSFiles:
    ca_file: Path = field(repr=False)
    certificate_file: Path = field(repr=False)
    private_key_file: Path = field(repr=False)


def _context(material: TLSFiles, *, server: bool) -> ssl.SSLContext:
    try:
        if type(material) is not TLSFiles or any(not isinstance(path, Path) or not path.is_file()
                for path in (material.ca_file, material.certificate_file, material.private_key_file)):
            raise SecurityError('TLS configuration rejected')
        if os.name == 'posix' and material.private_key_file.stat().st_mode & 0o077:
            raise SecurityError('TLS configuration rejected')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        context.verify_flags |= ssl.VERIFY_X509_STRICT
        context.check_hostname = not server
        context.hostname_checks_common_name = False
        context.options |= ssl.OP_NO_COMPRESSION
        context.set_alpn_protocols(['http/1.1'])
        context.load_verify_locations(cafile=str(material.ca_file))
        # A callback avoids an interactive OpenSSL prompt for unsupported encrypted keys.
        context.load_cert_chain(str(material.certificate_file), str(material.private_key_file), password=lambda: b'')
        return context
    except (OSError, ValueError, TypeError):
        raise SecurityError('TLS configuration rejected') from None


def client_context(material: TLSFiles) -> ssl.SSLContext:
    return _context(material, server=False)


def server_context(material: TLSFiles) -> ssl.SSLContext:
    return _context(material, server=True)


def peer_fingerprint(peer: ssl.SSLSocket, *, client: bool) -> str:
    """Extract a leaf pin only from the verified side of an actual TLS channel.

    client=True means the remote peer is a client, so this is a server-side socket.
    Host code and SSLContext configuration are trusted; labels are not credentials.
    """
    if (not isinstance(peer, ssl.SSLSocket) or peer.server_side is not client
            or peer.version() != 'TLSv1.3' or peer.context.verify_mode != ssl.CERT_REQUIRED
            or peer.context.minimum_version != ssl.TLSVersion.TLSv1_3
            or not peer.context.verify_flags & ssl.VERIFY_X509_STRICT
            or not client and (not peer.context.check_hostname or peer.context.hostname_checks_common_name)):
        raise SecurityError('Verified mutual TLS channel required')
    certificate = peer.getpeercert(binary_form=True)
    if not certificate:
        raise SecurityError('Verified peer certificate required')
    return sha256(certificate).hexdigest()
