# SPDX-License-Identifier: Apache-2.0
"""Local synthetic campaign command; no network, credentials or model provider."""
import argparse

from .campaign import read_campaign, run_campaign
from .campaign_report import CampaignPolicy
from .core import canonical, parse
from ..advisory.contracts import encode
from ..advisory.dispatch import Adapter, AdapterResult
from ..advisory.usage import UsageQuote
from ..storage.store import sha


def fixture_adapter(prepared, operation):
    """Derive a fixture response from diagnostic summaries, never from suite labels."""
    def send(request):
        user = parse(parse(request.messages)[1]['content'].encode())
        summaries = user['evidence']['summaries']
        source = next(s for s in summaries if s['kind'] == 'source')
        if source['status'] == 'FAIL':
            label = 'SOURCE_QUALITY_FAILURE'
        else:
            batch = next(s for s in summaries if s['kind'] == 'reconciliation')
            label = ('NO_FAILURE_OBSERVED' if batch['status'] == 'PASS'
                     else 'TRANSFORMATION_RECONCILIATION_FAILURE')
        return AdapterResult(encode('response', {'version': '1', 'request_sha256': request.request_sha256,
            'decision': 'PROPOSE', 'assessment': label, 'evidence_sha256': user['request']['evidence_sha256']}), 8, 2)
    return (UsageQuote(prepared.manifest['input_sha256'], 'fixture/evidence-v1', 'fixture-v1', 10, 5, 2, 3),
            Adapter('fixture-v1', send))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run-fixture')
    run.add_argument('directory')
    read = commands.add_parser('read')
    read.add_argument('directory')
    read.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'run-fixture':
            result = run_campaign(args.directory, CampaignPolicy('fixture/evidence-v1',
                sha(b'public-evidence-fixture-v1')), fixture_adapter)
        else:
            result = read_campaign(args.directory, manifest_sha256=args.manifest_sha256)
    except (ValueError, OSError, KeyError):
        print(canonical({'status': 'ERROR', 'reason': 'Campaign unavailable; preserve artifacts for review'}).decode())
        return 1
    print(canonical(result).decode())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
