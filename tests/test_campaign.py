# SPDX-License-Identifier: Apache-2.0
from dataclasses import asdict, replace
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from hashlib import sha256
import json
import runpy
import sqlite3
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from aegisflow_dr.advisory.contracts import AdvisoryError, decode, encode
from aegisflow_dr.advisory.dispatch import Adapter, AdapterFailure, AdapterResult
from aegisflow_dr.benchmark.campaign import read_campaign, run_campaign, _quality_cases
from aegisflow_dr.benchmark.campaign_cli import fixture_adapter, main
from aegisflow_dr.benchmark.campaign_report import CampaignPolicy, summarize
from aegisflow_dr.benchmark.campaign_store import read, seal, verified_artifacts, write
from aegisflow_dr.benchmark.core import BenchmarkError, canonical, load_suite, parse


class CampaignTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.policy = CampaignPolicy('fixture/evidence-v1', 'a' * 64)
        self.suite = load_suite()[0]

    def run_campaign(self, name='campaign', factory=fixture_adapter, **options):
        return run_campaign(self.root / name, options.pop('policy', self.policy), factory,
                            clock_ms=lambda: 1000, clock_ns=options.pop('clock_ns', lambda: 0), **options)

    def records(self, name='campaign'):
        return [parse(p.read_bytes()) for p in sorted((self.root / name).glob('case-*.json'))]

    def summary(self, records, **options):
        return summarize(self.suite, records, asdict(self.policy),
            (self.root / 'campaign/protocol.json').read_bytes(), _quality_cases(self.suite), **options)

    def test_full_pipeline_retained_report_labels_never_sent_and_no_network(self):
        seen = []
        def build(prepared, operation):
            value = parse(prepared.messages[1]['content'].encode())
            self.assertNotIn('expected_assessment', json.dumps(value))
            self.assertNotIn('case_id', json.dumps(value))
            seen.append(value)
            return fixture_adapter(prepared, operation)
        with patch('socket.socket', side_effect=AssertionError('Network forbidden')):
            result = self.run_campaign(factory=build)
        report = result['report']
        self.assertEqual(len(seen), 18)
        self.assertEqual(report['adapter_invocations'], 18)
        self.assertEqual(report['operational_decision'], 'PASS')
        self.assertEqual(report['quality']['correct'], 18)
        self.assertEqual(report['quality']['decision'], 'BLOCK')
        self.assertIn('PROVENANCE_NOT_APPROVED', report['quality']['reasons'])
        self.assertFalse(report['live_activation_authorized'])
        self.assertEqual(report['usage'], {'held_tokens': 0, 'charged_tokens': 180,
            'held_cost_nusd': 0, 'charged_cost_nusd': 396})
        root = self.root / 'campaign'
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in root.iterdir()))

    def test_read_is_historical_readonly_and_existing_path_never_resends(self):
        result = self.run_campaign()
        root = self.root / 'campaign'
        before = {p.name: p.read_bytes() for p in root.iterdir()}
        with patch('socket.socket', side_effect=AssertionError('Network forbidden')):
            self.assertEqual(read_campaign(root, manifest_sha256=result['manifest_sha256']), result['report'])
        with self.assertRaises(FileExistsError):
            self.run_campaign(factory=lambda *_: self.fail('Must not resend'))
        self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_wrong_claim_is_raw_error_not_counted_as_correct_by_judge(self):
        def build(prepared, operation):
            quote, adapter = fixture_adapter(prepared, operation)
            def send(request):
                result = adapter.send(request)
                value = decode('response', result.payload)
                value['assessment'] = ('SOURCE_QUALITY_FAILURE' if value['assessment'] == 'NO_FAILURE_OBSERVED'
                                       else 'NO_FAILURE_OBSERVED')
                return replace(result, payload=encode('response', value))
            return quote, Adapter(quote.adapter_id, send)
        report = self.run_campaign(factory=build)['report']
        self.assertEqual(report['quality']['correct'], 0)
        self.assertEqual(report['quality']['unsupported_claims'], 18)
        self.assertEqual({p['prediction'] for p in report['accepted_predictions']}, {'ABSTAIN'})
        self.assertEqual(report['operational_decision'], 'BLOCK')

    def test_abstentions_and_malformed_responses_are_retained_without_raw_text(self):
        def build(prepared, operation):
            quote, _ = fixture_adapter(prepared, operation)
            def send(request):
                return AdapterResult(encode('response', {'version': '1', 'request_sha256': request.request_sha256,
                    'decision': 'ABSTAIN', 'assessment': None, 'evidence_sha256': []}), 8, 2)
            return quote, Adapter(quote.adapter_id, send)
        self.assertEqual(self.run_campaign(factory=build)['report']['quality']['abstentions'], 18)
        def invalid(prepared, operation):
            quote, _ = fixture_adapter(prepared, operation)
            return quote, Adapter(quote.adapter_id, lambda _: AdapterResult(b'private-invalid-response', 8, 2))
        result = self.run_campaign('invalid', invalid)
        self.assertEqual(result['report']['quality']['errors'], 18)
        self.assertTrue(all(b'private-invalid-response' not in p.read_bytes() for p in (self.root / 'invalid').iterdir()))

    def test_unknown_usage_halts_remaining_cases_preserves_hold_and_denominator(self):
        def build(prepared, operation):
            quote, _ = fixture_adapter(prepared, operation)
            def timeout(_):
                raise TimeoutError('private-network-detail')
            return quote, Adapter(quote.adapter_id, timeout)
        report = self.run_campaign(factory=build)['report']
        self.assertEqual(report['adapter_invocations'], 1)
        self.assertEqual(report['quality']['case_count'], 18)
        self.assertEqual(report['quality']['errors'], 18)
        self.assertEqual(report['usage']['held_cost_nusd'], 35)
        self.assertEqual([r['status'] for r in self.records()], ['USAGE_UNKNOWN'] + ['NOT_RUN'] * 17)
        self.assertIn('UNRESOLVED_USAGE', report['operational_reasons'])

    def test_shared_campaign_cost_and_token_budgets_do_not_reset_per_case(self):
        for name, policy, expected_calls in (
                ('cost', replace(self.policy, max_cost_nusd=35), 1),
                ('tokens', replace(self.policy, max_tokens=15), 1),
                ('exact', replace(self.policy, max_tokens=10, max_cost_nusd=22), 0)):
            report = self.run_campaign(name, policy=policy)['report']
            self.assertEqual(report['adapter_invocations'], expected_calls)
            self.assertLessEqual(report['usage']['charged_cost_nusd'], policy.max_cost_nusd)
        # Known exact-cost settlement stops later cases before constructing an adapter.
        def known(prepared, operation):
            quote, _ = fixture_adapter(prepared, operation)
            return replace(quote, input_tokens=8, output_limit=2), Adapter(quote.adapter_id, lambda _: AdapterFailure('TERMINAL', 8, 2))
        report = self.run_campaign('exact-settlement', known, policy=replace(self.policy, max_cost_nusd=22))['report']
        self.assertEqual(report['adapter_invocations'], 1)
        self.assertEqual(self.records('exact-settlement')[1]['status'], 'NOT_RUN')

    def test_latency_limit_is_independent_of_dispatch_deadline(self):
        tick = [0]
        def clock():
            tick[0] += 2000000
            return tick[0]
        report = self.run_campaign(clock_ns=clock, policy=replace(self.policy, max_case_latency_ms=1))['report']
        self.assertEqual(report['quality']['correct'], 18)
        self.assertTrue(any(reason.startswith('LATENCY_LIMIT:') for reason in report['operational_reasons']))
        self.assertGreater(report['latency_ms']['p95_nearest_rank'], 1)

    def test_crash_keeps_completed_cases_and_started_ledger_without_seal(self):
        built = [0]
        def build(prepared, operation):
            built[0] += 1
            quote, adapter = fixture_adapter(prepared, operation)
            if built[0] == 2:
                def crash(_):
                    raise KeyboardInterrupt()
                adapter = Adapter(quote.adapter_id, crash)
            return quote, adapter
        with self.assertRaises(KeyboardInterrupt):
            self.run_campaign(factory=build)
        root = self.root / 'campaign'
        self.assertTrue((root / 'case-000.json').is_file())
        self.assertTrue((root / 'usage-001.db').is_file())
        self.assertFalse((root / 'manifest.json').exists())
        with self.assertRaises(BenchmarkError):
            read_campaign(root, manifest_sha256='a' * 64)
        with self.assertRaises(FileExistsError):
            self.run_campaign()

    def test_actual_process_exit_keeps_inflight_hold_and_never_publishes_complete_report(self):
        script = '''
import os, sys
from aegisflow_dr.benchmark.campaign import run_campaign
from aegisflow_dr.benchmark.campaign_report import CampaignPolicy
from aegisflow_dr.benchmark.campaign_cli import fixture_adapter
from aegisflow_dr.advisory.dispatch import Adapter
count = 0
def build(prepared, operation):
    global count
    count += 1
    quote, adapter = fixture_adapter(prepared, operation)
    if count == 2:
        adapter = Adapter(quote.adapter_id, lambda _: os._exit(37))
    return quote, adapter
run_campaign(sys.argv[1], CampaignPolicy('fixture/evidence-v1', 'a' * 64), build, clock_ms=lambda: 1000)
'''
        path = self.root / 'terminated'
        result = subprocess.run([sys.executable, '-c', script, str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertTrue((path / 'case-000.json').is_file())
        self.assertFalse((path / 'manifest.json').exists())
        with closing(sqlite3.connect(path / 'usage-001.db')) as db:
            self.assertEqual(db.execute('SELECT status,reserved_cost_nusd,charged_cost_nusd FROM attempts').fetchall(),
                             [('IN_FLIGHT', 35, 0)])
        with self.assertRaises(FileExistsError):
            run_campaign(path, self.policy, lambda *_: self.fail('Crash must not trigger redispatch'))

    def test_concurrent_launch_has_one_owner_and_no_duplicate_calls(self):
        count = []
        def build(prepared, operation):
            count.append(1)
            return fixture_adapter(prepared, operation)
        def launch():
            try:
                return self.run_campaign(factory=build)['report']['operational_decision']
            except FileExistsError:
                return 'EXISTING'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: launch(), range(2)))
        self.assertCountEqual(results, ['PASS', 'EXISTING'])
        self.assertEqual(len(count), 18)

    def test_mismatched_quote_rejects_before_any_adapter_call(self):
        def build(prepared, operation):
            quote, adapter = fixture_adapter(prepared, operation)
            return replace(quote, input_sha256='0' * 64), Adapter(adapter.revision, lambda _: self.fail('Quote rejected too late'))
        with self.assertRaises(AdvisoryError):
            self.run_campaign(factory=build)
        self.assertFalse((self.root / 'campaign/manifest.json').exists())

    def test_config_factories_and_nonmonotonic_clocks_rejected(self):
        for changes in ({'max_tokens': True}, {'max_tokens': 1.0}, {'max_cost_nusd': -1},
                        {'model_revision_sha256': 'bad'}, {'case_timeout_ms': 0}):
            with self.assertRaises(BenchmarkError):
                replace(self.policy, **changes)
        for args in (({}, fixture_adapter, {}), (self.policy, None, {}),
                     (self.policy, fixture_adapter, {'clock_ns': None}),
                     (self.policy, fixture_adapter, {'clock_ms': False})):
            with self.assertRaises(BenchmarkError):
                run_campaign(self.root / 'bad', *args[:2], **args[2])
        def bad(prepared, operation):
            quote, _ = fixture_adapter(prepared, operation)
            return quote, None
        with self.assertRaises(BenchmarkError):
            self.run_campaign('bad-adapter', bad)
        with self.assertRaises(AdvisoryError):
            self.run_campaign('bad-clock', clock_ns=lambda: -1)

    def test_corrupt_missing_extra_and_symlinked_artifacts_rejected(self):
        result = self.run_campaign()
        root = self.root / 'campaign'
        digest = result['manifest_sha256']
        path = root / 'case-000.json'
        original = path.read_bytes()
        path.write_bytes(b'{}')
        with self.assertRaises(BenchmarkError):
            read_campaign(root, manifest_sha256=digest)
        path.unlink()
        with self.assertRaises(BenchmarkError):
            read_campaign(root, manifest_sha256=digest)
        outside = self.root / 'outside.json'
        outside.write_bytes(original)
        path.symlink_to(outside)
        with self.assertRaises(BenchmarkError):
            read_campaign(root, manifest_sha256=digest)
        path.unlink()
        path.write_bytes(original)
        with self.assertRaises(BenchmarkError):
            read_campaign(root, manifest_sha256='b' * 64)
        (root / 'extra').write_text('unexpected')
        with self.assertRaises(BenchmarkError):
            read_campaign(root, manifest_sha256=digest)
        link = self.root / 'link'
        link.symlink_to(root)
        with self.assertRaises(BenchmarkError):
            read_campaign(link, manifest_sha256=digest)

    def test_report_is_recomputed_even_if_digest_is_reissued(self):
        self.run_campaign()
        root = self.root / 'campaign'
        report = parse((root / 'report.json').read_bytes())
        report['quality']['correct'] = 999
        (root / 'report.json').write_bytes(canonical(report))
        (root / 'manifest.json').unlink()
        digest = seal(root)
        with self.assertRaisesRegex(BenchmarkError, 'differs'):
            read_campaign(root, manifest_sha256=digest)

    def test_record_coverage_and_aggregate_budget_checks(self):
        self.run_campaign()
        records = self.records()
        with self.assertRaises(BenchmarkError):
            self.summary(records[:-1])
        with self.assertRaises(BenchmarkError):
            self.summary(list(reversed(records)))
        records[0]['elapsed_ms'] = 1.0
        with self.assertRaises(BenchmarkError):
            self.summary(records)
        records[0]['elapsed_ms'] = 0
        records[0]['usage']['charged_cost_nusd'] = self.policy.max_cost_nusd + 1
        with self.assertRaises(BenchmarkError):
            self.summary(records)

    def test_wrong_request_is_not_scored_as_valid_response(self):
        def build(prepared, operation):
            quote, adapter = fixture_adapter(prepared, operation)
            def send(request):
                result = adapter.send(request)
                response = decode('response', result.payload)
                response['request_sha256'] = '0' * 64
                return replace(result, payload=encode('response', response))
            return quote, Adapter(quote.adapter_id, send)
        report = self.run_campaign(factory=build)['report']
        self.assertEqual(report['quality']['errors'], 18)
        self.assertEqual(report['quality']['unsupported_claims'], 18)

    def test_reader_rejects_changed_suite_and_path_traversal(self):
        self.run_campaign()
        root = self.root / 'campaign'
        config = parse((root / 'config.json').read_bytes())
        config['suite_sha256'] = '0' * 64
        (root / 'config.json').write_bytes(canonical(config))
        (root / 'manifest.json').unlink()
        digest = seal(root)
        with self.assertRaisesRegex(BenchmarkError, 'suite changed'):
            read_campaign(root, manifest_sha256=digest)
        raw = canonical({'version': '1', 'artifacts': {'../outside': 'a' * 64}})
        (root / 'manifest.json').write_bytes(raw)
        with self.assertRaises(BenchmarkError):
            verified_artifacts(root, sha256(raw).hexdigest())

    def test_artifact_limits_and_exclusive_write(self):
        path = self.root / 'file'
        write(path, b'123')
        with self.assertRaises(FileExistsError):
            write(path, b'changed')
        with self.assertRaises(BenchmarkError):
            read(path, 2)
        with patch.object(Path, 'stat') as stat:
            stat.return_value.st_size = 1
            stat.return_value.st_mode = 0o100600
            with self.assertRaisesRegex(BenchmarkError, 'exceeds'):
                read(path, 2)

    def test_frozen_public_protocol_and_aggregate_artifact_cap_cannot_be_bypassed(self):
        result = self.run_campaign()
        root = self.root / 'campaign'
        with patch('aegisflow_dr.benchmark.campaign_store.MAX_TOTAL', 1):
            with self.assertRaisesRegex(BenchmarkError, 'total size'):
                read_campaign(root, manifest_sha256=result['manifest_sha256'])
        value = parse((root / 'protocol.json').read_bytes())
        value['sealed'] = True
        (root / 'protocol.json').write_bytes(canonical(value))
        (root / 'manifest.json').unlink()
        digest = seal(root)
        with self.assertRaisesRegex(BenchmarkError, 'profile changed'):
            read_campaign(root, manifest_sha256=digest)

    def test_cli_writes_and_reads_an_installed_style_result_and_sanitizes_errors(self):
        with patch('builtins.print') as output:
            self.assertEqual(main(['run-fixture', str(self.root / 'cli')]), 0)
            value = json.loads(output.call_args.args[0])
            self.assertEqual(main(['read', str(self.root / 'cli'), '--manifest-sha256', value['manifest_sha256']]), 0)
            self.assertEqual(main(['run-fixture', str(self.root / 'cli')]), 1)
            self.assertNotIn(str(self.root), output.call_args.args[0])
        command = subprocess.run([sys.executable, '-m', 'aegisflow_dr.benchmark.campaign_cli', 'read',
            str(self.root / 'cli'), '--manifest-sha256', value['manifest_sha256']], capture_output=True, text=True)
        self.assertEqual(command.returncode, 0, command.stderr)
        self.assertEqual(json.loads(command.stdout)['adapter_invocations'], 18)
        with patch.object(sys, 'argv', ['campaign', 'read', str(self.root / 'missing'), '--manifest-sha256', 'a' * 64]), patch('builtins.print'), patch.dict(sys.modules):
            sys.modules.pop('aegisflow_dr.benchmark.campaign_cli', None)
            with self.assertRaises(SystemExit) as caught:
                runpy.run_module('aegisflow_dr.benchmark.campaign_cli', run_name='__main__')
        self.assertEqual(caught.exception.code, 1)
