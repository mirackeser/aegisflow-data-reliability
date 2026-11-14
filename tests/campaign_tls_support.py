# SPDX-License-Identifier: Apache-2.0
"""Ephemeral loopback gateway for campaign integration; not a deployable server."""
from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tls_support import TestCertificates, review_server
from aegisflow_dr.advisory.contracts import decode, encode
from aegisflow_dr.advisory.dispatch import AdapterRequest
from aegisflow_dr.advisory.gateway import gateway_adapter
from aegisflow_dr.advisory.recovery_auth import RecoverySigner, signing_bytes
from aegisflow_dr.benchmark.campaign_cli import fixture_adapter
from aegisflow_dr.security.policy import AccessPolicy
from aegisflow_dr.storage.store import sha


@contextmanager
def campaign_gateway(root, *, tamper=False, wrong_claim=False):
    certificates = TestCertificates(root)
    key = Ed25519PrivateKey.generate()
    principal = str(uuid4())
    adapters = {}

    def handler(peer, body, *_):
        query = decode('gateway-request', body)
        adapter = adapters[query['operation_sha256']]
        response = adapter.send(AdapterRequest(bytes.fromhex(query['messages_hex']), query['request_sha256'],
            query['model_id'], query['remaining_ms'], query['output_limit'], 16384))
        if wrong_claim:
            value = decode('response', response.payload)
            value['assessment'] = ('SOURCE_QUALITY_FAILURE' if value['assessment'] == 'NO_FAILURE_OBSERVED'
                                   else 'NO_FAILURE_OBSERVED')
            response = replace(response, payload=encode('response', value))
        value = {**{k: query[k] for k in ('version', 'operation_sha256', 'request_sha256',
            'input_sha256', 'quote_sha256', 'model_id')}, 'receipt_sha256': '1' * 64,
            'payload_hex': response.payload.hex(), 'input_tokens': 8, 'output_tokens': 2}
        metadata = {'version': '1', 'purpose': 'model-gateway-result', 'principal_id': principal,
            'operation_sha256': query['operation_sha256'], 'key_sha256': sha(key.public_key().public_bytes_raw()),
            'payload_sha256': sha(encode('gateway-result', value)), 'issued_at_ms': 900, 'expires_at_ms': 100000}
        signature = '0' * 128 if tamper else key.sign(signing_bytes(metadata)).hex()
        proof = encode('recovery-signature', {**metadata, 'signature': signature})
        return 200, encode('gateway-response', {'result': value, 'signature_hex': proof.hex()})

    with review_server(certificates, None, AccessPolicy(), handler=handler) as (server, endpoint):
        def build(prepared, operation):
            quote, fixture = fixture_adapter(prepared, operation)
            digest = sha(operation.payload)
            adapters[digest] = fixture
            grant = RecoverySigner(principal, 'model-gateway-result', digest,
                key.public_key().public_bytes_raw(), 900, 100000)
            return quote, gateway_adapter(prepared, quote, operation, endpoint=endpoint,
                material=certificates.client, grant=grant, clock_ms=lambda: 1000)
        yield build, server
