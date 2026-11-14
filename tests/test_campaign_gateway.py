# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from campaign_tls_support import campaign_gateway
from aegisflow_dr.benchmark.campaign import run_campaign, read_campaign
from aegisflow_dr.benchmark.campaign_report import CampaignPolicy


class CampaignGatewayTests(unittest.TestCase):
    def test_complete_campaign_uses_real_pinned_mtls_then_reopens_without_connections(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with campaign_gateway(root) as (build, server):
                with patch('socket.getaddrinfo', side_effect=AssertionError('DNS forbidden')):
                    result = run_campaign(root / 'campaign', CampaignPolicy('fixture/evidence-v1', 'a' * 64),
                                          build, clock_ms=lambda: 1000)
                self.assertEqual(server.requests, 18)
            with patch('socket.socket', side_effect=AssertionError('Replay forbidden')):
                report = read_campaign(root / 'campaign', manifest_sha256=result['manifest_sha256'])
            self.assertEqual(report['quality']['correct'], 18)
            self.assertEqual(report['operational_decision'], 'PASS')
            self.assertEqual(report['quality']['decision'], 'BLOCK')
            self.assertEqual(report['usage']['charged_cost_nusd'], 396)

    def test_signed_wrong_claims_still_fail_independent_judge(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with campaign_gateway(root, wrong_claim=True) as (build, server):
                result = run_campaign(root / 'campaign', CampaignPolicy('fixture/evidence-v1', 'a' * 64),
                                      build, clock_ms=lambda: 1000)
                self.assertEqual(server.requests, 18)
            self.assertEqual(result['report']['quality']['unsupported_claims'], 18)
            self.assertEqual(result['report']['quality']['correct'], 0)
            self.assertEqual(result['report']['operational_decision'], 'BLOCK')

    def test_bad_gateway_signature_halts_campaign_and_retains_full_hold(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with campaign_gateway(root, tamper=True) as (build, server):
                result = run_campaign(root / 'campaign', CampaignPolicy('fixture/evidence-v1', 'a' * 64),
                                      build, clock_ms=lambda: 1000)
                self.assertEqual(server.requests, 1)
            self.assertEqual(result['report']['usage']['held_cost_nusd'], 35)
            self.assertEqual(result['report']['quality']['case_count'], 18)
            self.assertEqual(result['report']['quality']['errors'], 18)
