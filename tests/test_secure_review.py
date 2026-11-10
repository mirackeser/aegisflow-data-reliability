# SPDX-License-Identifier: Apache-2.0
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from aegisflow_dr.security.mtls import TLSFiles, SecurityError, client_context, server_context, peer_fingerprint
from aegisflow_dr.security.policy import AccessPolicy, EgressPolicy, Grant
from aegisflow_dr.integration.secure_review import (TransportError, handle_review, review_https,
                                                   _remaining)
from aegisflow_dr.coordination.contracts import encode, ContractError, MAX_MESSAGE_BYTES
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.storage import IncidentStore, initialize
from aegisflow_dr.storage.runs import InvestigationRuns
from aegisflow_dr.investigation import default_policy
from tls_support import TestCertificates, review_server


class SecureReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.certs=TestCertificates(self.root)
        self.db=self.root/'evidence.db';initialize(self.db)
        self.store=IncidentStore(self.db);self.runs=InvestigationRuns(self.store)
        incident=self.store.record(generate_orders(),request_key='source')
        self.record=self.runs.execute(incident['incident_id'],default_policy(),request_key='run')
        self.proposal={'version':'1','incident_id':incident['incident_id'],'run_id':self.record['run_id'],
                       'assessment':self.record['trace']['assessment'],
                       'evidence_sha256':sorted({self.record['trace']['source_sha256'],
                            *(s['report_sha256'] for s in self.record['trace']['steps'])})}
        self.policy=AccessPolicy(frozenset({Grant(self.certs.client_pin,incident['incident_id'],self.record['run_id'])}))

    def send(self,endpoint,**kwargs):
        return review_https(encode('proposal',self.proposal),endpoint=endpoint,
                            material=kwargs.pop('material',self.certs.client),**kwargs)

    def test_real_mtls_round_trip_is_authorized_read_only_and_has_no_dns_lookup(self):
        before=self.db.read_bytes()
        with review_server(self.certs,self.runs,self.policy) as (server,endpoint):
            with patch('socket.getaddrinfo',side_effect=AssertionError('DNS must not be used')):
                result=self.send(endpoint)
            self.assertEqual(result['decision'],'ACCEPT')
            self.assertEqual(server.requests,1)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertNotIn('ORD-',json.dumps(result))

    def test_contradictory_proposal_returns_rejection_over_tls(self):
        self.proposal['assessment']='SOURCE_QUALITY_FAILURE'
        with review_server(self.certs,self.runs,self.policy) as (_,endpoint):
            self.assertEqual(self.send(endpoint)['decision'],'REJECT')

    def test_default_deny_blocks_evidence_lookup(self):
        with review_server(self.certs,self.runs,AccessPolicy()) as (_,endpoint):
            with patch.object(self.runs,'read',side_effect=AssertionError('must not read')):
                with self.assertRaises(TransportError):self.send(endpoint)

    def test_cross_run_and_incident_grants_are_denied(self):
        for field in ['run_id','incident_id']:
            original=self.proposal[field];self.proposal[field]='00000000-0000-0000-0000-000000000001'
            with review_server(self.certs,self.runs,self.policy) as (_,endpoint):
                with patch.object(self.runs,'read',side_effect=AssertionError('must not read')):
                    with self.assertRaises(TransportError):self.send(endpoint)
            self.proposal[field]=original

    def test_unknown_leaf_signed_by_same_ca_is_not_an_authorized_identity(self):
        other,_=self.certs.leaf('other-client',server=False)
        with review_server(self.certs,self.runs,self.policy) as (_,endpoint):
            with patch.object(self.runs,'read',side_effect=AssertionError('must not read')):
                with self.assertRaises(TransportError):self.send(endpoint,material=other)

    def test_wrong_server_pin_is_rejected_before_sending_proposal(self):
        with review_server(self.certs,self.runs,self.policy) as (server,endpoint):
            with self.assertRaises(TransportError):self.send(replace(endpoint,server_sha256='a'*64))
            self.assertEqual(server.requests,0)

    def test_wrong_hostname_and_common_name_only_are_rejected(self):
        with review_server(self.certs,self.runs,self.policy) as (_,endpoint):
            with self.assertRaises(TransportError):self.send(replace(endpoint,hostname='wrong.invalid'))
        material,_=self.certs.leaf('no-san',server=True,san=False)
        with review_server(self.certs,self.runs,self.policy,material=material) as (_,endpoint):
            with self.assertRaises(TransportError):self.send(endpoint)

    def test_expired_and_wrong_eku_server_certificates_fail_tls(self):
        for label,server,expired in [('expired-server',True,True),('client-eku-server',False,False)]:
            material,_=self.certs.leaf(label,server=server,expired=expired)
            with review_server(self.certs,self.runs,self.policy,material=material) as (service,endpoint):
                with self.assertRaises(TransportError):self.send(endpoint)
                self.assertEqual(service.requests,0)

    def test_expired_and_wrong_eku_client_certificates_fail_tls(self):
        for label,server,expired in [('expired-client',False,True),('server-eku-client',True,False)]:
            material,_=self.certs.leaf(label,server=server,expired=expired)
            with review_server(self.certs,self.runs,self.policy) as (service,endpoint):
                with self.assertRaises(TransportError):self.send(endpoint,material=material)
                self.assertEqual(service.requests,0)

    def test_unknown_ca_and_missing_client_certificate_fail_tls(self):
        other_root=self.root/'foreign';other_root.mkdir();other=TestCertificates(other_root)
        with review_server(self.certs,self.runs,self.policy) as (server,endpoint):
            foreign=TLSFiles(self.certs.ca_file,other.client.certificate_file,other.client.private_key_file)
            with self.assertRaises(TransportError):self.send(endpoint,material=foreign)
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.minimum_version=ssl.TLSVersion.TLSv1_3
            context.load_verify_locations(str(self.certs.ca_file))
            with socket.create_connection(('127.0.0.1',endpoint.port),timeout=2) as raw:
                with self.assertRaises((ssl.SSLError,OSError)):
                    with context.wrap_socket(raw,server_hostname='localhost') as peer:
                        peer.sendall(b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n');peer.recv(1024)
            self.assertEqual(server.requests,0)

    def test_untrusted_server_ca_is_rejected(self):
        other_root=self.root/'foreign';other_root.mkdir();other=TestCertificates(other_root)
        with review_server(other,self.runs,self.policy) as (server,endpoint):
            with self.assertRaises(TransportError):self.send(endpoint)
            self.assertEqual(server.requests,0)

    def test_tls_downgrade_and_unverified_server_context_rejected(self):
        context=server_context(self.certs.server)
        context.minimum_version=ssl.TLSVersion.TLSv1_2;context.maximum_version=ssl.TLSVersion.TLSv1_2
        with review_server(self.certs,self.runs,self.policy,context=context) as (_,endpoint):
            with self.assertRaises(TransportError):self.send(endpoint)
        context=server_context(self.certs.server);context.verify_mode=ssl.CERT_NONE
        with review_server(self.certs,self.runs,self.policy,context=context) as (_,endpoint):
            with patch.object(self.runs,'read',side_effect=AssertionError):
                with self.assertRaises(TransportError):self.send(endpoint)

    def test_pin_rotation_requires_host_policy_update(self):
        material,pin=self.certs.leaf('rotated-client',server=False)
        with review_server(self.certs,self.runs,self.policy) as (server,endpoint):
            with self.assertRaises(TransportError):self.send(endpoint,material=material)
            server.access_policy=AccessPolicy(self.policy.grants|{Grant(pin,self.proposal['incident_id'],self.proposal['run_id'])})
            self.assertEqual(self.send(endpoint,material=material)['decision'],'ACCEPT')
            server.access_policy=AccessPolicy(frozenset({Grant(pin,self.proposal['incident_id'],self.proposal['run_id'])}))
            with self.assertRaises(TransportError):self.send(endpoint)

    def test_request_cannot_supply_policy_endpoint_or_forwarded_identity(self):
        for field in ['policy','endpoint','peer_sha256','authorization']:
            proposal=dict(self.proposal,**{field:'private-value'})
            with patch('socket.socket',side_effect=AssertionError):
                with self.assertRaises(ContractError):review_https(json.dumps(proposal).encode(),
                    endpoint=EgressPolicy('example.invalid',443,'8.8.8.8','a'*64),material=self.certs.client)
        with self.assertRaises(SecurityError):handle_review(object(),encode('proposal',self.proposal),self.runs,self.policy)
        with self.assertRaises(SecurityError):handle_review(object(),encode('proposal',self.proposal),self.runs,{})

    def test_invalid_grants_policies_and_egress_destinations_are_rejected(self):
        for values in [('bad',self.proposal['incident_id'],self.proposal['run_id']),
                       ('a'*64,'not-uuid',self.proposal['run_id']),('a'*64,True,self.proposal['run_id'])]:
            with self.assertRaises(SecurityError):Grant(*values)
        for values in [set(),frozenset({'role-A27'}),frozenset(range(1025))]:
            with self.assertRaises(SecurityError):AccessPolicy(values)
        base=EgressPolicy('example.invalid',443,'8.8.8.8','a'*64)
        for mutation in [{'hostname':'https://example.invalid'},{'hostname':'evil\nheader'},{'hostname':'EXAMPLE.INVALID'},
                         {'port':True},{'port':0},{'port':65536},{'server_sha256':'A'*64},{'path':'//evil'},
                         {'path':'/../admin'},{'path':'/review?endpoint=evil'},{'address':None},{'address':'0.0.0.0'},
                         {'address':'169.254.169.254'},{'address':'224.0.0.1'},{'address':'::ffff:127.0.0.1'},
                         {'address':'127.0.0.1'},{'address':'::'},{'allow_loopback':1},{'address':'fe80::1%eth0'}]:
            with self.subTest(mutation=mutation),self.assertRaises(SecurityError):replace(base,**mutation)
        self.assertEqual(replace(base,address='10.0.0.1').address,'10.0.0.1')

    def test_private_key_config_permissions_repr_and_errors_are_safe(self):
        self.assertNotIn(str(self.root),repr(self.certs.client))
        for material in [None,replace(self.certs.client,ca_file=self.root/'absent'),
                         replace(self.certs.client,private_key_file=self.certs.server.private_key_file),
                         replace(self.certs.client,private_key_file=str(self.certs.client.private_key_file))]:
            with self.assertRaises(SecurityError) as error:client_context(material)
            self.assertNotIn(str(self.root),str(error.exception))
        if os.name=='posix':
            self.certs.client.private_key_file.chmod(0o644)
            with self.assertRaises(SecurityError):client_context(self.certs.client)

    def test_contexts_enforce_tls13_custom_roots_and_certificates(self):
        for context in [client_context(self.certs.client),server_context(self.certs.server)]:
            self.assertEqual(context.minimum_version,ssl.TLSVersion.TLSv1_3)
            self.assertEqual(context.maximum_version,ssl.TLSVersion.TLSv1_3)
            self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
            self.assertTrue(context.verify_flags & ssl.VERIFY_X509_STRICT)
            self.assertFalse(context.hostname_checks_common_name)
            configured=ssl.PEM_cert_to_DER_cert(self.certs.ca_file.read_text())
            self.assertIn(configured,context.get_ca_certs(binary_form=True))

    def test_redirects_encoded_chunked_missing_and_duplicate_lengths_rejected(self):
        replies=[b'HTTP/1.1 302 Found\r\nLocation: https://untrusted.invalid\r\nContent-Length: 0\r\n\r\n',
                 b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 2\r\n\r\n{}',
                 b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n',
                 b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Encoding: gzip\r\nContent-Length: 2\r\n\r\n{}',
                 b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{}',
                 b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}']
        for reply in replies:
            with review_server(self.certs,self.runs,self.policy,response=lambda peer,body:peer.sendall(reply)) as (server,endpoint):
                with self.assertRaises(TransportError):self.send(endpoint)
                self.assertEqual(server.requests,1)

    def test_oversized_truncated_and_invalid_verdicts_are_rejected(self):
        for length,body in [('20000',b'{}'),('5',b'{}'),('2',b'{}'),('-2',b'{}'),('999999',b'{}'),('abc',b'{}')]:
            reply=('HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '+length+'\r\n\r\n').encode()+body
            with review_server(self.certs,self.runs,self.policy,response=lambda peer,data:peer.sendall(reply)) as (_,endpoint):
                with self.assertRaises(TransportError):self.send(endpoint)

    def test_wrong_run_response_cannot_be_accepted(self):
        verdict={'version':'1','run_id':'00000000-0000-0000-0000-000000000000','decision':'ACCEPT','reason':'MATCH',
                 'assessment':'NO_FAILURE_OBSERVED','reviewer':'A27','mode':'deterministic','record_sha256':'a'*64}
        body=encode('verdict',verdict)
        reply=f'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n'.encode()+body
        with review_server(self.certs,self.runs,self.policy,response=lambda peer,data:peer.sendall(reply)) as (_,endpoint):
            with self.assertRaises(TransportError):self.send(endpoint)

    def test_fragmented_response_body_survives_http_handle_close(self):
        def fragmented(peer,payload):
            body=handle_review(peer,payload,self.runs,self.policy)
            peer.sendall(f'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode())
            for chunk in [body[:10],body[10:]]:
                time.sleep(0.01);peer.sendall(chunk)
        with review_server(self.certs,self.runs,self.policy,response=fragmented) as (_,endpoint):
            self.assertEqual(self.send(endpoint)['decision'],'ACCEPT')

    def test_total_network_deadline_limits_trickled_headers(self):
        sent=[]
        def delayed(peer,body):
            for _ in range(100):
                time.sleep(0.02);peer.sendall(b'H');sent.append(1)
        with review_server(self.certs,self.runs,self.policy,response=delayed) as (server,endpoint):
            with self.assertRaises(TransportError):self.send(endpoint,timeout=0.25)
            self.assertEqual(server.requests,1)
        self.assertLess(len(sent),100)

    def test_header_budget_and_invalid_network_configuration_reject(self):
        reply=b'HTTP/1.1 200 OK\r\nX-Large: '+b'x'*(MAX_MESSAGE_BYTES*2)+b'\r\n\r\n'
        with review_server(self.certs,self.runs,self.policy,response=lambda peer,body:peer.sendall(reply)) as (_,endpoint):
            with self.assertRaises(TransportError):self.send(endpoint)
        for timeout in [0,True,float('nan'),11,'5']:
            with self.assertRaises(TransportError):review_https(encode('proposal',self.proposal),endpoint=None,material=self.certs.client,timeout=timeout)
        with self.assertRaises(TimeoutError):_remaining(0)

    def test_connection_failure_is_sanitized(self):
        endpoint=EgressPolicy('example.invalid',443,'8.8.8.8','a'*64)
        with patch('socket.socket',side_effect=OSError('private-path-and-key')):
            with self.assertRaises(TransportError) as error:self.send(endpoint)
        self.assertNotIn('private-path-and-key',str(error.exception))

    def test_missing_peer_certificate_extraction_fails_closed(self):
        with review_server(self.certs,self.runs,self.policy) as (server,endpoint):
            with patch.object(ssl.SSLSocket,'getpeercert',return_value=None):
                with self.assertRaises(TransportError):self.send(endpoint)
            self.assertEqual(server.requests,0)

    def test_encrypted_private_key_never_prompts_for_interactive_password(self):
        from cryptography.hazmat.primitives import serialization
        key=serialization.load_pem_private_key(self.certs.client.private_key_file.read_bytes(),password=None)
        encrypted=self.root/'encrypted.key'
        encrypted.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                                                serialization.BestAvailableEncryption(b'test')))
        encrypted.chmod(0o600)
        with self.assertRaises(SecurityError):client_context(replace(self.certs.client,private_key_file=encrypted))
