# SPDX-License-Identifier: Apache-2.0
"""Qualify an isolated local PostgreSQL source without contacting existing servers."""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.investigation import default_policy
from aegisflow_dr.storage import IncidentStore, initialize
from aegisflow_dr.storage.runs import InvestigationRuns


def qualify(bindir):
    bindir = Path(bindir).resolve()
    def process(name, arguments, payload=None, allowed_failure=False):
        result = subprocess.run([str(bindir / name), *arguments], input=payload,
            capture_output=True, timeout=30, env={k: v for k, v in os.environ.items()
            if not k.startswith('PG')})
        if result.returncode and not allowed_failure:
            raise RuntimeError('Local PostgreSQL qualification command failed')
        return result
    with TemporaryDirectory(prefix='aegis-pg-') as temporary:
        root = Path(temporary)
        cluster, socket = root / 'cluster', root / 'socket'
        socket.mkdir(mode=0o700)
        process('initdb', ['-D', str(cluster), '-U', 'fixture_owner', '--auth=trust', '--no-locale', '-E', 'UTF8'])
        process('pg_ctl', ['-D', str(cluster), '-l', str(root / 'server.log'), '-o',
            f"-k {socket} -c listen_addresses='' -c unix_socket_permissions=0700", '-w', 'start'])
        try:
            def sql(statement, reader=False, fail=False):
                return process('psql', ['-X', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1',
                    '-h', str(socket), '-U', 'fixture_reader' if reader else 'fixture_owner',
                    '-d', 'postgres', '-c', statement], allowed_failure=fail)
            sql("CREATE ROLE fixture_reader LOGIN; CREATE TABLE orders (order_id text, customer_id text, order_total text); GRANT SELECT ON orders TO fixture_reader;")
            results = []
            for fault in ('clean', 'null_total', 'duplicate_order'):
                sql('TRUNCATE orders')
                raw = generate_orders(fault=fault)
                process('psql', ['-X', '-q', '-v', 'ON_ERROR_STOP=1', '-h', str(socket),
                    '-U', 'fixture_owner', '-d', 'postgres', '-c',
                    'COPY orders FROM STDIN WITH (FORMAT CSV, HEADER TRUE)'], raw)
                selected = sql("COPY (SELECT order_id,customer_id,order_total FROM orders ORDER BY order_id,customer_id,order_total) TO STDOUT WITH (FORMAT CSV, HEADER TRUE)", reader=True).stdout
                if len(selected) > 1000000 or len(list(csv.reader(io.StringIO(selected.decode())))) != 25:
                    raise RuntimeError('Unexpected fixture export bounds')
                evidence = root / (fault + '.db')
                initialize(evidence)
                store = IncidentStore(evidence)
                source = store.record(selected, request_key=fault)
                record = InvestigationRuns(store).execute(source['incident_id'], default_policy(), request_key=fault)
                expected = 'NO_FAILURE_OBSERVED' if fault == 'clean' else 'SOURCE_QUALITY_FAILURE'
                if record['trace']['assessment'] != expected:
                    raise RuntimeError('PostgreSQL evidence assessment mismatch')
                results.append({'case': fault, 'assessment': expected, 'rows': 24})
            # Permissions must reject writes even outside a READ ONLY transaction.
            for statement in ('DELETE FROM orders', "INSERT INTO orders VALUES ('x','y','1')", 'DROP TABLE orders'):
                if sql(statement, reader=True, fail=True).returncode == 0:
                    raise RuntimeError('Reader unexpectedly acquired write authority')
            if sql('SELECT count(*) FROM orders', reader=True).stdout.strip() != b'24':
                raise RuntimeError('Denied writes changed source data')
            return {'status': 'PASS', 'source': 'isolated-local-postgresql', 'cases': results,
                    'write_denials': 3, 'live_model_calls': 0, 'existing_servers_accessed': False}
        finally:
            process('pg_ctl', ['-D', str(cluster), '-m', 'immediate', '-w', 'stop'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bindir', required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.bindir), sort_keys=True))
