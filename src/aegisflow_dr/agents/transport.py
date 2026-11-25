# SPDX-License-Identifier: Apache-2.0
"""How agent work crosses a boundary: in process, the local MCP tool profile, or A2A over mutual TLS.

``in_process`` is the default and always available. ``plan(requested)`` decides, per run, which optional path is
used and records why another one was not:

- **MCP (tools):** with the ``mcp`` extra and ``transport`` "mcp" or "auto", a specialist's call of a tool the local
  MCP profile can express (``diagnose_csv``, ``run_batch``, ``query_lineage`` on ``source_orders``; see
  ``integration.mcp_tools``) is sent through the official MCP client to a ``LocalToolSession`` whose ``ToolPolicy``
  grants exactly that one tool for one call. The report that comes back is rebuilt into the same dataclass the
  in-process function returns, so executors and evidence digests do not depend on the path. Every other tool, a payload
  above the profile's CSV limit, a payload that is not UTF-8, or a report above the profile's output limit stays (or
  falls back to) in process, and the reason is recorded with the call.
- **A2A (Judge):** with the ``a2a`` extra and ``cryptography``, and ``transport`` "a2a" or "auto", the final Judge
  (A27) task is sent as an A2A 1.0 ``SendMessageRequest`` (official protobuf models) through the existing bounded mTLS
  exchange ``integration.secure_review.post_json`` to a loopback endpoint on 127.0.0.1 that runs A27 and answers with
  its ``agent-result-v1`` in a ``SendMessageResponse``. Both sides use TLS 1.3 with leaf certificates issued by an
  ephemeral CA created for this run in a private temporary directory (0700, keys 0600) that is deleted when the run
  ends, also on error. The server pins the client leaf and the client pins the server leaf (SHA-256 of the DER
  certificate); the record carries the CA and leaf fingerprints. The endpoint lives in the same process: this
  demonstrates an authenticated, contract-checked hop, not a remote deployment.

Nothing here writes key material anywhere but that temporary directory.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
import os
from pathlib import Path
import secrets
import shutil
from tempfile import mkdtemp
from threading import Thread
from uuid import NAMESPACE_URL, uuid4, uuid5

from ..batch import Artifact, BatchReport, Reconciliation, downstream, run_batch
from ..pipeline import Finding, InputRejected, Report, diagnose_csv
from .context import PolicyDenied

IN_PROCESS, MCP_LOCAL, A2A_MTLS = "in_process", "mcp_local", "a2a_mtls"
REQUESTS = ("auto", "in_process", "mcp", "a2a")
DATASET = "source_orders"
MAX_CSV_CHARACTERS = 16_384  # integration.mcp_tools.MAX_CSV_CHARACTERS (the profile's input schema limit)
A2A_TIMEOUT_S = 10.0
_SERVER_NAME = "localhost"
_LOOPBACK = "127.0.0.1"


def _importable(*names):
    try:
        for name in names:
            import_module(name)
    except ImportError:
        return False
    return True


def mcp_available():
    """True when the optional ``mcp`` extra (official SDK and the local tool profile) imports."""
    return _importable("mcp", "aegisflow_dr.integration.mcp_tools")


def a2a_available():
    """True when the optional ``a2a`` extra and ``cryptography`` (for the ephemeral CA) import."""
    return _importable("a2a", "cryptography", "aegisflow_dr.integration.a2a_profile")


def plan(requested):
    """``{"requested", "tools": {"mode", "reason"}, "judge": {"mode", "reason"}}`` for a run."""
    if requested not in REQUESTS:
        raise InputRejected("Unknown agent transport")
    if requested in ("auto", "mcp"):
        tools = {"mode": MCP_LOCAL, "reason": None} if mcp_available() else {"mode": IN_PROCESS,
                                                                            "reason": "mcp_extra_unavailable"}
    else:
        tools = {"mode": IN_PROCESS, "reason": "mcp_not_requested"}
    if requested in ("auto", "a2a"):
        judge = {"mode": A2A_MTLS, "reason": None} if a2a_available() else {"mode": IN_PROCESS,
                                                                           "reason": "a2a_extra_unavailable"}
    else:
        judge = {"mode": IN_PROCESS, "reason": "a2a_not_requested"}
    return {"requested": requested, "tools": tools, "judge": judge}


# -- MCP (tools) ----------------------------------------------------------------------------------------------------
def _csv_arguments(args):
    payload = args[0] if len(args) == 1 else None
    if type(payload) is not bytes:
        return None, "unsupported_call"
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None, "payload_not_utf8"
    if len(text) > MAX_CSV_CHARACTERS:
        return None, "payload_exceeds_mcp_limit"
    return {"dataset": DATASET, "csv_text": text}, None


def _lineage_arguments(args):
    if args != (DATASET,):
        return None, "unsupported_call"
    return {"dataset": DATASET}, None


def _report(data):
    findings = tuple(Finding(**{**f, "record_numbers": tuple(f["record_numbers"])}) for f in data["findings"])
    return Report(**{**data, "findings": findings})


def _batch_report(data):
    return BatchReport(**{**data, "source_check": _report(data["source_check"]),
                          "artifacts": tuple(Artifact(**a) for a in data["artifacts"]),
                          "reconciliation": tuple(Reconciliation(**{**r, "evidence_sha256": tuple(r["evidence_sha256"])})
                                                  for r in data["reconciliation"]),
                          "potential_downstream": tuple(data["potential_downstream"])})


def _lineage(data):
    return tuple(data["potential_downstream"])


# tool name -> (the in-process function it stands for, argument builder, report rebuilder)
MCP_TOOLS = {"diagnose_csv": (diagnose_csv, _csv_arguments, _report),
             "run_batch": (run_batch, _csv_arguments, _batch_report),
             "query_lineage": (downstream, _lineage_arguments, _lineage)}


class McpTools:
    """Routes eligible tool calls through the official MCP client to a one-call ``LocalToolSession``."""

    def __init__(self):
        import anyio
        from mcp import Client
        from ..gateway import ToolPolicy
        from ..integration.mcp_tools import PROTOCOL_VERSION, LocalToolSession
        self._anyio, self._client, self._policy = anyio, Client, ToolPolicy
        self._version, self._session = PROTOCOL_VERSION, LocalToolSession

    def route(self, name, fn, args, kwargs):
        """(MCP arguments, None) when the profile can carry this call, else (None, reason it stays in process)."""
        spec = MCP_TOOLS.get(name)
        if spec is None:
            return None, "tool_not_in_mcp_profile"
        if fn is not spec[0] or kwargs:
            return None, "unsupported_call"
        return spec[1](args)

    async def _exchange(self, session, name, arguments):
        async with self._client(session.server, mode=self._version) as client:
            result = await client.call_tool(name, arguments)
        return result.structured_content

    def invoke(self, name, arguments, fn, args):
        """(value, transport, reason). Raises InputRejected, PolicyDenied or another error (a tool error)."""
        session = self._session(self._policy(frozenset({(name, DATASET)}), max_calls=1, timeout_seconds=60))
        content = self._anyio.run(self._exchange, session, name, arguments)
        outcome = content["outcome"]
        if outcome == "OK":
            return MCP_TOOLS[name][2](content["report"]), MCP_LOCAL, None
        if outcome == "OUTPUT_REJECTED":  # the profile's 64 KiB output limit, not a tool failure
            return fn(*args), IN_PROCESS, "mcp_output_limit"
        if outcome == "INPUT_REJECTED":
            raise InputRejected("Tool input rejected")
        if outcome == "DENIED":
            raise PolicyDenied("TOOL_NOT_ALLOWED")
        raise RuntimeError("MCP tool outcome " + outcome)


# -- A2A over mutual TLS (Judge) ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Pki:
    root: Path
    ca_sha256: str
    server: object  # security.mtls.TLSFiles
    server_sha256: str
    client: object
    client_sha256: str

    def fingerprints(self):
        return {"ca_sha256": self.ca_sha256, "server_sha256": self.server_sha256, "client_sha256": self.client_sha256}


def _issue(root, label, subject_key, ca_cert, ca_key, *, server):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    from ..security.mtls import TLSFiles
    now = datetime.now(timezone.utc)
    usage = ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH
    certificate = (x509.CertificateBuilder()
                   .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _SERVER_NAME)]))
                   .issuer_name(ca_cert.subject).public_key(subject_key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(hours=1))
                   .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                                key_encipherment=False, data_encipherment=False, key_agreement=False,
                                                key_cert_sign=False, crl_sign=False, encipher_only=None,
                                                decipher_only=None), critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(subject_key.public_key()), critical=False)
                   .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                                  critical=False)
                   .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
                   .add_extension(x509.SubjectAlternativeName([x509.DNSName(_SERVER_NAME)]), critical=False)
                   .sign(ca_key, hashes.SHA256()))
    cert_file, key_file = root / (label + ".pem"), root / (label + ".key")
    key_file.touch(mode=0o600)
    key_file.write_bytes(subject_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    pin = sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()
    return TLSFiles(root / "ca.pem", cert_file, key_file), pin


@contextmanager
def ephemeral_pki():
    """A run-scoped CA with a server and a client leaf in a 0700 temporary directory, removed on exit."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    root = Path(mkdtemp(prefix="aegisflow-a2a-"))
    try:
        os.chmod(root, 0o700)
        ca_key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AegisFlow ephemeral run CA")])
        now = datetime.now(timezone.utc)
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
              .serial_number(x509.random_serial_number())
              .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(hours=1))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                           data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                           crl_sign=True, encipher_only=None, decipher_only=None), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
              .sign(ca_key, hashes.SHA256()))
        (root / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        ca_pin = sha256(ca.public_bytes(serialization.Encoding.DER)).hexdigest()
        server, server_pin = _issue(root, "server", ec.generate_private_key(ec.SECP256R1()), ca, ca_key, server=True)
        client, client_pin = _issue(root, "client", ec.generate_private_key(ec.SECP256R1()), ca, ca_key, server=False)
        yield Pki(root, ca_pin, server, server_pin, client, client_pin)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _context_id(task):
    return str(uuid5(NAMESPACE_URL, "aegisflow:agent-run:" + task["run_id"]))


def _message(pb, role, context_id, key, value):
    from google.protobuf import json_format
    message = pb.Message(message_id=str(uuid4()), context_id=context_id, role=role,
                         parts=[pb.Part(media_type="application/json")])
    json_format.ParseDict({key: value}, message.parts[0].data)
    return message


def _integral(value):
    """protobuf ``Struct`` carries every JSON number as a double; restore integral values to integers (every integer
    of the task and result contracts is far below 2**53, and the Judge result carries no fractional numbers)."""
    if type(value) is float and value.is_integer():
        return int(value)
    if type(value) is list:
        return [_integral(item) for item in value]
    if type(value) is dict:
        return {key: _integral(item) for key, item in value.items()}
    return value


def _unwrap(payload, model, role, context_id, key):
    """The single JSON data part ``{key: value}`` of an A2A message with the expected role and context."""
    from ..integration.a2a_profile import _load, _part, _require
    raw, _ = _load(payload, model)
    _require(set(raw) <= {"message", "configuration"} and type(raw.get("message")) is dict)
    message = raw["message"]
    _require(set(message) == {"messageId", "contextId", "role", "parts"} and message["role"] == role
             and message["contextId"] == context_id and type(message["parts"]) is list and len(message["parts"]) == 1)
    data = _part(message["parts"][0])
    _require(set(data) == {key})
    return _integral(data[key])


def _serve(pki, task, review):
    """A loopback mTLS endpoint for one Judge task; returns (server, thread)."""
    from a2a.types import a2a_pb2 as pb
    from ..coordination.contracts import MAX_MESSAGE_BYTES
    from ..integration.a2a_profile import SEND_PATH, VERSION, ProtocolError, wire
    from ..security.mtls import SecurityError, peer_fingerprint, server_context

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        block_on_close = False

        def handle_error(self, request, client_address):
            pass  # handshake and socket failures surface on the client side as a typed TransportError

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.connection.settimeout(A2A_TIMEOUT_S)
            try:
                if not secrets.compare_digest(peer_fingerprint(self.connection, client=True), pki.client_sha256):
                    raise SecurityError("Client identity denied")
                length = self.headers.get("Content-Length", "")
                if (self.path != SEND_PATH or self.headers.get_all("A2A-Version", []) != [VERSION]
                        or self.headers.get("Content-Type") != "application/json" or not length.isdigit()
                        or int(length) > MAX_MESSAGE_BYTES):
                    raise ProtocolError("A2A request rejected")
                received = _unwrap(self.rfile.read(int(length)), pb.SendMessageRequest(), "ROLE_USER",
                                   _context_id(task), "task")
                if received != task:
                    raise ProtocolError("Unexpected Judge task")
                reply = pb.SendMessageResponse(message=_message(pb, pb.ROLE_AGENT, _context_id(task), "result",
                                                                review(received)))
                status, body = 200, wire(reply)
            except SecurityError:
                status, body = 403, b'{"error":"denied"}'
            except ProtocolError:
                status, body = 400, b'{"error":"rejected"}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

    server = Server((_LOOPBACK, 0), Handler)
    server.socket = server_context(pki.server).wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    return server, thread


def a2a_review(task, review, *, pki, timeout=A2A_TIMEOUT_S):
    """Send the Judge ``task`` over A2A+mTLS to a loopback endpoint that answers with ``review(task)``.

    Returns the decoded result object (the caller validates it). Raises ``secure_review.TransportError`` or
    ``a2a_profile.ProtocolError`` when the exchange is rejected.
    """
    from a2a.types import a2a_pb2 as pb
    from ..integration.a2a_profile import SEND_PATH, VERSION, wire
    from ..integration.secure_review import post_json
    from ..security.policy import EgressPolicy
    request = pb.SendMessageRequest(message=_message(pb, pb.ROLE_USER, _context_id(task), "task", task),
                                    configuration=pb.SendMessageConfiguration(accepted_output_modes=["application/json"],
                                                                              history_length=0))
    server, thread = _serve(pki, task, review)
    try:
        endpoint = EgressPolicy(_SERVER_NAME, server.server_port, _LOOPBACK, pki.server_sha256, path=SEND_PATH,
                                allow_loopback=True)
        reply = post_json(wire(request), endpoint=endpoint, material=pki.client, timeout=timeout, a2a_version=VERSION)
        return _unwrap(reply, pb.SendMessageResponse(), "ROLE_AGENT", _context_id(task), "result")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
