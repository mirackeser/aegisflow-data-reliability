# SPDX-License-Identifier: Apache-2.0
"""Installed campaign integration through real ephemeral mTLS, with retained readback."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import aegisflow_dr
from aegisflow_dr.benchmark.campaign import run_campaign, read_campaign
from aegisflow_dr.benchmark.campaign_report import CampaignPolicy

checkout = Path(__file__).resolve().parents[1]
if Path(aegisflow_dr.__file__).resolve().is_relative_to(checkout / 'src'):
    raise RuntimeError('Campaign check imported source checkout')
sys.path.insert(0, str(checkout / 'tests'))
from campaign_tls_support import campaign_gateway

with TemporaryDirectory() as directory:
    root = Path(directory)
    with campaign_gateway(root) as (build, server):
        result = run_campaign(root / 'campaign', CampaignPolicy('fixture/evidence-v1', 'a' * 64),
                              build, clock_ms=lambda: 1000)
        if server.requests != 18:
            raise RuntimeError('Installed campaign did not execute every public case')
    report = read_campaign(root / 'campaign', manifest_sha256=result['manifest_sha256'])
    if (report['operational_decision'] != 'PASS' or report['quality']['correct'] != 18 or
            report['quality']['decision'] != 'BLOCK' or report['usage']['charged_cost_nusd'] != 396):
        raise RuntimeError('Installed campaign accounting or quality boundary failed')
print('Installed retained campaign, pinned mTLS, independent Judge and conservative quality gate passed.')
