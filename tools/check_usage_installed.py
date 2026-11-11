# SPDX-License-Identifier: Apache-2.0
"""Verify durable usage admission from an installed distribution, without a provider."""
from pathlib import Path
from tempfile import TemporaryDirectory
import aegisflow_dr
from aegisflow_dr.advisory.context import PreparedAdvisory
from aegisflow_dr.advisory.contracts import AdvisoryError
from aegisflow_dr.advisory.usage import UsageLedger, UsagePolicy, UsageQuote, initialize_usage
from aegisflow_dr.investigation import default_policy
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.storage import IncidentStore, initialize
from aegisflow_dr.storage.runs import InvestigationRuns

checkout = Path(__file__).resolve().parents[1]
if Path(aegisflow_dr.__file__).resolve().is_relative_to(checkout / 'src'):
    raise RuntimeError('Installed usage check imported source checkout')
with TemporaryDirectory() as temporary:
    evidence, usage = Path(temporary) / 'evidence.db', Path(temporary) / 'usage.db'
    initialize(evidence)
    store = IncidentStore(evidence)
    source = store.record(generate_orders(), request_key='usage-installed')
    runs = InvestigationRuns(store)
    record = runs.execute(source['incident_id'], default_policy(), request_key='usage-installed')
    before = evidence.read_bytes()
    prepared = PreparedAdvisory(runs, record['run_id'], model_id='offline/test')
    quote = UsageQuote(prepared.manifest['input_sha256'], 'offline/test', 'fixture-v1', 10, 5, 2, 3)
    initialize_usage(usage, UsagePolicy(max_tokens=15, max_cost_nusd=35))
    ledger = UsageLedger(usage, clock_ms=lambda: 1000)
    row = ledger.reserve(prepared, quote, attempt_key='installed', deadline_ms=2000)
    ledger.transition(row['attempt_id'], 'start')
    try:
        ledger.transition(row['attempt_id'], 'start')
    except AdvisoryError:
        pass
    else:
        raise RuntimeError('Installed usage check allowed duplicate start')
    ledger.transition(row['attempt_id'], 'settle', input_tokens=8, output_tokens=2)
    snapshot = UsageLedger(usage).snapshot()
    if (snapshot['held_tokens'], snapshot['charged_tokens'], snapshot['charged_cost_nusd']) != (0, 10, 22):
        raise RuntimeError('Installed usage accounting mismatch')
    if evidence.read_bytes() != before:
        raise RuntimeError('Installed usage check changed evidence')
print('Installed durable admission, one-shot start, exact accounting and restart checks passed.')
