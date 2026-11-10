# SPDX-License-Identifier: Apache-2.0
"""Bounded scheduler state and validated metadata results."""
from dataclasses import asdict, dataclass, field
import re

from ..coordination.contracts import encode, parse
from ..storage.store import canonical

MAX_TIME = 9_000_000_000_000_000
MAX_BYTES = 32_768
MAX_EVENTS = 128
MAX_ACTIVE = 128
TERMINAL = frozenset({'SUCCEEDED', 'FAILED', 'CANCELLED', 'BLOCKED'})
REASONS = frozenset({'TEMPORARY_UNAVAILABLE', 'LEASE_EXPIRED', 'INTEGRITY_FAILURE',
                     'VERSION_MISMATCH', 'EVIDENCE_UNAVAILABLE', 'INTERNAL_ERROR',
                     'DEPENDENCY_FAILED', 'OPERATOR_CANCELLED'})


class QueueError(ValueError):
    pass


class QueueIntegrityError(QueueError):
    pass


class LeaseLost(QueueError):
    """The reservation is expired, cancelled, replaced or already consumed."""


def identifier(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', value):
        raise QueueError('Invalid local identifier')
    return value


def uuid(value):
    if type(value) is not str or not re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', value):
        raise QueueError('Invalid job identity')
    return value


def digest(value):
    return type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def milliseconds(value):
    if type(value) is not int or not 0 <= value <= MAX_TIME - 3_600_000:
        raise QueueError('Invalid scheduler clock')
    return value


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_ms: int = 1000
    max_delay_ms: int = 60_000

    def __post_init__(self):
        if (type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 5
                or type(self.base_delay_ms) is not int or not 1 <= self.base_delay_ms <= 60_000
                or type(self.max_delay_ms) is not int or not self.base_delay_ms <= self.max_delay_ms <= 3_600_000):
            raise QueueError('Invalid retry policy')

    def delay(self, attempt):
        return min(self.base_delay_ms * 2 ** (attempt - 1), self.max_delay_ms)

    def mapping(self):
        return asdict(self)


@dataclass(frozen=True)
class Lease:
    job_id: str
    task_id: str
    fence: int
    owner: str
    token: str = field(repr=False)


def initial(now):
    task = {'state': 'PENDING', 'attempt': 0, 'fence': 0, 'owner': None,
            'lease_hash': None, 'lease_until_ms': None, 'renewals': 0,
            'ready_at_ms': now, 'result': None, 'reason': None}
    return {'cancelled': False, 'updated_ms': now,
            'tasks': {'collect': dict(task), 'judge': dict(task)}}


def status(projection):
    tasks = projection['tasks'].values()
    if projection['cancelled']:
        return 'CANCELLED'
    if any(t['state'] in {'FAILED', 'BLOCKED'} for t in tasks):
        return 'FAILED'
    if all(t['state'] == 'SUCCEEDED' for t in tasks):
        return 'SUCCEEDED'
    return 'RUNNING' if any(t['attempt'] for t in tasks) else 'QUEUED'


def validate_result(key, result, manifest):
    request = manifest['request']
    if key == 'collect':
        if (type(result) is not dict or set(result) != {'run_id', 'record_sha256'}
                or result['run_id'] != request['proposal']['run_id']
                or result['record_sha256'] != request['record_sha256']):
            raise QueueError('Invalid evidence pointer')
    else:
        result = parse('verdict', encode('verdict', result))
        if (result['run_id'] != request['proposal']['run_id']
                or result['record_sha256'] != request['record_sha256']):
            raise QueueError('Invalid Judge result binding')
    return result


def validate_projection(value, manifest):
    if (type(value) is not dict or set(value) != {'cancelled', 'updated_ms', 'tasks'}
            or type(value['cancelled']) is not bool or type(value['tasks']) is not dict
            or set(value['tasks']) != {'collect', 'judge'}):
        raise QueueError('Invalid queue projection')
    milliseconds(value['updated_ms'])
    expected_fields = set(initial(0)['tasks']['collect'])
    for key, task in value['tasks'].items():
        if (type(task) is not dict or set(task) != expected_fields
                or task['state'] not in {'PENDING', 'LEASED', 'RETRY_WAIT', *TERMINAL}
                or type(task['attempt']) is not int or not 0 <= task['attempt'] <= manifest['request']['retry']['max_attempts']
                or type(task['fence']) is not int or task['fence'] != task['attempt']
                or type(task['renewals']) is not int or not 0 <= task['renewals'] <= 3
                or task['reason'] is not None and task['reason'] not in REASONS):
            raise QueueError('Invalid task projection')
        milliseconds(task['ready_at_ms'])
        if task['owner'] is not None:
            identifier(task['owner'])
        if task['state'] == 'LEASED':
            if not digest(task['lease_hash']) or task['owner'] is None or task['attempt'] == 0:
                raise QueueError('Invalid reservation')
            milliseconds(task['lease_until_ms'])
        elif task['lease_hash'] is not None or task['lease_until_ms'] is not None:
            raise QueueError('Inactive reservation retained')
        if task['state'] == 'SUCCEEDED':
            validate_result(key, task['result'], manifest)
        elif task['result'] is not None:
            raise QueueError('Result without completion')
        state, attempt = task['state'], task['attempt']
        if state == 'PENDING' and (attempt or task['owner'] is not None or task['reason'] is not None):
            raise QueueError('Pending task has execution metadata')
        if state in {'LEASED', 'SUCCEEDED', 'FAILED', 'RETRY_WAIT'} and (not attempt or task['owner'] is None):
            raise QueueError('Executed task has no reservation history')
        if state in {'LEASED', 'SUCCEEDED'} and task['reason'] is not None:
            raise QueueError('Successful or reserved task has a failure reason')
        if state == 'RETRY_WAIT' and (attempt >= manifest['request']['retry']['max_attempts']
                                      or task['reason'] not in {'TEMPORARY_UNAVAILABLE', 'LEASE_EXPIRED'}):
            raise QueueError('Retry is not eligible')
        if state == 'FAILED' and task['reason'] not in REASONS - {'DEPENDENCY_FAILED', 'OPERATOR_CANCELLED'}:
            raise QueueError('Failed task has no failure reason')
        if state == 'BLOCKED' and (key != 'judge' or attempt or task['reason'] != 'DEPENDENCY_FAILED'
                                   or value['tasks']['collect']['state'] != 'FAILED'):
            raise QueueError('Invalid dependency block')
        if state == 'CANCELLED' and (not value['cancelled'] or task['reason'] != 'OPERATOR_CANCELLED'):
            raise QueueError('Invalid cancellation')
    if value['tasks']['collect']['state'] == 'FAILED' and value['tasks']['judge']['state'] != 'BLOCKED':
        raise QueueError('Failed dependency is not blocked')
    if (value['tasks']['judge']['state'] in {'LEASED', 'SUCCEEDED', 'RETRY_WAIT'}
            and value['tasks']['collect']['state'] != 'SUCCEEDED'):
        raise QueueError('Dependency not complete')
    if value['cancelled'] and any(t['state'] not in TERMINAL for t in value['tasks'].values()):
        raise QueueError('Cancellation incomplete')
    if len(canonical(value)) > MAX_BYTES:
        raise QueueError('Projection exceeds budget')
