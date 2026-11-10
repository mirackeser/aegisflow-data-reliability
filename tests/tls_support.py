# SPDX-License-Identifier: Apache-2.0
"""Ephemeral loopback TLS fixture; no certificates or private keys are checked in."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import ssl
from threading import Thread

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from aegisflow_dr.security.mtls import TLSFiles, SecurityError, server_context
from aegisflow_dr.integration.secure_review import handle_review
from aegisflow_dr.security.policy import EgressPolicy


class TestCertificates:
    def __init__(self, root: Path):
        self.root = root
        self.key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Ephemeral test root')])
        self.ca = self._certificate(name, self.key, name, self.key, ca=True)
        self.ca_file = root / 'ca.pem'
        self.ca_file.write_bytes(self.ca.public_bytes(serialization.Encoding.PEM))
        self.server, self.server_pin = self.leaf('server', server=True)
        self.client, self.client_pin = self.leaf('client', server=False)

    @staticmethod
    def _certificate(subject, key, issuer, signer, *, ca=False, server=True, expired=False, san=True):
        now = datetime.now(timezone.utc)
        builder = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(days=3 if expired else 1))
                   .not_valid_after(now - timedelta(days=1) if expired else now + timedelta(days=1))
                   .add_extension(x509.BasicConstraints(ca=ca, path_length=0 if ca else None), critical=True)
                   .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                       key_encipherment=False, data_encipherment=False, key_agreement=False,
                       key_cert_sign=ca, crl_sign=ca, encipher_only=None, decipher_only=None), critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                   .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(signer.public_key()), critical=False))
        if not ca:
            builder = builder.add_extension(x509.ExtendedKeyUsage([
                ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
            if san:
                builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False)
        return builder.sign(signer, hashes.SHA256())

    def leaf(self, label, *, server, expired=False, san=True):
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        cert = self._certificate(name, key, self.ca.subject, self.key, server=server, expired=expired, san=san)
        cert_file, key_file = self.root / (label + '.pem'), self.root / (label + '.key')
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        key_file.chmod(0o600)
        pin = sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
        return TLSFiles(self.ca_file, cert_file, key_file), pin


@contextmanager
def review_server(certificates, runs, policy, *, material=None, context=None, response=None, handler=None):
    """response(peer, request_bytes) -> raw HTTP bytes, for hostile response tests."""
    class Server(ThreadingHTTPServer):
        daemon_threads = True
        block_on_close = False
        def handle_error(self, request, client_address):
            # Handshake/socket failures are expected test outcomes; never print them.
            pass
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args):
            pass
        def do_POST(self):
            self.server.requests += 1
            self.connection.settimeout(2)
            body = self.rfile.read(int(self.headers['Content-Length']))
            try:
                if response is not None:
                    response(self.connection, body)
                    self.close_connection = True
                    return
                if handler is not None:
                    status, data = handler(self.connection, body, self.headers, self.path, self.server.access_policy)
                else:
                    data = handle_review(self.connection, body, runs, self.server.access_policy)
                    status = 200
            except SecurityError:
                data, status = b'{"error":"denied"}', 403
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True
    server = Server(('127.0.0.1', 0), Handler)
    server.requests = 0
    server.access_policy = policy
    server.socket = (context or server_context(material or certificates.server)).wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
    thread.start()
    endpoint = EgressPolicy('localhost', server.server_port, '127.0.0.1', certificates.server_pin,
                            allow_loopback=True)
    try:
        yield server, endpoint
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
