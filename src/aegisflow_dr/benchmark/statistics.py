# SPDX-License-Identifier: Apache-2.0
"""Exact integer binomial support tests with a fixed family-wise error budget."""
from math import comb

from .core import BenchmarkError, closed, validate


METHOD = 'exact-binomial-bonferroni-v1'
STATISTICS = closed({'method': {'const': METHOD},
                     'sampling_assumptions_approved': {'type': 'boolean'},
                     'familywise_alpha_bps': {'type': 'integer', 'minimum': 1, 'maximum': 500}})


def validate_statistics(value):
    validate(STATISTICS, value)
    if type(value['familywise_alpha_bps']) is not int:
        raise BenchmarkError('Integer significance budget required')


def supports_target(successes, trials, target_bps, *, alpha_bps=500, comparisons=1):
    """Test P(Binomial(n, target) >= successes) <= alpha / comparisons exactly.

    Independent Bernoulli trials within a metric are a host-reviewed assumption.
    No floating point rounding, estimated rates or externally supplied p-values.
    """
    values = (successes, trials, target_bps, alpha_bps, comparisons)
    if (any(type(value) is not int for value in values)
            or not 0 <= successes <= trials <= 10_000 or not 1 <= target_bps <= 10_000
            or not 1 <= alpha_bps <= 500 or not 1 <= comparisons <= 71):
        raise BenchmarkError('Statistical counts or policy rejected')
    if trials == 0 or successes == 0 or target_bps == 10_000:
        return False
    denominator = 10_000 ** trials
    complement = 10_000 - target_bps
    term = comb(trials, successes) * target_bps ** successes * complement ** (trials-successes)
    numerator = term
    for count in range(successes, trials):
        # Positive remaining terms can only increase the tail; fail early safely.
        if numerator * 10_000 * comparisons > alpha_bps * denominator:
            return False
        term = term * (trials-count) * target_bps // ((count+1) * complement)
        numerator += term
    return numerator * 10_000 * comparisons <= alpha_bps * denominator


def statistical_support(result, protocol):
    """Internal scorer output only; callers must validate/recompute source counts first."""
    settings = protocol['statistics']
    validate_statistics(settings)
    policy = protocol['policy']
    metrics = {'ACCURACY': (result['correct'], result['case_count'], policy['min_accuracy_bps'])}
    for label, counts in result['per_class'].items():
        metrics['CLASS_PRECISION:'+label] = (counts['true_positive'], counts['predicted'], policy['min_precision_bps'])
        metrics['CLASS_RECALL:'+label] = (counts['true_positive'], counts['support'], policy['min_recall_bps'])
    for family, counts in result['families'].items():
        metrics['FAMILY_ACCURACY:'+family] = (counts['correct'], counts['support'], policy['min_family_accuracy_bps'])
    comparisons = len(metrics)
    assessed = {name: {'successes': values[0], 'trials': values[1], 'target_bps': values[2],
                      'supported': supports_target(*values, alpha_bps=settings['familywise_alpha_bps'],
                                                   comparisons=comparisons)}
                for name, values in metrics.items()}
    return {**settings, 'comparisons': comparisons, 'metrics': assessed}
