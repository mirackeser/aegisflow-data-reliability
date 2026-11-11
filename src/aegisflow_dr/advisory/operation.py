# SPDX-License-Identifier: Apache-2.0
"""Immutable, host-approved logical operation identity and model eligibility."""
from dataclasses import dataclass

from .context import PreparedAdvisory
from .contracts import AdvisoryError, decode, encode


def identity(prepared):
    if type(prepared) is not PreparedAdvisory:
        raise AdvisoryError('Trusted prepared operation input required')
    request = decode('request', prepared.request)
    manifest = prepared.manifest
    return {**{key: request[key] for key in
               ('run_id', 'incident_id', 'record_sha256', 'prompt_sha256')},
            'evidence_sha256': sorted(request['evidence_sha256']),
            **{key: manifest[key] for key in ('context_sha256', 'response_schema_sha256')}}


@dataclass(frozen=True)
class OperationBinding:
    """Persist only metadata hashes and host grants, never source data or prompts."""
    payload: bytes

    def __post_init__(self):
        decode('operation', self.payload)

    def admit(self, prepared, deadline_ms):
        value = decode('operation', self.payload)
        request = decode('request', prepared.request)
        if (deadline_ms != value['deadline_ms'] or request['model_id'] not in value['allowed_models']
                or any(value[key] != item for key, item in identity(prepared).items())):
            raise AdvisoryError('Operation binding admission denied')


def bind_operation(prepared, *, operation_id, allowed_models, deadline_ms):
    """Explicit host approval; models cannot expand their own eligibility."""
    if type(allowed_models) is not tuple:
        raise AdvisoryError('Immutable allowed model tuple required')
    value = {'version': '1', 'operation_id': operation_id, **identity(prepared),
             'allowed_models': list(allowed_models), 'deadline_ms': deadline_ms}
    binding = OperationBinding(encode('operation', value))
    binding.admit(prepared, deadline_ms)
    return binding
