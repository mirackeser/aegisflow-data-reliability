# SPDX-License-Identifier: Apache-2.0
"""Executors for the 36 roles, one module per layer; ``resolve`` turns a registry ``executor_ref`` into a callable."""
from importlib import import_module

from ...pipeline import InputRejected
from ..registry import role


def resolve(agent_id):
    """The ``execute(task, ctx)`` callable of ``agent_id``, imported from its registry reference."""
    module, _, function = role(agent_id).executor_ref.partition(":")
    execute = getattr(import_module(module), function, None)
    if not callable(execute) or getattr(execute, "agent_id", None) != agent_id:
        raise InputRejected("Executor does not belong to its role")
    return execute
