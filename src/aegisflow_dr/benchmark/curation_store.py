# SPDX-License-Identifier: Apache-2.0
"""Private local curation snapshots, verified against an external trusted digest."""
from contextlib import closing, contextmanager
from hashlib import sha256
import os
from pathlib import Path
import sqlite3

from .core import BenchmarkError, canonical
from .curation import prepare_manifest, reconcile_annotations

TABLE_SQL = 'CREATE TABLE artifacts (name TEXT PRIMARY KEY, value BLOB NOT NULL)'


@contextmanager
def _database(path, *, readonly):
    try:
        uri = Path(path).resolve().as_uri() + ('?mode=ro' if readonly else '?mode=rw')
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection, connection:
            if readonly:
                connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_256)
                connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 16_384)
                connection.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 32)
                connection.execute('PRAGMA trusted_schema=OFF')
            connection.execute('BEGIN' if readonly else 'BEGIN IMMEDIATE')
            yield connection
    except BenchmarkError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError):
        raise BenchmarkError('Curation snapshot unavailable') from None


def _prepare(development, candidate, annotations, reviewers):
    manifest = prepare_manifest(development, candidate)
    result = reconcile_annotations(manifest, annotations, expected_manifest_sha256=sha256(manifest).hexdigest(),
                                   reviewer_ids=reviewers)
    artifacts = dict(development=development, candidate=candidate,
                     annotation_a=annotations[0], annotation_b=annotations[1])
    header = canonical({'version':'1', 'reviewers':list(reviewers),
                        'artifacts':{key:sha256(value).hexdigest() for key,value in artifacts.items()},
                        'manifest_sha256':sha256(manifest).hexdigest(), 'result_sha256':sha256(canonical(result)).hexdigest()})
    return header, artifacts, result


def retain_curation(path, development, candidate, annotations, *, reviewer_ids):
    """Exclusively create a snapshot; preserve agreement and disagreement alike."""
    header, artifacts, _ = _prepare(development, candidate, annotations, reviewer_ids)
    return _write_snapshot(path, header, artifacts)


def _write_snapshot(path, header, artifacts):
    """Shared exclusive, transactional storage for validated curation artifacts."""
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
    except (OSError, TypeError, ValueError):
        raise BenchmarkError('New curation snapshot required') from None
    with _database(path, readonly=False) as connection:
        connection.execute(TABLE_SQL)
        connection.executemany('INSERT INTO artifacts VALUES (?,?)', {**artifacts, 'header':header}.items())
        for action in ('INSERT', 'UPDATE', 'DELETE'):
            connection.execute(f"CREATE TRIGGER immutable_{action.lower()} BEFORE {action} ON artifacts BEGIN SELECT RAISE(ABORT,'Immutable curation snapshot'); END")
    return sha256(header).hexdigest()


def read_curation(path, *, expected_sha256, reviewer_ids):
    """Recompute source leakage checks and labels before returning a verified result.

    Expected digest and reviewer IDs come from the trusted host, not this file.
    The database contains private source data; it is not a model-facing interface.
    """
    artifacts = _read_snapshot(path, expected_sha256, {'development','candidate','annotation_a','annotation_b','header'})
    header, _, result = _prepare(artifacts['development'], artifacts['candidate'],
                                 (artifacts['annotation_a'],artifacts['annotation_b']), reviewer_ids)
    if artifacts['header'] != header:
        raise BenchmarkError('Curation snapshot integrity rejected')
    return result


def _read_snapshot(path, expected_sha256, expected_names, *, maximum_blob_bytes=1_000_000):
    """Bounded physical-table reader; caller supplies the exact artifact names."""
    with _database(path, readonly=True) as connection:
        schema = connection.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name='artifacts' LIMIT 2").fetchall()
        if schema != [(TABLE_SQL,)]:
            raise BenchmarkError('Curation snapshot schema rejected')
        sizes = connection.execute('SELECT name, typeof(value), length(value) FROM artifacts LIMIT ?',
                                   (len(expected_names)+1,)).fetchall()
        if (len(sizes) != len(expected_names) or {row[0] for row in sizes} != expected_names
                or any(row[1] != 'blob' or not 0 < row[2] <= maximum_blob_bytes for row in sizes)):
            raise BenchmarkError('Curation snapshot structure rejected')
        artifacts = dict(connection.execute('SELECT name,value FROM artifacts').fetchall())
        if sha256(artifacts['header']).hexdigest() != expected_sha256:
            raise BenchmarkError('Curation snapshot binding rejected')
        return artifacts
