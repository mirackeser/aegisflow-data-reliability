# SPDX-License-Identifier: Apache-2.0
"""Offline split checks and exact, dual-review label reconciliation."""
from hashlib import sha256

from .core import BenchmarkError, ID, LABELS, canonical, closed, parse, signature, validate
from .quality import HASH


CASE = closed({
    'case_id': ID, 'family': ID, 'group_id': ID,
    'csv_text': {'type': 'string', 'minLength': 1, 'maxLength': 16_384},
    'transform': {'enum': ['clean', 'exclude_first']},
})
CORPUS = {'type': 'array', 'minItems': 1, 'maxItems': 10_000, 'items': CASE}
MANIFEST_CASE = closed({
    'case_id': ID, 'family': ID, 'group_id': ID, 'content_signature_sha256': HASH,
})
MANIFEST = closed({
    'version': {'const': '1'}, 'development_sha256': HASH, 'candidate_sha256': HASH,
    'cases': {'type': 'array', 'minItems': 1, 'maxItems': 10_000, 'items': MANIFEST_CASE},
})
ANNOTATION = closed({
    'version': {'const': '1'}, 'reviewer_id': ID, 'manifest_sha256': HASH,
    'labels': {'type': 'array', 'minItems': 1, 'maxItems': 10_000,
               'items': closed({'case_id': ID, 'label': {'enum': list(LABELS)}})},
})


def _unique(items, key):
    values = {item[key] for item in items}
    if len(values) != len(items):
        raise BenchmarkError('Duplicate curation identity or content')
    return values


def prepare_manifest(development_bytes, candidate_bytes):
    """Bind label-free source bytes; reject known split overlap and repeated holdout groups."""
    development, candidates = parse(development_bytes), parse(candidate_bytes)
    validate(CORPUS, development)
    validate(CORPUS, candidates)
    _unique(development, 'case_id')
    _unique(candidates, 'case_id')
    _unique(candidates, 'group_id')
    # Deliberately ignore the transformation and row/column order when detecting copies.
    # This conservative heuristic is not semantic leakage detection.
    dev_signatures = {signature(item['csv_text']) for item in development}
    manifest_cases = [{**{key: item[key] for key in ('case_id', 'family', 'group_id')},
                       'content_signature_sha256': signature(item['csv_text'])}
                      for item in candidates]
    candidate_signatures = _unique(manifest_cases, 'content_signature_sha256')
    for key in ('case_id', 'family', 'group_id'):
        if {item[key] for item in development} & {item[key] for item in candidates}:
            raise BenchmarkError('Curation split overlap rejected')
    if dev_signatures & candidate_signatures:
        raise BenchmarkError('Curation split overlap rejected')
    value = {'version': '1', 'development_sha256': sha256(development_bytes).hexdigest(),
             'candidate_sha256': sha256(candidate_bytes).hexdigest(),
             'cases': sorted(manifest_cases, key=lambda item: item['case_id'])}
    validate(MANIFEST, value)
    return canonical(value)


def reconcile_annotations(manifest_bytes, annotation_bytes, *, expected_manifest_sha256, reviewer_ids):
    """Require two host-approved distinct reviewers; disagreement yields no usable labels.

    Reviewer names are local identifiers, not authenticated identities. This function
    does not attest independence, seal a dataset or authorize model acceptance.
    """
    manifest = parse(manifest_bytes)
    validate(MANIFEST, manifest)
    digest = sha256(manifest_bytes).hexdigest()
    if digest != expected_manifest_sha256:
        raise BenchmarkError('Curation manifest binding rejected')
    if type(reviewer_ids) is not tuple or len(reviewer_ids) != 2:
        raise BenchmarkError('Two distinct approved reviewers required')
    for reviewer in reviewer_ids:
        validate(ID, reviewer)
    if reviewer_ids[0] == reviewer_ids[1]:
        raise BenchmarkError('Two distinct approved reviewers required')
    if type(annotation_bytes) is not tuple or len(annotation_bytes) != 2:
        raise BenchmarkError('Two annotation artifacts required')
    ids = _unique(manifest['cases'], 'case_id')
    _unique(manifest['cases'], 'group_id')
    _unique(manifest['cases'], 'content_signature_sha256')
    annotations, hashes = {}, {}
    for raw in annotation_bytes:
        annotation = parse(raw)
        validate(ANNOTATION, annotation)
        reviewer = annotation['reviewer_id']
        if (annotation['manifest_sha256'] != digest or reviewer not in reviewer_ids
                or reviewer in annotations):
            raise BenchmarkError('Annotation binding rejected')
        if _unique(annotation['labels'], 'case_id') != ids:
            raise BenchmarkError('Exact annotation case coverage required')
        annotations[reviewer] = {item['case_id']: item['label'] for item in annotation['labels']}
        hashes[reviewer] = sha256(raw).hexdigest()
    first, second = (annotations[reviewer] for reviewer in reviewer_ids)
    disagreements = sorted(case_id for case_id in ids if first[case_id] != second[case_id])
    cases = [] if disagreements else [
        {'case_id': item['case_id'], 'family': item['family'], 'label': first[item['case_id']]}
        for item in sorted(manifest['cases'], key=lambda item: item['case_id'])]
    return {'version': '1', 'status': 'DISAGREEMENT' if disagreements else 'AGREED',
            'manifest_sha256': digest, 'annotations': hashes, 'disagreements': disagreements,
            'cases': cases, 'quality_cases_sha256': sha256(canonical(cases)).hexdigest() if cases else None}
