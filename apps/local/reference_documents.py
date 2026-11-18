# SPDX-License-Identifier: Apache-2.0
"""The built-in reference documents the workbench retrieves from. Untrusted reference text, never instructions."""
from knowledge import Document

REFERENCE_DOCUMENTS = (Document('local', 'quality-contract', 'v1',
    'Source quality failure: check missing order_total values and duplicate order_id records. '
    'A finding is an observation, not a causal explanation. Never repair source data automatically.'),
    Document('local', 'reconciliation-contract', 'v1',
        'Transformation reconciliation compares expected and observed order count and amount cents. '
        'A mismatch is evidence of loss or inconsistent transformation, not proof of a causal root cause.'),
    Document('local', 'schema-contract', 'v1',
        'Schema contract: order_id, customer_id and order_total are required and no other column is allowed. '
        'A missing or unexpected column often means a renamed or reordered export field. A rename is a candidate '
        'explanation to confirm with the data owner, never proof; map columns only after confirmation.'),
    Document('local', 'missing-value-guidance', 'v1',
        'Empty required value: a blank order_total understates revenue and a blank identifier prevents matching. '
        'The inspection reports the record number only. Fix the value at its source system and inspect a new export.'),
    Document('local', 'duplicate-guidance', 'v1',
        'Duplicate order_id: identical repeated records are consistent with a repeated load or export; records with '
        'conflicting values indicate a key collision or conflicting updates. Repeats counted twice overstate revenue. '
        'The observed pattern does not prove the cause; confirm in the source system before removing anything.'),
    Document('local', 'amount-format-guidance', 'v1',
        'Invalid amount format: order_total must be a nonnegative decimal with at most two decimal places and no '
        'currency symbol, thousands separator or exponent. A locale decimal comma or text value cannot be summed safely.'))
