# SPDX-License-Identifier: Apache-2.0
"""Operator commands for an explicit local review queue."""
from pathlib import Path

from ..coordination.contracts import MAX_MESSAGE_BYTES
from ..storage import IncidentStore
from ..storage.runs import InvestigationRuns
from .model import RetryPolicy
from .queue import ReviewQueue
from .schema import initialize
from .worker import enqueue_review, work_once

COMMANDS = frozenset({'queue-init', 'submit-review', 'read-job', 'cancel-job', 'recover-job', 'work-once'})


def register(commands):
    for name in sorted(COMMANDS):
        operation = commands.add_parser(name, help='Operate on a separate local durable review queue')
        operation.add_argument('--queue', required=True)
        if name in {'read-job', 'cancel-job', 'recover-job'}:
            operation.add_argument('--job', required=True)
        if name in {'submit-review', 'work-once'}:
            operation.add_argument('--db', required=True)
        if name == 'submit-review':
            operation.add_argument('--proposal', required=True)
            operation.add_argument('--key', required=True)
            operation.add_argument('--max-attempts', type=int, choices=range(1, 6), default=3)
        if name == 'work-once':
            operation.add_argument('--owner', default='local-worker')
            operation.add_argument('--lease-ms', type=int, default=30_000)


def execute(args):
    if args.command == 'queue-init':
        initialize(Path(args.queue))
        return {'outcome': 'QUEUE_INITIALIZED'}, 0
    queue = ReviewQueue(Path(args.queue))
    if args.command == 'read-job':
        result = queue.read(args.job)
    elif args.command == 'cancel-job':
        result = queue.cancel(args.job)
    elif args.command == 'recover-job':
        result = queue.recover(args.job)
    else:
        runs = InvestigationRuns(IncidentStore(Path(args.db)))
        if args.command == 'submit-review':
            with open(args.proposal, 'rb') as stream:
                payload = stream.read(MAX_MESSAGE_BYTES + 1)
            result = enqueue_review(queue, runs, payload, request_key=args.key,
                                    retry=RetryPolicy(max_attempts=args.max_attempts))
        else:
            result = work_once(queue, runs, owner=args.owner, lease_ms=args.lease_ms)
    return result, 1 if result.get('outcome') == 'LEASE_LOST' else 0
