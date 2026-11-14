# SPDX-License-Identifier: Apache-2.0
"""Public evaluation reporting: raw predictions and accepted advice stay separate."""
from dataclasses import asdict, dataclass

from .core import BenchmarkError, LABELS, canonical, closed, validate
from .quality import HASH, evaluate_quality
from ..advisory.contracts import REQUEST, RESPONSE

COUNT = {'type': 'integer', 'minimum': 0, 'maximum': 10**18}
CONFIG = closed({'model_id': REQUEST['properties']['model_id'], 'model_revision_sha256': HASH,
    'max_tokens': {'type': 'integer', 'minimum': 1, 'maximum': 10**9},
    'max_cost_nusd': COUNT,
    'case_timeout_ms': {'type': 'integer', 'minimum': 1, 'maximum': 600000},
    'max_case_latency_ms': {'type': 'integer', 'minimum': 1, 'maximum': 600000}})
STATES = ('VERIFIED_ADVISORY', 'REJECTED_ADVISORY', 'ABSTAIN', 'USAGE_UNKNOWN',
          'KNOWN_RETRYABLE_FAILURE', 'KNOWN_TERMINAL_FAILURE', 'RESPONSE_REJECTED',
          'DEADLINE_EXCEEDED', 'ADMISSION_DENIED', 'NOT_RUN')
RECORD = closed({'case_id': {'type': 'string'}, 'status': {'enum': list(STATES)},
    'request_sha256': {'anyOf': [HASH, {'type': 'null'}]},
    'input_sha256': {'anyOf': [HASH, {'type': 'null'}]},
    'response': {'anyOf': [RESPONSE, {'type': 'null'}]},
    'adapter_invocations': {'type': 'integer', 'minimum': 0, 'maximum': 1},
    'elapsed_ms': COUNT, 'usage': closed({key: COUNT for key in
        ('held_tokens', 'charged_tokens', 'held_cost_nusd', 'charged_cost_nusd')})})


@dataclass(frozen=True)
class CampaignPolicy:
    model_id: str
    model_revision_sha256: str
    max_tokens: int = 100000
    max_cost_nusd: int = 1000000000
    case_timeout_ms: int = 10000
    max_case_latency_ms: int = 10000

    def __post_init__(self):
        validate(CONFIG, asdict(self))
        if any(type(getattr(self, field)) is not int for field in
               ('max_tokens', 'max_cost_nusd', 'case_timeout_ms', 'max_case_latency_ms')):
            raise BenchmarkError('Integer campaign limits required')


def summarize(suite, records, policy, protocol, quality_cases):
    """Recompute from bounded observations; never trust a stored success flag."""
    CampaignPolicy(**policy)
    if type(records) is not list or len(records) != len(suite['cases']):
        raise BenchmarkError('Exact campaign case coverage required')
    raw, accepted, totals = [], [], {key: 0 for key in RECORD['properties']['usage']['properties']}
    reasons, latencies, invocations = [], [], 0
    for expected, item in zip(suite['cases'], records):
        validate(RECORD, item)
        if any(type(v) is not int for v in (item['adapter_invocations'], item['elapsed_ms'], *item['usage'].values())):
            raise BenchmarkError('Integer campaign observations required')
        if item['case_id'] != expected['case_id']:
            raise BenchmarkError('Campaign case order changed')
        response, status = item['response'], item['status']
        usable = (response is not None and response['request_sha256'] == item['request_sha256']
                  and status in ('VERIFIED_ADVISORY', 'REJECTED_ADVISORY', 'ABSTAIN'))
        prediction = ('ABSTAIN' if response['decision'] == 'ABSTAIN' else response['assessment']) if usable else 'ERROR'
        unsupported = status == 'REJECTED_ADVISORY' or (response is not None and not usable)
        gated = prediction if status == 'VERIFIED_ADVISORY' and prediction in LABELS else 'ABSTAIN'
        raw.append({'case_id': item['case_id'], 'prediction': prediction, 'unsupported_claim': unsupported})
        accepted.append({'case_id': item['case_id'], 'prediction': gated})
        for key in totals:
            totals[key] += item['usage'][key]
        invocations += item['adapter_invocations']
        latencies.append(item['elapsed_ms'])
        if status != 'VERIFIED_ADVISORY':
            reasons.append('CASE_NOT_VERIFIED:' + item['case_id'])
        if item['elapsed_ms'] > policy['max_case_latency_ms']:
            reasons.append('LATENCY_LIMIT:' + item['case_id'])
    if totals['held_tokens'] or totals['held_cost_nusd']:
        reasons.append('UNRESOLVED_USAGE')
    if (totals['held_tokens'] + totals['charged_tokens'] > policy['max_tokens'] or
            totals['held_cost_nusd'] + totals['charged_cost_nusd'] > policy['max_cost_nusd']):
        raise BenchmarkError('Campaign accounting exceeds policy')
    quality = evaluate_quality(protocol, quality_cases, canonical(raw),
                               model_revision_sha256=policy['model_revision_sha256'])
    return {'version': '1', 'scope': 'public-synthetic-adapter-evaluation',
        'operational_decision': 'BLOCK' if reasons else 'PASS', 'operational_reasons': reasons,
        'quality': quality, 'raw_predictions': raw, 'accepted_predictions': accepted,
        'adapter_invocations': invocations, 'usage': totals,
        'latency_ms': {'max': max(latencies), 'total': sum(latencies),
                       'p95_nearest_rank': sorted(latencies)[(95 * len(latencies) + 99) // 100 - 1]},
        'live_activation_authorized': False, 'independent_model_accuracy_measured': False}
