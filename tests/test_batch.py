# SPDX-License-Identifier: Apache-2.0
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aegisflow_dr.batch import downstream, run_batch
from aegisflow_dr.__main__ import main
from aegisflow_dr.pipeline import InputRejected, MAX_INPUT_BYTES, generate_orders


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


class BatchTests(unittest.TestCase):
    def test_golden_fixture_runs_actual_staging_and_grouping(self):
        payload = Path('fixtures/orders-clean.csv').read_bytes()
        report = run_batch(payload)
        expected_mart = (b'customer_id,order_count,total_cents\n'
                         b'CUS-001,2,1555\nCUS-002,1,2020\n')
        self.assertEqual(report.status, 'PASS')
        self.assertEqual([a.row_count for a in report.artifacts], [3, 3, 2])
        self.assertEqual(report.artifacts[0].sha256, sha(payload))
        self.assertEqual(report.artifacts[2].sha256, sha(expected_mart))
        self.assertEqual([c.actual for c in report.reconciliation], [3, 3575])
        self.assertEqual(report.potential_downstream, ())
        self.assertIsNone(report.affected_dataset)

    def test_artifact_chain_and_sql_version(self):
        report = run_batch(generate_orders())
        source, staging, mart = report.artifacts
        self.assertEqual(staging.upstream_sha256, source.sha256)
        self.assertEqual(mart.upstream_sha256, staging.sha256)
        self.assertEqual(mart.transform_sha256, report.transform_sha256)
        self.assertEqual(report.transform_sha256,
                         sha(Path('src/aegisflow_dr/sql/customer_sales_v1.sql').read_bytes()))
        self.assertTrue(all(c.evidence_sha256 == (staging.sha256, mart.sha256)
                            for c in report.reconciliation))

    def test_filter_regression_identifies_observed_failure_and_potential_consumer(self):
        report = run_batch(Path('fixtures/orders-clean.csv').read_bytes(),
                           transform='exclude_first')
        self.assertEqual(report.status, 'FAIL')
        self.assertEqual([(c.expected, c.actual, c.passed) for c in report.reconciliation],
                         [(3, 2, False), (3575, 2565, False)])
        self.assertEqual(report.affected_dataset, 'customer_sales')
        self.assertEqual(report.potential_downstream, ('sales_dashboard',))

    def test_zero_amount_still_detects_missing_record(self):
        report = run_batch(b'order_id,customer_id,order_total\na,c,0\n',
                           transform='exclude_first')
        self.assertEqual(report.status, 'FAIL')
        self.assertFalse(report.reconciliation[0].passed)
        self.assertTrue(report.reconciliation[1].passed)
        self.assertEqual(report.artifacts[-1].row_count, 0)

    def test_source_faults_block_sql_execution(self):
        for fault in ['schema_drift', 'null_total', 'duplicate_order']:
            with self.subTest(fault=fault), patch('aegisflow_dr.batch.sqlite3.connect') as connect:
                report = run_batch(generate_orders(fault=fault))
                self.assertEqual(report.status, 'BLOCKED')
                self.assertEqual(len(report.artifacts), 1)
                self.assertEqual(report.reconciliation, ())
                self.assertEqual(report.affected_dataset, 'source_orders')
                self.assertEqual(report.potential_downstream,
                                 ('staging_orders', 'customer_sales', 'sales_dashboard'))
                connect.assert_not_called()

    def test_malformed_and_oversize_source_rejected_before_sql(self):
        for payload in [b'\xff', b'x' * (MAX_INPUT_BYTES + 1), b'a,a\n1,2']:
            with self.subTest(size=len(payload)), patch('aegisflow_dr.batch.sqlite3.connect') as connect:
                with self.assertRaises(InputRejected): run_batch(payload)
                connect.assert_not_called()

    def test_normalized_identifiers_exact_cents_and_canonical_stage(self):
        payload = b'order_total,customer_id,order_id\n0.10, customer , a \n0.20,customer,b\n'
        report = run_batch(payload)
        expected_stage = (b'record_number,order_id,customer_id,total_cents\n'
                          b'1,a,customer,10\n2,b,customer,20\n')
        expected_mart = b'customer_id,order_count,total_cents\ncustomer,2,30\n'
        self.assertEqual(report.artifacts[1].sha256, sha(expected_stage))
        self.assertEqual(report.artifacts[2].sha256, sha(expected_mart))
        self.assertEqual(report.reconciliation[1].actual, 30)

    def test_maximum_bounded_amount_fits_exact_sql_aggregation(self):
        payload = (b'order_id,customer_id,order_total\n'
                   b'a,c,999999999999.99\nb,c,999999999999.99\n')
        report = run_batch(payload)
        self.assertEqual(report.status, 'PASS')
        self.assertEqual(report.reconciliation[1].actual, 199999999999998)

    def test_multiline_utf8_customer_and_bom(self):
        payload = '\ufefforder_id,customer_id,order_total\na,"Müşteri\nBir",1.25\n'.encode()
        report = run_batch(payload)
        self.assertEqual(report.status, 'PASS')
        self.assertEqual(report.artifacts[-1].row_count, 1)
        self.assertNotIn('Müşteri', report.to_json())

    def test_identical_input_and_transform_yield_identical_report(self):
        payload = generate_orders(seed=7)
        self.assertEqual(run_batch(payload).to_json(), run_batch(payload).to_json())
        clean = run_batch(payload)
        fault = run_batch(payload, transform='exclude_first')
        self.assertNotEqual(clean.transform_sha256, fault.transform_sha256)
        self.assertEqual(clean.artifacts[1], fault.artifacts[1])

    def test_fixed_dag_transitive_impact(self):
        self.assertEqual(downstream('source_orders'),
                         ('staging_orders', 'customer_sales', 'sales_dashboard'))
        self.assertEqual(downstream('staging_orders'), ('customer_sales', 'sales_dashboard'))
        self.assertEqual(downstream('sales_dashboard'), ())
        with self.assertRaises(ValueError): downstream('not-a-dataset')

    def test_unknown_transform_cannot_supply_sql(self):
        with self.assertRaises(ValueError):
            run_batch(generate_orders(), transform='DROP TABLE staging_orders')

    def test_report_hides_raw_identifiers_and_exposes_json_contract(self):
        report = run_batch(b'order_id,customer_id,order_total\nprivate-order,private-customer,1.25\n')
        encoded = report.to_json()
        self.assertNotIn('private-order', encoded)
        self.assertNotIn('private-customer', encoded)
        self.assertEqual(json.loads(encoded)['engine'], 'sqlite-memory-batch-v1')

    def test_cli_pass_fail_blocked_and_rejected_outcomes(self):
        for args, code, status in [([], 0, 'PASS'),
                                  (['--transform', 'exclude_first'], 1, 'FAIL'),
                                  (['--fault', 'schema_drift'], 1, 'BLOCKED'),
                                  (['--rows', '0'], 2, None)]:
            with self.subTest(args=args):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(main(['batch-demo', *args]), code)
                if status: self.assertEqual(json.loads(out.getvalue())['status'], status)
                else: self.assertEqual(out.getvalue(), '')

    def test_balanced_misattribution_is_outside_reconciliation_coverage(self):
        # Counts and totals alone cannot validate customer attribution.
        sql = (b"SELECT 'wrong-customer', COUNT(*), SUM(total_cents) "
               b"FROM staging_orders")
        with patch('aegisflow_dr.batch.files') as resource:
            resource.return_value.joinpath.return_value.read_bytes.return_value = sql
            report = run_batch(b'order_id,customer_id,order_total\na,real-customer,1.25\n')
        self.assertEqual(report.status, 'PASS')
        self.assertEqual(report.artifacts[-1].sha256,
                         sha(b'customer_id,order_count,total_cents\nwrong-customer,1,125\n'))
