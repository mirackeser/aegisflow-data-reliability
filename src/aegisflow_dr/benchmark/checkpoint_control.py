# SPDX-License-Identifier: Apache-2.0
"""Durable intent before key mutation; publish only a verified exact successor."""
from hashlib import sha256
import os
from pathlib import Path

from .access_registry import _db
from .core import BenchmarkError, ID, canonical, closed, parse, validate
from .curation_auth import TIME, _time
from .key_policy import CHECKPOINT, _disable_event, _state, disable_key, evaluate_with_key_policy, key_history

PENDING = closed({'key_id':ID,'time_ms':TIME,'next':CHECKPOINT})
STATE = closed({'version':{'const':'1'},'current':CHECKPOINT,
                'pending':{'oneOf':[{'type':'null'},PENDING]}})


def _distinct(*paths):
    if len({Path(path).resolve() for path in paths}) != len(paths):
        raise BenchmarkError('Separate checkpoint control paths required')


def _next(current, key_id, now_ms):
    raw=canonical(_disable_event(current,key_id,now_ms))
    return {'catalog_sha256':current['catalog_sha256'],'sequence':current['sequence']+1,
            'event_sha256':sha256(raw).hexdigest()}


def _load(db, catalog_sha256):
    rows=db.execute('SELECT payload FROM checkpoint WHERE id=1').fetchall()
    if len(rows)!=1:
        raise BenchmarkError('Checkpoint control state missing')
    state=parse(rows[0][0]);validate(STATE,state)
    current=state['current'];pending=state['pending']
    if type(current['sequence']) is not int or current['catalog_sha256']!=catalog_sha256:
        raise BenchmarkError('Checkpoint control binding rejected')
    if pending is not None:
        _time(pending['time_ms'])
        if (type(pending['next']['sequence']) is not int
                or pending['next']!=_next(current,pending['key_id'],pending['time_ms'])):
            raise BenchmarkError('Checkpoint intent rejected')
    return state


def _save(db, state):
    db.execute('UPDATE checkpoint SET payload=? WHERE id=1',(canonical(state),))


def initialize_checkpoint(path, policy_path, *, checkpoint):
    _distinct(path,policy_path)
    key_history(policy_path,checkpoint=checkpoint)
    try:
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(descriptor)
    except (OSError,TypeError,ValueError):
        raise BenchmarkError('New checkpoint control required') from None
    with _db(path) as db:
        db.execute('CREATE TABLE checkpoint (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)')
        db.execute('INSERT INTO checkpoint VALUES (1,?)',(canonical({'version':'1','current':checkpoint,'pending':None}),))
    return checkpoint['catalog_sha256']


def checkpoint_status(path, *, catalog_sha256):
    with _db(path) as db:
        return _load(db,catalog_sha256)


def managed_disable(path, policy_path, *, catalog_sha256, key_id, now_ms):
    _distinct(path,policy_path);_time(now_ms);validate(ID,key_id)
    with _db(path) as db:
        state=_load(db,catalog_sha256)
        if state['pending'] is not None:
            raise BenchmarkError('Checkpoint recovery required')
        with _db(policy_path) as policy_db:
            keys,disabled,_=_state(policy_db,state['current'])
        if key_id not in keys:
            raise BenchmarkError('Unknown policy key')
        if key_id in disabled:
            return state['current']
        state['pending']={'key_id':key_id,'time_ms':now_ms,'next':_next(state['current'],key_id,now_ms)}
        # Commit the exact intent before the policy file can change.
        _save(db,state)
    return recover_checkpoint(path,policy_path,catalog_sha256=catalog_sha256)


def recover_checkpoint(path, policy_path, *, catalog_sha256):
    _distinct(path,policy_path)
    with _db(path) as db:
        state=_load(db,catalog_sha256);pending=state['pending']
        if pending is None:
            key_history(policy_path,checkpoint=state['current'])
            return state['current']
        try:
            key_history(policy_path,checkpoint=pending['next'])
        except BenchmarkError:
            actual=disable_key(policy_path,checkpoint=state['current'],key_id=pending['key_id'],now_ms=pending['time_ms'])
            if actual!=pending['next']:
                raise BenchmarkError('Unexpected policy successor')
        key_history(policy_path,checkpoint=pending['next'])
        state['current']=pending['next'];state['pending']=None
        _save(db,state)
    return state['current']


def evaluate_managed(path, policy_path, binding_path, registry_path, snapshot_path, *, catalog_sha256,
                     resolve_key, **request):
    _distinct(path,policy_path,binding_path,registry_path)
    with _db(path) as db:
        state=_load(db,catalog_sha256)
        if state['pending'] is not None:
            raise BenchmarkError('Checkpoint recovery required')
        return evaluate_with_key_policy(policy_path,binding_path,registry_path,snapshot_path,
                                         checkpoint=state['current'],resolve_key=resolve_key,**request)
