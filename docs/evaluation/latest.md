# Deterministic check evaluation

Scope: Deterministic order-contract checks against synthetic injected faults. Not real data, not unseen fault kinds, and not a language model.

- Corpus: 1120 cases, 40 base tables, 28 injected patterns; sha256 `72804863d3dfb1309bbf3d3f055a5f6308cdc6bcbe6a433b775552297ced1e3c`
- Leakage across splits: none found ({'groups_in_several_splits': 0, 'payloads_in_several_splits': 0, 'records_in_several_splits': 0, 'clean': True})
- Held-out split scored: yes

## diagnose_csv

### development (672 cases)

Exact-match cases: 100.00% (672/672)

| check | precision | recall | TP | FP | FN |
|---|---|---|---|---|---|
| amount_format | 100.00% (192/192) | 100.00% (192/192) | 192 | 0 | 0 |
| missing_column | 100.00% (48/48) | 100.00% (48/48) | 48 | 0 | 0 |
| not_null | 100.00% (240/240) | 100.00% (240/240) | 240 | 0 | 0 |
| unexpected_column | 100.00% (48/48) | 100.00% (48/48) | 48 | 0 | 0 |
| unique | 100.00% (216/216) | 100.00% (216/216) | 216 | 0 | 0 |
| overall | 100.00% (744/744) | 100.00% (744/744) | 744 | 0 | 0 |

Missed by category: none
Spurious by variant: none

### validation (280 cases)

Exact-match cases: 100.00% (280/280)

| check | precision | recall | TP | FP | FN |
|---|---|---|---|---|---|
| amount_format | 100.00% (80/80) | 100.00% (80/80) | 80 | 0 | 0 |
| missing_column | 100.00% (20/20) | 100.00% (20/20) | 20 | 0 | 0 |
| not_null | 100.00% (100/100) | 100.00% (100/100) | 100 | 0 | 0 |
| unexpected_column | 100.00% (20/20) | 100.00% (20/20) | 20 | 0 | 0 |
| unique | 100.00% (90/90) | 100.00% (90/90) | 90 | 0 | 0 |
| overall | 100.00% (310/310) | 100.00% (310/310) | 310 | 0 | 0 |

Missed by category: none
Spurious by variant: none

### heldout (168 cases)

Exact-match cases: 100.00% (168/168)

| check | precision | recall | TP | FP | FN |
|---|---|---|---|---|---|
| amount_format | 100.00% (48/48) | 100.00% (48/48) | 48 | 0 | 0 |
| missing_column | 100.00% (12/12) | 100.00% (12/12) | 12 | 0 | 0 |
| not_null | 100.00% (60/60) | 100.00% (60/60) | 60 | 0 | 0 |
| unexpected_column | 100.00% (12/12) | 100.00% (12/12) | 12 | 0 | 0 |
| unique | 100.00% (54/54) | 100.00% (54/54) | 54 | 0 | 0 |
| overall | 100.00% (186/186) | 100.00% (186/186) | 186 | 0 | 0 |

Missed by category: none
Spurious by variant: none

## record_issues

### development (672 cases)

Exact-match cases: 100.00% (672/672)

| check | precision | recall | TP | FP | FN |
|---|---|---|---|---|---|
| amount_format | 100.00% (192/192) | 100.00% (192/192) | 192 | 0 | 0 |
| not_null | 100.00% (240/240) | 100.00% (240/240) | 240 | 0 | 0 |
| unique | 100.00% (216/216) | 100.00% (216/216) | 216 | 0 | 0 |
| overall | 100.00% (648/648) | 100.00% (648/648) | 648 | 0 | 0 |

Missed by category: none
Spurious by variant: none

### validation (280 cases)

Exact-match cases: 100.00% (280/280)

| check | precision | recall | TP | FP | FN |
|---|---|---|---|---|---|
| amount_format | 100.00% (80/80) | 100.00% (80/80) | 80 | 0 | 0 |
| not_null | 100.00% (100/100) | 100.00% (100/100) | 100 | 0 | 0 |
| unique | 100.00% (90/90) | 100.00% (90/90) | 90 | 0 | 0 |
| overall | 100.00% (270/270) | 100.00% (270/270) | 270 | 0 | 0 |

Missed by category: none
Spurious by variant: none

### heldout (168 cases)

Exact-match cases: 100.00% (168/168)

| check | precision | recall | TP | FP | FN |
|---|---|---|---|---|---|
| amount_format | 100.00% (48/48) | 100.00% (48/48) | 48 | 0 | 0 |
| not_null | 100.00% (60/60) | 100.00% (60/60) | 60 | 0 | 0 |
| unique | 100.00% (54/54) | 100.00% (54/54) | 54 | 0 | 0 |
| overall | 100.00% (162/162) | 100.00% (162/162) | 162 | 0 | 0 |

Missed by category: none
Spurious by variant: none

