# SPDX-License-Identifier: Apache-2.0
"""Durable signed review records; no refund, resend or settlement authority."""
from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3
import json

from .contracts import AdvisoryError, encode
from .recovery import verify_recovery_review
from .recovery_auth import verify_signature, _verify_usage
from .usage import UsageLedger, database, integer
from ..storage.store import canonical, sha


@contextmanager
def journal(path):
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=rw',uri=True,timeout=5)) as db,db:
            db.execute('PRAGMA trusted_schema=OFF')
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,16384)
            db.execute('BEGIN IMMEDIATE')
            yield db
    except AdvisoryError:
        raise
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,IndexError):
        raise AdvisoryError('Recovery decision log unavailable') from None


def initialize_decisions(path, *, operation_sha256):
    encode('recovery-decision-scope',{'operation_sha256':operation_sha256})
    try:
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(descriptor)
    except (OSError,TypeError,ValueError):
        raise AdvisoryError('New recovery decision log required') from None
    with journal(path) as db:
        db.execute('CREATE TABLE scope (operation TEXT NOT NULL)')
        db.execute('INSERT INTO scope VALUES (?)',(operation_sha256,))
        db.execute('CREATE TABLE decisions (sequence INTEGER PRIMARY KEY, review_id TEXT UNIQUE NOT NULL, recorded_at_ms INTEGER NOT NULL, payload BLOB NOT NULL, digest TEXT NOT NULL)')
        for table in ('scope','decisions'):
            for action in ('UPDATE','DELETE'):
                db.execute(f"CREATE TRIGGER {table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Append only'); END")


def scope(db, expected):
    rows=db.execute('SELECT operation FROM scope LIMIT 2').fetchall()
    if len(rows)!=1 or rows[0][0]!=expected:
        raise AdvisoryError('Recovery decision scope rejected')


def decision_payload(review, attestation=None, attestation_envelope=None):
    if (type(review) is not bytes or
            (attestation is None)!=(attestation_envelope is None) or
            (attestation is not None and (type(attestation) is not bytes or type(attestation_envelope) is not bytes))):
        raise AdvisoryError('Exact decision evidence bytes required')
    return encode('recovery-decision',{'version':'1','review_sha256':sha(review),
        'attestation_sha256':None if attestation is None else sha(attestation),
        'attestation_signature_sha256':None if attestation_envelope is None else sha(attestation_envelope)})


def record_decision(path, ledger, review, envelope, *, grant, now_ms,
                    attestation=None, attestation_envelope=None, issuer_grant=None):
    if (type(ledger) is not UsageLedger or ledger.version!=3 or
            Path(path).resolve()==ledger.path.resolve()):
        raise AdvisoryError('Separate decision and routing stores required')
    supplied=(attestation,attestation_envelope,issuer_grant)
    if any(item is not None for item in supplied) and any(item is None for item in supplied):
        raise AdvisoryError('Complete usage evidence required')
    with database(ledger.path) as connection:
        ledger._validate(connection)
        packet=verify_recovery_review(ledger,review)
        proof=verify_signature(decision_payload(review,attestation,attestation_envelope),envelope,grant=grant,purpose='recovery-decision',now_ms=now_ms)
        if proof['principal_id']!=packet['operator_id'] or proof['operation_sha256']!=packet['operation_sha256']:
            raise AdvisoryError('Recovery operator binding rejected')
        evidence=None
        if attestation is not None:
            evidence=_verify_usage(connection,ledger,attestation,attestation_envelope,grant=issuer_grant,now_ms=now_ms)
            if issuer_grant.principal_id==grant.principal_id or issuer_grant.public_key==grant.public_key:
                raise AdvisoryError('Independent usage issuer required')
        raw=canonical({'version':'1','review':review.hex(),'signature':envelope.hex(),
            'attestation':None if evidence is None else attestation.hex(),
            'attestation_signature':None if evidence is None else attestation_envelope.hex()})
        with journal(path) as db:
            scope(db,packet['operation_sha256'])
            old=db.execute('SELECT payload,digest FROM decisions WHERE review_id=?',(packet['review_id'],)).fetchone()
            if old is not None:
                if old!=(raw,sha(raw)):
                    raise AdvisoryError('Recovery review ID conflict')
                return old[1]
            if db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]>=10000:
                raise AdvisoryError('Recovery decision capacity reached')
            db.execute('INSERT INTO decisions(review_id,recorded_at_ms,payload,digest) VALUES (?,?,?,?)',
                       (packet['review_id'],now_ms,raw,sha(raw)))
    return sha(raw)


def decision_history(path, *, operation_sha256, after=0, limit=100):
    integer(after,0,10**18);integer(limit,1,100)
    with journal(path) as db:
        scope(db,operation_sha256)
        rows=db.execute('SELECT sequence,recorded_at_ms,payload,digest FROM decisions WHERE sequence>? ORDER BY sequence LIMIT ?',
                        (after,limit)).fetchall()
        result=[]
        for sequence,recorded_at,raw,digest in rows:
            integer(recorded_at,0,10**18)
            if type(raw) is not bytes or sha(raw)!=digest:
                raise AdvisoryError('Recovery decision record rejected')
            result.append({'sequence':sequence,'recorded_at_ms':recorded_at,'digest':digest,'record':json.loads(raw)})
        return result
