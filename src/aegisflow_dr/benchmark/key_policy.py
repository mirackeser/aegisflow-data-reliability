# SPDX-License-Identifier: Apache-2.0
"""Shared key-version disable policy with externally anchored lifecycle history."""
from hashlib import sha256
import os
from pathlib import Path

from .access_registry import _db
from .core import BenchmarkError, ID, canonical, closed, parse, validate
from .curation_auth import _time
from .identity_keys import evaluate_peer
from .quality import HASH

EMPTY = sha256(b'aegisflow/key-policy/v1').hexdigest()
CHECKPOINT = closed({'catalog_sha256':HASH, 'sequence':{'type':'integer','minimum':0,'maximum':10000}, 'event_sha256':HASH})
EVENT = closed({'catalog_sha256':HASH, 'sequence':{'type':'integer','minimum':1,'maximum':10000},
                'previous_sha256':HASH, 'key_id':ID, 'action':{'const':'DISABLED'},
                'time_ms':{'type':'integer','minimum':0,'maximum':10**18}})


def _catalog(keys):
    if type(keys) is not dict or not 1 <= len(keys) <= 64:
        raise BenchmarkError('Bounded key catalog required')
    for key_id, digest in keys.items():
        validate(ID,key_id); validate(HASH,digest)
    if len(set(keys.values())) != len(keys):
        raise BenchmarkError('Unique key materials required')
    return canonical(keys)


def initialize_key_policy(path, keys):
    raw = _catalog(keys)
    try:
        descriptor = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.close(descriptor)
    except (OSError,TypeError,ValueError):
        raise BenchmarkError('New key policy required') from None
    with _db(path) as db:
        db.execute('CREATE TABLE catalog (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)')
        db.execute('INSERT INTO catalog VALUES (1,?)',(raw,))
        db.execute('CREATE TABLE events (sequence INTEGER PRIMARY KEY, payload BLOB NOT NULL)')
        for table in ('catalog','events'):
            for action in ('UPDATE','DELETE'):
                db.execute(f"CREATE TRIGGER {table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable key policy'); END")
    return {'catalog_sha256':sha256(raw).hexdigest(),'sequence':0,'event_sha256':EMPTY}


def _state(db, checkpoint):
    validate(CHECKPOINT,checkpoint)
    if type(checkpoint['sequence']) is not int:
        raise BenchmarkError('Integer checkpoint sequence required')
    rows = db.execute('SELECT payload FROM catalog LIMIT 2').fetchall()
    if len(rows)!=1 or type(rows[0][0]) is not bytes or sha256(rows[0][0]).hexdigest()!=checkpoint['catalog_sha256']:
        raise BenchmarkError('Key catalog binding rejected')
    keys = parse(rows[0][0]); _catalog(keys)
    events = db.execute('SELECT sequence,payload FROM events ORDER BY sequence LIMIT 10001').fetchall()
    if len(events)>10000:
        raise BenchmarkError('Key lifecycle capacity exceeded')
    previous=EMPTY; disabled=set(); history=[]
    for index,(sequence,raw) in enumerate(events,1):
        event=parse(raw);validate(EVENT,event);_time(event['time_ms'])
        if (type(event['sequence']) is not int or sequence!=index or event['sequence']!=index
                or event['catalog_sha256']!=checkpoint['catalog_sha256'] or event['previous_sha256']!=previous
                or event['key_id'] not in keys or event['key_id'] in disabled):
            raise BenchmarkError('Key lifecycle chain rejected')
        previous=sha256(raw).hexdigest(); disabled.add(event['key_id']); history.append(event)
    if checkpoint['sequence']!=len(events) or checkpoint['event_sha256']!=previous:
        raise BenchmarkError('Current external key checkpoint required')
    return keys,disabled,history


def disable_key(path, *, checkpoint, key_id, now_ms):
    _time(now_ms); validate(ID,key_id)
    with _db(path) as db:
        keys,disabled,history=_state(db,checkpoint)
        if key_id not in keys:
            raise BenchmarkError('Unknown policy key')
        if key_id in disabled:
            return dict(checkpoint)
        event=_disable_event(checkpoint,key_id,now_ms)
        raw=canonical(event)
        db.execute('INSERT INTO events VALUES (?,?)',(event['sequence'],raw))
    return {'catalog_sha256':checkpoint['catalog_sha256'],'sequence':event['sequence'],'event_sha256':sha256(raw).hexdigest()}


def key_history(path, *, checkpoint):
    with _db(path) as db:
        return _state(db,checkpoint)[2]


def evaluate_with_key_policy(policy_path, binding_path, registry_path, snapshot_path, *, checkpoint,
                             resolve_key, **request):
    paths=[Path(p).resolve() for p in (policy_path,binding_path,registry_path)]
    if len(set(paths))!=3:
        raise BenchmarkError('Separate policy registries required')
    with _db(policy_path) as db:
        keys,disabled,_=_state(db,checkpoint)
        def approved_key(access):
            if access.key_id not in keys or access.key_id in disabled:
                raise BenchmarkError('Key policy denied')
            key=resolve_key(access)
            if type(key) is not bytes or len(key)!=32 or sha256(key).hexdigest()!=keys[access.key_id]:
                raise BenchmarkError('Policy key material rejected')
            return key
        return evaluate_peer(binding_path,registry_path,snapshot_path,resolve_key=approved_key,**request)


def _disable_event(checkpoint, key_id, now_ms):
    return {'catalog_sha256':checkpoint['catalog_sha256'],'sequence':checkpoint['sequence']+1,
            'previous_sha256':checkpoint['event_sha256'],'key_id':key_id,'action':'DISABLED','time_ms':now_ms}
