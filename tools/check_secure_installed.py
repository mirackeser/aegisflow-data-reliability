# SPDX-License-Identifier: Apache-2.0
"""Verify installed TLS boundaries with ephemeral loopback certificates only."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

import aegisflow_dr
from aegisflow_dr.coordination.contracts import encode
from aegisflow_dr.integration.secure_review import TransportError, review_https
from aegisflow_dr.security.policy import AccessPolicy, Grant
from aegisflow_dr.storage import IncidentStore, initialize
from aegisflow_dr.storage.runs import InvestigationRuns
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.investigation import default_policy

checkout = Path(__file__).resolve().parents[1]
if Path(aegisflow_dr.__file__).resolve().is_relative_to(checkout / 'src'):
    raise RuntimeError('Installed TLS check imported the source checkout')
# Fixture code creates temporary certificates; it never adds the source package to sys.path.
sys.path.insert(0, str(checkout / 'tests'))
from tls_support import TestCertificates, review_server


def main():
    with TemporaryDirectory() as temporary:
        root=Path(temporary)
        certificates=TestCertificates(root)
        database=root/'evidence.db';initialize(database)
        store=IncidentStore(database);runs=InvestigationRuns(store)
        incident=store.record(generate_orders(),request_key='tls-smoke')
        record=runs.execute(incident['incident_id'],default_policy(),request_key='tls-smoke')
        proposal={'version':'1','run_id':record['run_id'],'incident_id':incident['incident_id'],
                  'assessment':record['trace']['assessment'],
                  'evidence_sha256':sorted({record['trace']['source_sha256'],
                    *(s['report_sha256'] for s in record['trace']['steps'])})}
        policy=AccessPolicy(frozenset({Grant(certificates.client_pin,incident['incident_id'],record['run_id'])}))
        before=database.read_bytes()
        with review_server(certificates,runs,policy) as (server,endpoint):
            result=review_https(encode('proposal',proposal),endpoint=endpoint,material=certificates.client)
            if result['decision']!='ACCEPT':
                raise RuntimeError('Installed TLS acceptance check failed')
            server.access_policy=AccessPolicy()
            try:
                review_https(encode('proposal',proposal),endpoint=endpoint,material=certificates.client)
            except TransportError:
                pass
            else:
                raise RuntimeError('Installed TLS authorization failed open')
        if database.read_bytes()!=before:
            raise RuntimeError('Installed TLS review changed evidence history')
    print('Installed mTLS review acceptance, authorization denial and read-only evidence checks passed.')


if __name__=='__main__':
    main()
