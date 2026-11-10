# SPDX-License-Identifier: Apache-2.0
"""Exercise the installed CLI from a directory outside the source checkout."""
import json
from importlib.metadata import distribution
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

SCENARIOS = [
    (["demo"], 0, "PASS"),
    (["demo", "--fault", "schema_drift"], 1, "FAIL"),
    (["demo", "--fault", "null_total"], 1, "FAIL"),
    (["demo", "--fault", "duplicate_order"], 1, "FAIL"),
    (["batch-demo"], 0, "PASS"),
    (["batch-demo", "--transform", "exclude_first"], 1, "FAIL"),
    (["batch-demo", "--fault", "schema_drift"], 1, "BLOCKED"),
]


def main() -> None:
    dist = distribution("aegisflow-data-reliability")
    if dist.metadata.get("License-Expression") != "Apache-2.0":
        raise RuntimeError("Installed license metadata is inconsistent")
    for filename in ("LICENSE", "NOTICE"):
        matches = [entry for entry in dist.files or ()
                   if str(entry).endswith(".dist-info/licenses/" + filename)]
        if len(matches) != 1 or not dist.locate_file(matches[0]).is_file():
            raise RuntimeError("Installed license file missing: " + filename)
    gateway = subprocess.run([sys.executable, "-m", "aegisflow_dr", "gateway-demo"],
                             capture_output=True, text=True, check=True, timeout=20)
    result = json.loads(gateway.stdout)
    if result["outcome"] != "OK" or result["report"]["status"] != "PASS":
        raise RuntimeError("Installed gateway demo failed")
    catalog = subprocess.run([sys.executable, "-m", "aegisflow_dr", "catalog"],
                             capture_output=True, text=True, check=True)
    if "36 planned specialist roles" not in catalog.stdout:
        raise RuntimeError("Installed catalog validation failed")
    for arguments, exit_code, status in SCENARIOS:
        result = subprocess.run([sys.executable, "-m", "aegisflow_dr", *arguments],
                                capture_output=True, text=True, timeout=20)
        if result.returncode != exit_code or json.loads(result.stdout)["status"] != status:
            raise RuntimeError(f"Installed CLI regression: {arguments}")
    def invoke(arguments):
        completed = subprocess.run([sys.executable, '-m', 'aegisflow_dr', *arguments],
                                   capture_output=True, text=True, check=True, timeout=20)
        return json.loads(completed.stdout)
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        database = str(root / 'research.db')
        source = root / 'synthetic.csv'
        source.write_bytes(b'order_id,customer_id,order_total\na,c,1.25\n')
        invoke(['store-init', '--db', database])
        saved = invoke(['record-source', '--db', database, '--source', str(source), '--key', 'smoke'])
        incident = saved['incident_id']
        restored = invoke(['read-incident', '--db', database, '--incident', incident])
        if restored != saved:
            raise RuntimeError('Installed history changed across processes')
        replay = invoke(['replay-incident', '--db', database, '--incident', incident])
        if replay['outcome'] != 'MATCH':
            raise RuntimeError('Installed replay mismatch')
        investigation = invoke(['investigate-incident', '--db', database, '--incident', incident])
        if investigation['status'] != 'COMPLETED' or investigation['assessment'] != 'NO_FAILURE_OBSERVED':
            raise RuntimeError('Installed investigation regression')
        faulted = invoke(['investigate-incident', '--db', database, '--incident', incident,
                          '--transform', 'exclude_first'])
        if faulted['assessment'] != 'TRANSFORMATION_RECONCILIATION_FAILURE':
            raise RuntimeError('Installed transformation investigation regression')
        recorded = invoke(['record-investigation', '--db', database, '--incident', incident,
                           '--key', 'durable', '--transform', 'exclude_first'])
        run = recorded['run_id']
        if len(recorded['manifest']['artifacts']) != 4 or recorded['trace']['assessment'] != 'TRANSFORMATION_RECONCILIATION_FAILURE':
            raise RuntimeError('Installed durable evidence missing')
        if invoke(['read-investigation', '--db', database, '--run', run]) != recorded:
            raise RuntimeError('Installed run changed across processes')
        if invoke(['replay-investigation', '--db', database, '--run', run])['outcome'] != 'MATCH':
            raise RuntimeError('Installed run replay mismatch')
        if invoke(['record-investigation', '--db', database, '--incident', incident,
                   '--key', 'durable', '--transform', 'exclude_first']) != recorded:
            raise RuntimeError('Installed run idempotency mismatch')
        proposal = {'version': '1', 'run_id': run, 'incident_id': incident,
                    'assessment': recorded['trace']['assessment'],
                    'evidence_sha256': sorted({recorded['trace']['source_sha256'],
                        *(step['report_sha256'] for step in recorded['trace']['steps'])})}
        proposal_file = root / 'proposal.json'
        proposal_file.write_text(json.dumps(proposal))
        reviewed = invoke(['review-investigation', '--db', database, '--proposal', str(proposal_file)])
        if reviewed['verdict']['decision'] != 'ACCEPT' or [r['agent_id'] for r in reviewed['receipts']] != ['A26', 'A27']:
            raise RuntimeError('Installed coordination/Judge regression')
        proposal['assessment'] = 'NO_FAILURE_OBSERVED'
        proposal_file.write_text(json.dumps(proposal))
        rejected = subprocess.run([sys.executable, '-m', 'aegisflow_dr', 'review-investigation',
                                  '--db', database, '--proposal', str(proposal_file)],
                                 capture_output=True, text=True, timeout=20)
        if rejected.returncode != 1 or json.loads(rejected.stdout)['verdict']['decision'] != 'REJECT':
            raise RuntimeError('Installed contradictory proposal was not rejected')
        queue = str(root / 'queue.db')
        invoke(['queue-init', '--queue', queue])
        arguments = ['submit-review', '--queue', queue, '--db', database,
                     '--proposal', str(proposal_file), '--key', 'durable-review']
        job = invoke(arguments)
        if invoke(arguments) != job:
            raise RuntimeError('Installed queue idempotency regression')
        for expected in ('collect', 'judge'):
            applied = invoke(['work-once', '--queue', queue, '--db', database])
            if applied['outcome'] != 'APPLIED' or applied['task_id'] != expected:
                raise RuntimeError('Installed durable dependency dispatch regression')
        saved_job = invoke(['read-job', '--queue', queue, '--job', job['job_id']])
        if saved_job['status'] != 'SUCCEEDED' or saved_job['tasks']['judge']['result']['decision'] != 'REJECT':
            raise RuntimeError('Installed durable Judge result regression')
        if invoke(['work-once', '--queue', queue, '--db', database])['outcome'] != 'IDLE':
            raise RuntimeError('Installed terminal job was dispatched again')
        arguments[-1] = 'cancelled-review'
        cancelled_job = invoke(arguments)
        cancelled = invoke(['cancel-job', '--queue', queue, '--job', cancelled_job['job_id']])
        if cancelled['status'] != 'CANCELLED' or invoke(['recover-job', '--queue', queue,
                                                      '--job', cancelled_job['job_id']]) != cancelled:
            raise RuntimeError('Installed cancellation/recovery regression')
        invoke(['store-recover', '--db', database])
        invoke(['store-migrate', '--db', database])
        evaluation = invoke(['evaluate-investigation'])
        if not evaluation['all_matched'] or evaluation['case_count'] != 10 or evaluation['held_out_benchmark']:
            raise RuntimeError('Installed development suite regression')
        closed = invoke(['close-incident', '--db', database, '--incident', incident,
                         '--expected-revision', '2', '--actor', 'smoke'])
        retried = invoke(['record-source', '--db', database, '--source', str(source), '--key', 'smoke'])
        if closed['state'] != 'CLOSED' or retried != closed:
            raise RuntimeError('Installed lifecycle/idempotency regression')
    print("Installed licensing, diagnostics, evidence, coordination and durable queue checks passed.")


if __name__ == "__main__":
    main()
