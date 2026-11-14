# SPDX-License-Identifier: Apache-2.0
"""Exclusive private campaign directories, sealed last; no resume or overwrite."""
from hashlib import sha256
import os
from pathlib import Path

from .core import BenchmarkError, canonical, closed, parse, validate
from .quality import HASH

MAX_ARTIFACT = 16000000
MAX_TOTAL = 64000000
MANIFEST = closed({'version': {'const': '1'}, 'artifacts': {'type': 'object',
    'minProperties': 1, 'maxProperties': 140, 'additionalProperties': HASH}})


def write(path, raw):
    with open(path, 'xb') as target:
        os.chmod(path, 0o600)
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())


def read(path, limit=MAX_ARTIFACT):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise BenchmarkError('Campaign artifact unavailable')
    with open(path, 'rb') as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise BenchmarkError('Campaign artifact exceeds limit')
    return raw


def seal(root):
    artifacts = {path.name: sha256(read(path)).hexdigest() for path in sorted(root.iterdir())}
    raw = canonical({'version': '1', 'artifacts': artifacts})
    validate(MANIFEST, parse(raw))
    write(root / 'manifest.json', raw)
    descriptor = os.open(root, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return sha256(raw).hexdigest()


def verified_artifacts(directory, digest):
    """Digest must be retained separately by the trusted host; this is not a signature."""
    validate(HASH, digest)
    root = Path(directory)
    if root.is_symlink():
        raise BenchmarkError('Campaign directory rejected')
    raw = read(root / 'manifest.json', 1000000)
    if sha256(raw).hexdigest() != digest:
        raise BenchmarkError('Campaign manifest digest mismatch')
    manifest = parse(raw)
    validate(MANIFEST, manifest)
    entries = manifest['artifacts']
    if (any(Path(name).name != name or name in ('.', '..', 'manifest.json') for name in entries)
            or {p.name for p in root.iterdir()} != {*entries, 'manifest.json'}):
        raise BenchmarkError('Campaign artifact set mismatch')
    result = {}
    for name, expected in entries.items():
        value = read(root / name)
        if sum(map(len, result.values())) + len(value) > MAX_TOTAL:
            raise BenchmarkError('Campaign total size exceeded')
        if sha256(value).hexdigest() != expected:
            raise BenchmarkError('Campaign artifact digest mismatch')
        result[name] = value
    return result
