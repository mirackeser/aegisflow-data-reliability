# SPDX-License-Identifier: Apache-2.0
"""Verify installed A2A SDK interoperation over an ephemeral mTLS fixture."""
import asyncio
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import aegisflow_dr
from aegisflow_dr.coordination.contracts import encode
from aegisflow_dr.integration.a2a_client import review_a2a
from aegisflow_dr.integration.a2a_profile import ProtocolError
from aegisflow_dr.investigation import default_policy
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.security.policy import AccessPolicy, Grant
from aegisflow_dr.storage import IncidentStore, initialize
from aegisflow_dr.storage.runs import InvestigationRuns

checkout=Path(__file__).resolve().parents[1]
if Path(aegisflow_dr.__file__).resolve().is_relative_to(checkout/'src'):
    raise RuntimeError('Installed A2A check imported the source checkout')
sys.path.insert(0,str(checkout/'tests'))
from tls_support import TestCertificates
from a2a_support import a2a_server, send_endpoint


def main():
    with TemporaryDirectory() as temporary:
        root=Path(temporary);certificates=TestCertificates(root)
        database=root/'evidence.db';initialize(database)
        store=IncidentStore(database);runs=InvestigationRuns(store)
        incident=store.record(generate_orders(),request_key='a2a-smoke')
        saved=runs.execute(incident['incident_id'],default_policy(),request_key='a2a-smoke')
        proposal={'version':'1','incident_id':incident['incident_id'],'run_id':saved['run_id'],
                  'assessment':saved['trace']['assessment'],
                  'evidence_sha256':sorted({saved['trace']['source_sha256'],
                    *(step['report_sha256'] for step in saved['trace']['steps'])})}
        policy=AccessPolicy(frozenset({Grant(certificates.client_pin,incident['incident_id'],saved['run_id'])}))
        before=database.read_bytes()
        with a2a_server(certificates,runs,policy) as (server,endpoint):
            result=asyncio.run(review_a2a(encode('proposal',proposal),endpoint=send_endpoint(endpoint),material=certificates.client))
            if result['decision']!='ACCEPT':raise RuntimeError('Installed A2A acceptance failed')
            proposal['assessment']='SOURCE_QUALITY_FAILURE'
            result=asyncio.run(review_a2a(encode('proposal',proposal),endpoint=send_endpoint(endpoint),material=certificates.client))
            if result['decision']!='REJECT':raise RuntimeError('Installed A2A Judge failed open')
            server.access_policy=AccessPolicy()
            try:asyncio.run(review_a2a(encode('proposal',proposal),endpoint=send_endpoint(endpoint),material=certificates.client))
            except ProtocolError:pass
            else:raise RuntimeError('Installed A2A access failed open')
        if database.read_bytes()!=before:raise RuntimeError('Installed A2A changed evidence history')
    print('Installed official A2A SDK, mutual TLS and read-only review checks passed.')


if __name__=='__main__':main()
