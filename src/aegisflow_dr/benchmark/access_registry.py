# SPDX-License-Identifier: Apache-2.0
"""One immutable evaluator grant, terminal revocation and transactional audit."""
from contextlib import closing, contextmanager
from dataclasses import asdict
from hashlib import sha256
import os
from pathlib import Path
import sqlite3

from .core import BenchmarkError, canonical, parse
from .curation_access import EvaluationAccess, read_for_evaluation
from .curation_auth import _time


@contextmanager
def _db(path):
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=rw', uri=True, timeout=5)) as db, db:
            db.execute('PRAGMA trusted_schema=OFF')
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 16384)
            db.execute('BEGIN IMMEDIATE')
            yield db
    except BenchmarkError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError):
        raise BenchmarkError('Access registry unavailable') from None


def initialize_access(path, access):
    if type(access) is not EvaluationAccess or access.revoked:
        raise BenchmarkError('Active evaluator grant required')
    raw = canonical(asdict(access))
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
    except (OSError, TypeError, ValueError):
        raise BenchmarkError('New access registry required') from None
    with _db(path) as db:
        db.execute('CREATE TABLE authority (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL, revoked INTEGER NOT NULL CHECK(revoked IN (0,1)))')
        db.execute('INSERT INTO authority VALUES (1,?,0)', (raw,))
        db.execute('CREATE TABLE audit (sequence INTEGER PRIMARY KEY, time_ms INTEGER NOT NULL, outcome TEXT NOT NULL)')
        db.execute("CREATE TRIGGER preserve_authority BEFORE UPDATE ON authority WHEN NEW.payload IS NOT OLD.payload OR NEW.id != OLD.id OR NEW.revoked < OLD.revoked BEGIN SELECT RAISE(ABORT,'Immutable authority'); END")
        db.execute("CREATE TRIGGER preserve_grant BEFORE DELETE ON authority BEGIN SELECT RAISE(ABORT,'Immutable authority'); END")
        for action in ('UPDATE','DELETE'):
            db.execute(f"CREATE TRIGGER audit_{action.lower()} BEFORE {action} ON audit BEGIN SELECT RAISE(ABORT,'Append only audit'); END")
    return sha256(raw).hexdigest()


def _authority(db, expected_sha256):
    rows = db.execute('SELECT payload,revoked FROM authority LIMIT 2').fetchall()
    if len(rows) != 1 or type(rows[0][0]) is not bytes or sha256(rows[0][0]).hexdigest() != expected_sha256:
        raise BenchmarkError('Access registry binding rejected')
    try:
        access = EvaluationAccess(**parse(rows[0][0]))
    except TypeError:
        raise BenchmarkError('Access registry grant rejected') from None
    if rows[0][1] not in (0,1):
        raise BenchmarkError('Access registry revocation rejected')
    return access, bool(rows[0][1])


def revoke_access(path, *, expected_sha256, now_ms):
    _time(now_ms)
    with _db(path) as db:
        _, revoked = _authority(db, expected_sha256)
        if not revoked:
            db.execute('UPDATE authority SET revoked=1 WHERE id=1')
            db.execute("INSERT INTO audit(time_ms,outcome) VALUES (?,'REVOKED')", (now_ms,))


def evaluate_registered(path, snapshot_path, *, expected_grant_sha256, principal_id, role,
                         expected_sha256, key_id, policy_revision, now_ms, grants, resolve_key):
    """Serialize revocation and read, committing its audit before releasing labels."""
    _time(now_ms)
    error = None
    result = None
    with _db(path) as db:
        access, revoked = _authority(db, expected_grant_sha256)
        # Audit storage must accept a write before invoking any key resolver.
        db.execute("INSERT INTO audit(time_ms,outcome) VALUES (?,'STARTED')", (now_ms,))
        try:
            if revoked:
                raise BenchmarkError('Evaluation access denied')
            result = read_for_evaluation(snapshot_path, access=access, principal_id=principal_id,
                                         role=role, expected_sha256=expected_sha256, key_id=key_id,
                                         policy_revision=policy_revision, now_ms=now_ms,
                                         grants=grants, resolve_key=resolve_key)
        except BenchmarkError:
            error = BenchmarkError('Registered evaluation rejected')
        db.execute('INSERT INTO audit(time_ms,outcome) VALUES (?,?)',
                   (now_ms, 'REJECTED' if error else 'VERIFIED'))
    if error:
        raise error
    return result


def access_history(path, *, expected_sha256, after=0, limit=100):
    if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise BenchmarkError('Bounded audit cursor required')
    with _db(path) as db:
        _authority(db, expected_sha256)
        return [{'sequence': row[0], 'time_ms': row[1], 'outcome': row[2]} for row in
                db.execute('SELECT sequence,time_ms,outcome FROM audit WHERE sequence>? ORDER BY sequence LIMIT ?', (after,limit))]
