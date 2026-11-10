# SPDX-License-Identifier: Apache-2.0
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aegisflow_dr.__main__ import main
from aegisflow_dr.pipeline import (
    InputRejected, MAX_INPUT_BYTES, MAX_ROWS, diagnose_csv, generate_orders,
)


class DiagnosticTests(unittest.TestCase):
    def test_clean_csv_uses_exact_decimal_arithmetic(self):
        payload = b'order_id,customer_id,order_total\na,c,0.10\nb,c,0.20\n'
        report = diagnose_csv(payload)
        self.assertEqual((report.status, report.row_count, report.total_valid_amount),
                         ('PASS', 2, '0.30'))
        self.assertEqual(report.source_sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(report.source_bytes, len(payload))

    def test_golden_fixture(self):
        report = diagnose_csv(Path('fixtures/orders-clean.csv').read_bytes())
        self.assertEqual((report.status, report.row_count, report.total_valid_amount),
                         ('PASS', 3, '35.75'))

    def test_fault_scenarios_find_expected_violations(self):
        for fault, checks in [
            ('schema_drift', {'missing_column', 'unexpected_column'}),
            ('null_total', {'not_null'}),
            ('duplicate_order', {'unique'}),
        ]:
            with self.subTest(fault=fault):
                report = diagnose_csv(generate_orders(fault=fault))
                self.assertEqual(report.status, 'FAIL')
                self.assertEqual({f.check for f in report.findings}, checks)
                self.assertIsNone(report.total_valid_amount)

    def test_reproducible_generation_and_reports(self):
        a = generate_orders(seed=7)
        self.assertEqual(a, generate_orders(seed=7))
        self.assertNotEqual(a, generate_orders(seed=8))
        self.assertEqual(diagnose_csv(a).to_json(), diagnose_csv(a).to_json())

    def test_duplicate_evidence_uses_logical_records_and_hides_values(self):
        payload = b'order_id,customer_id,order_total\nsecret,"multi\nline",1.00\n secret ,c,2.00\n'
        report = diagnose_csv(payload)
        self.assertEqual(report.findings[0].record_numbers, (1, 2))
        self.assertNotIn('secret', report.to_json())
        self.assertNotIn('multi\\nline', report.to_json())

    def test_column_order_and_utf8_bom_are_supported(self):
        report = diagnose_csv(b'\xef\xbb\xbforder_total,order_id,customer_id\n1.25,a,c\n')
        self.assertEqual(report.total_valid_amount, '1.25')

    def test_invalid_amounts_are_never_silently_rounded(self):
        for value in ['NaN', 'Infinity', '1e99999999', '-1', '0.001', '1,00', '1234567890123']:
            with self.subTest(value=value):
                payload = f'order_id,customer_id,order_total\na,c,"{value}"\n'.encode()
                report = diagnose_csv(payload)
                self.assertEqual(report.findings[0].check, 'amount_format')
                self.assertIsNone(report.total_valid_amount)

    def test_required_values_cannot_be_whitespace(self):
        report = diagnose_csv(b'order_id,customer_id,order_total\n ,c, \n')
        self.assertEqual({f.column for f in report.findings}, {'order_id', 'order_total'})

    def test_header_only_is_a_quality_failure(self):
        report = diagnose_csv(b'order_id,customer_id,order_total\n')
        self.assertEqual(report.findings[0].check, 'nonempty_dataset')

    def test_ambiguous_and_malformed_inputs_are_rejected(self):
        for payload in [b'', b'a,a\n1,2', b',b\n1,2', b'\xff', b'a\n\x00',
                        b'order_id,customer_id,order_total\na,c\n',
                        b'order_id,customer_id,order_total\n"unterminated']:
            with self.subTest(payload=payload):
                with self.assertRaises(InputRejected):
                    diagnose_csv(payload)

    def test_byte_budget(self):
        with self.assertRaises(InputRejected):
            diagnose_csv(b'x' * (MAX_INPUT_BYTES + 1))

    def test_record_budget(self):
        payload = b'order_id,customer_id,order_total\n' + b'a,c,1\n' * (MAX_ROWS + 1)
        with self.assertRaises(InputRejected):
            diagnose_csv(payload)

    def test_report_budget_keeps_count_and_explicit_truncation(self):
        payload = b'order_id,customer_id,order_total\n' + b',,\n' * 101
        report = diagnose_csv(payload)
        self.assertEqual(report.finding_count, 303)
        self.assertEqual(len(report.findings), 100)
        self.assertTrue(report.findings_truncated)
        self.assertEqual(report.status, 'FAIL')

    def test_digest_covers_source_bytes_not_normalized_data(self):
        a = b'order_id,customer_id,order_total\na,c,1\n'
        b = a.replace(b'\n', b'\r\n')
        self.assertNotEqual(diagnose_csv(a).source_sha256, diagnose_csv(b).source_sha256)

    def test_generator_rejects_invalid_options(self):
        for options in [{'rows': 0}, {'rows': True}, {'rows': MAX_ROWS + 1},
                        {'seed': 'a'}, {'fault': 'unknown'},
                        {'fault': 'duplicate_order', 'rows': 1}]:
            with self.subTest(options=options):
                with self.assertRaises(ValueError): generate_orders(**options)


class CLITests(unittest.TestCase):
    def invoke(self, arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(arguments)
        return code, out.getvalue(), err.getvalue()

    def test_demo_exit_codes_and_machine_readable_output(self):
        for fault in ['clean', 'schema_drift', 'null_total', 'duplicate_order']:
            with self.subTest(fault=fault):
                code, out, err = self.invoke(['demo', '--fault', fault])
                self.assertEqual(code, 0 if fault == 'clean' else 1)
                self.assertEqual(json.loads(out)['status'], 'PASS' if code == 0 else 'FAIL')
                self.assertEqual(err, '')

    def test_missing_file_is_rejected_without_path_disclosure(self):
        code, out, err = self.invoke(['inspect', '/not-present/private-name.csv'])
        self.assertEqual(code, 2)
        self.assertEqual(out, '')
        self.assertNotIn('private-name', err)

    def test_file_inspection(self):
        code, out, _ = self.invoke(['inspect', 'fixtures/orders-clean.csv'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['total_valid_amount'], '35.75')

    def test_catalog_default_is_backward_compatible(self):
        code, out, _ = self.invoke([])
        self.assertEqual(code, 0)
        self.assertIn('36 planned specialist roles', out)

    def test_invalid_demo_options_are_rejected(self):
        code, out, err = self.invoke(['demo', '--rows', '0'])
        self.assertEqual(code, 2)
        self.assertEqual(out, '')
        self.assertIn('Input rejected', err)
