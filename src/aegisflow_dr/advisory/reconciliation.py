# SPDX-License-Identifier: Apache-2.0
"""Explicit signed accounting reconciliation; delivery uncertainty remains blocked."""
from .contracts import AdvisoryError,decode,encode
from .recovery_auth import verify_signature,_verify_usage
from .usage import UsageLedger,database,integer
from ..storage.store import sha

SCHEMA = (
    'CREATE TABLE reconciliations (sequence INTEGER PRIMARY KEY, attempt_id TEXT UNIQUE NOT NULL, approval_id TEXT UNIQUE NOT NULL, payload BLOB NOT NULL, digest TEXT NOT NULL)',
    "CREATE TRIGGER reconciliations_update BEFORE UPDATE ON reconciliations BEGIN SELECT RAISE(ABORT,'Append only'); END",
    "CREATE TRIGGER reconciliations_delete BEFORE DELETE ON reconciliations BEGIN SELECT RAISE(ABORT,'Append only'); END",
)


def _record(raw, digest):
    if type(raw) is not bytes or sha(raw)!=digest:
        raise AdvisoryError('Reconciliation record integrity rejected')
    value=decode('usage-reconciliation-record',raw)
    integer(value['recorded_at_ms'],0,10**18)
    approval=decode('usage-reconciliation',bytes.fromhex(value['approval']))
    attestation=decode('usage-attestation',bytes.fromhex(value['attestation']))
    if (approval['attempt_id']!=attestation['attempt_id'] or
            any(approval[k]!=attestation[k] for k in ('operation_sha256','snapshot_sha256','assessment_sha256')) or
            approval['attestation_sha256']!=sha(bytes.fromhex(value['attestation'])) or
            approval['attestation_signature_sha256']!=sha(bytes.fromhex(value['attestation_signature']))):
        raise AdvisoryError('Reconciliation evidence binding rejected')
    return value,approval,attestation


def project_accounting(connection, rows, operation):
    """Validate historical receipts; project charges without rewriting delivery state."""
    records=connection.execute('SELECT * FROM reconciliations LIMIT 100001').fetchall()
    if len(records)>len(rows):
        raise AdvisoryError('Reconciliation history rejected')
    projected={row['attempt_id']:dict(row) for row in rows}
    for record in records:
        _,approval,evidence=_record(record['payload'],record['digest'])
        row=projected.get(record['attempt_id'])
        if (row is None or row['status'] not in ('UNKNOWN','IN_FLIGHT') or
                approval['approval_id']!=record['approval_id'] or approval['attempt_id']!=record['attempt_id'] or
                approval['operation_sha256']!=operation or
                any(evidence[k]!=row[k] for k in ('request_sha256','input_sha256','quote_sha256'))):
            raise AdvisoryError('Reconciliation attempt binding rejected')
        integer(evidence['input_tokens'],0,row['input_cap']);integer(evidence['output_tokens'],0,row['output_cap'])
        row.update(status='SETTLED',actual_input=evidence['input_tokens'],actual_output=evidence['output_tokens'],
            charged_tokens=evidence['input_tokens']+evidence['output_tokens'],
            charged_cost_nusd=evidence['input_tokens']*row['input_rate']+evidence['output_tokens']*row['output_rate'])
    return list(projected.values())


def reconcile_usage(ledger, approval, signature, attestation, attestation_signature, *, grant, issuer_grant, now_ms):
    """Atomically record verified accounting. Never dispatch or change route outcomes."""
    if type(ledger) is not UsageLedger or ledger.version!=4:
        raise AdvisoryError('Explicit reconciliation profile required')
    if any(type(value) is not bytes for value in (approval,signature,attestation,attestation_signature)):
        raise AdvisoryError('Exact reconciliation evidence bytes required')
    packet=decode('usage-reconciliation',approval)
    proof=verify_signature(approval,signature,grant=grant,purpose='reconcile-usage',now_ms=now_ms)
    if (proof['principal_id']!=packet['operator_id'] or proof['operation_sha256']!=packet['operation_sha256'] or
            packet['operation_sha256']!=sha(ledger.operation.payload) or
            packet['attestation_sha256']!=sha(attestation) or
            packet['attestation_signature_sha256']!=sha(attestation_signature)):
        raise AdvisoryError('Reconciliation authorization binding rejected')
    issuer=verify_signature(attestation,attestation_signature,grant=issuer_grant,purpose='usage-attestation',now_ms=now_ms)
    if (grant.principal_id==issuer_grant.principal_id or grant.public_key==issuer_grant.public_key or
            issuer['operation_sha256']!=packet['operation_sha256']):
        raise AdvisoryError('Independent reconciliation issuer required')
    with database(ledger.path) as connection:
        ledger._validate(connection)
        existing=connection.execute('SELECT * FROM reconciliations WHERE attempt_id=? OR approval_id=?',
                                    (packet['attempt_id'],packet['approval_id'])).fetchone()
        if existing is not None:
            value,_,_=_record(existing['payload'],existing['digest'])
            if any(value[k]!=v.hex() for k,v in (('approval',approval),('signature',signature),
                    ('attestation',attestation),('attestation_signature',attestation_signature))):
                raise AdvisoryError('Reconciliation replay conflict')
            return existing['digest']
        _verify_usage(connection,ledger,attestation,attestation_signature,grant=issuer_grant,now_ms=now_ms)
        value=decode('usage-attestation',attestation)
        if (packet['attempt_id']!=value['attempt_id'] or
                any(packet[k]!=value[k] for k in ('snapshot_sha256','assessment_sha256'))):
            raise AdvisoryError('Reconciliation snapshot binding rejected')
        now=ledger._now(connection)
        if now_ms!=now:
            raise AdvisoryError('Reconciliation clock mismatch')
        raw=encode('usage-reconciliation-record',{'approval':approval.hex(),'signature':signature.hex(),
            'attestation':attestation.hex(),'attestation_signature':attestation_signature.hex(),'recorded_at_ms':now})
        connection.execute('INSERT INTO reconciliations(attempt_id,approval_id,payload,digest) VALUES (?,?,?,?)',
                           (packet['attempt_id'],packet['approval_id'],raw,sha(raw)))
        ledger._validate(connection)
    return sha(raw)


def reconciliation_history(ledger, *, after=0, limit=100):
    if type(ledger) is not UsageLedger or ledger.version!=4:
        raise AdvisoryError('Bounded reconciliation cursor required')
    integer(after,0,10**18);integer(limit,1,100)
    with database(ledger.path) as connection:
        ledger._validate(connection)
        rows=connection.execute('SELECT * FROM reconciliations WHERE sequence>? ORDER BY sequence LIMIT ?',
                                (after,limit)).fetchall()
        return [{'sequence':row['sequence'],'attempt_id':row['attempt_id'],'digest':row['digest'],
                 'record':_record(row['payload'],row['digest'])[0]} for row in rows]
