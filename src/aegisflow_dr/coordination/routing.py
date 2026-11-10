# SPDX-License-Identifier: Apache-2.0
"""Host-owned capability routing and bounded acyclic task dependencies."""
from dataclasses import dataclass
import re
from types import MappingProxyType

from .contracts import encode, parse


class RoutingError(ValueError):
    pass


@dataclass(frozen=True)
class Worker:
    agent_id: str
    capability: str
    tags: frozenset[str]

    def __post_init__(self):
        if (type(self.agent_id) is not str or not re.fullmatch(r'A(?:0[1-9]|[12][0-9]|3[0-6])', self.agent_id)
                or type(self.capability) is not str or self.capability not in {'evidence.read', 'assessment.review'}
                or type(self.tags) is not frozenset or not self.tags
                or not self.tags <= {'read-only', 'deterministic', 'verification', 'retained-evidence'}):
            raise RoutingError('Invalid host worker registration')


LOCAL_WORKERS = (
    Worker('A26', 'evidence.read', frozenset({'read-only', 'deterministic', 'retained-evidence'})),
    Worker('A27', 'assessment.review', frozenset({'read-only', 'deterministic', 'verification'})),
)


class TaskGraph:
    """Local scheduling primitive; no durable delivery, network identity or retries."""
    def __init__(self, tasks: list[dict], *, workers: tuple[Worker, ...] = LOCAL_WORKERS):
        if type(tasks) is not list or not 1 <= len(tasks) <= 8:
            raise RoutingError('Task graph size rejected')
        if (type(workers) is not tuple or not workers or any(type(w) is not Worker for w in workers)
                or len({(w.agent_id, w.capability) for w in workers}) != len(workers)):
            raise RoutingError('Worker registry rejected')
        decoded = [parse('task', encode('task', task)) for task in tasks]
        by_id = {task['task_id']: task for task in decoded}
        if (len(by_id) != len(decoded) or len({(t['run_id'], t['incident_id']) for t in decoded}) != 1):
            raise RoutingError('Duplicate task or cross-context dependency')
        assignments = {}
        for task in decoded:
            if not set(task['depends_on']) <= by_id.keys():
                raise RoutingError('Missing task dependency')
            candidates = [w for w in workers if w.capability == task['capability']
                          and set(task['required_tags']) <= w.tags]
            if len(candidates) != 1:
                raise RoutingError('Capability unavailable or ambiguous')
            assignments[task['task_id']] = candidates[0]
        ordered = []
        while len(ordered) < len(decoded):
            ready = sorted(key for key, task in by_id.items()
                           if key not in ordered and set(task['depends_on']) <= set(ordered))
            if not ready:
                raise RoutingError('Cyclic task dependency')
            ordered.extend(ready)
        # Keep detached immutable bytes: caller mutation cannot alter the plan.
        self._tasks = MappingProxyType({key: encode('task', task) for key, task in by_id.items()})
        self.assignments = MappingProxyType(assignments)
        self.order = tuple(ordered)

    def task(self, task_id):
        return parse('task', self._tasks[task_id])

    def ready(self, completed: frozenset[str], failed: frozenset[str] = frozenset()) -> tuple[str, ...]:
        if (type(completed) is not frozenset or type(failed) is not frozenset
                or completed & failed or not completed | failed <= self._tasks.keys()):
            raise RoutingError('Invalid scheduler state')
        if any(not set(self.task(key)['depends_on']) <= completed for key in completed):
            raise RoutingError('Completed task has unfinished dependencies')
        return tuple(key for key in self.order if key not in completed | failed
                     and set(self.task(key)['depends_on']) <= completed)
