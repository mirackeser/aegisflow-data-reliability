# SPDX-License-Identifier: Apache-2.0
"""A2A 1.0 stateless review profile using the official SDK's generated protobuf models.

Install the a2a extra. This module does not implement a general A2A task server.
"""
import json
from uuid import UUID, uuid4

from a2a.types import a2a_pb2 as pb
from google.protobuf import json_format

from ..coordination.contracts import MAX_MESSAGE_BYTES, encode, parse
from ..integration.secure_review import handle_review
from ..security.policy import AccessPolicy, EgressPolicy
from ..storage.store import canonical

VERSION = '1.0'
SEND_PATH = '/message:send'


class ProtocolError(ValueError):
    """Sanitized protocol/profile rejection, without remote values or SDK details."""


def _require(condition):
    if not condition:
        raise ProtocolError('A2A review profile rejected')


def _identifier(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except ValueError:
        return False


def _pairs(values):
    result = {}
    for name, value in values:
        _require(name not in result)
        result[name] = value
    return result


def _constant(value):
    raise ProtocolError('Nonfinite A2A JSON rejected')


def _load(payload, model):
    _require(type(payload) is bytes and len(payload) <= MAX_MESSAGE_BYTES)
    try:
        raw = json.loads(payload.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
        _require(type(raw) is dict)
        # Strict parsing rejects unknown fields before any SDK compatibility decoder.
        decoded = json_format.ParseDict(raw, model, ignore_unknown_fields=False, max_recursion_depth=32)
        return raw, decoded
    except (ValueError, TypeError, RecursionError, json_format.ParseError):
        raise ProtocolError('A2A message rejected') from None


def wire(model) -> bytes:
    _require(isinstance(model, (pb.SendMessageRequest, pb.SendMessageResponse, pb.AgentCard)))
    try:
        data = canonical(json_format.MessageToDict(model))
        _require(len(data) <= MAX_MESSAGE_BYTES)
        return data
    except (ValueError, TypeError, RecursionError, json_format.SerializeToJsonError):
        raise ProtocolError('A2A encoding rejected') from None


def _part(value):
    _require(type(value) is dict and set(value) == {'data', 'mediaType'}
             and value['mediaType'] == 'application/json' and type(value['data']) is dict)
    return value['data']


def _payload(name, value):
    try:
        return parse(name, canonical(value))
    except (ValueError, TypeError, RecursionError):
        raise ProtocolError('A2A application payload rejected') from None


def decode_request(payload: bytes):
    raw, request = _load(payload, pb.SendMessageRequest())
    _require(set(raw) == {'message', 'configuration'})
    message, config = raw['message'], raw['configuration']
    _require(type(message) is dict and set(message) == {'messageId', 'contextId', 'role', 'parts'}
             and _identifier(message['messageId']) and _identifier(message['contextId'])
             and message['role'] == 'ROLE_USER' and type(message['parts']) is list and len(message['parts']) == 1)
    _require(type(config) is dict and set(config) <= {'acceptedOutputModes', 'historyLength', 'returnImmediately'}
             and config.get('acceptedOutputModes') == ['application/json']
             and type(config.get('historyLength', 0)) is int and config.get('historyLength', 0) == 0
             and type(config.get('returnImmediately', False)) is bool and not config.get('returnImmediately', False))
    proposal = _payload('proposal', _part(message['parts'][0]))
    _require(message['contextId'] == proposal['incident_id'])
    return request, proposal


def make_request(payload: bytes) -> pb.SendMessageRequest:
    proposal = parse('proposal', payload)
    request = pb.SendMessageRequest(
        message=pb.Message(message_id=str(uuid4()), context_id=proposal['incident_id'], role=pb.ROLE_USER,
                           parts=[pb.Part(media_type='application/json')]),
        configuration=pb.SendMessageConfiguration(accepted_output_modes=['application/json'], history_length=0))
    json_format.ParseDict(proposal, request.message.parts[0].data)
    decode_request(wire(request))
    return request


def decode_response(payload: bytes, proposal: dict):
    raw, response = _load(payload, pb.SendMessageResponse())
    _require(set(raw) == {'message'} and response.WhichOneof('payload') == 'message')
    message = raw['message']
    _require(type(message) is dict and set(message) == {'messageId', 'contextId', 'role', 'parts'}
             and _identifier(message['messageId']) and message['contextId'] == proposal['incident_id']
             and message['role'] == 'ROLE_AGENT' and type(message['parts']) is list and len(message['parts']) == 1)
    verdict = _payload('verdict', _part(message['parts'][0]))
    _require(verdict['run_id'] == proposal['run_id'])
    return response, verdict


def handle_send(peer, payload: bytes, runs, policy: AccessPolicy, *, method: str, path: str,
                versions: tuple[str, ...], content_types: tuple[str, ...]) -> bytes:
    """Host callback for POST /message:send with no protocol downgrade or task writes."""
    _require(method == 'POST' and path == SEND_PATH and type(versions) is tuple and versions == (VERSION,)
             and type(content_types) is tuple and content_types == ('application/json',))
    request, proposal = decode_request(payload)
    # Reuse the verified socket/resource gate, not A2A role labels or caller metadata.
    verdict = parse('verdict', handle_review(peer, encode('proposal', proposal), runs, policy))
    response = pb.SendMessageResponse(message=pb.Message(
        message_id=str(uuid4()), context_id=request.message.context_id, role=pb.ROLE_AGENT,
        parts=[pb.Part(media_type='application/json')]))
    json_format.ParseDict(verdict, response.message.parts[0].data)
    data = wire(response)
    decode_response(data, proposal)
    return data


def agent_card(endpoint: EgressPolicy) -> pb.AgentCard:
    """Host-generated capability declaration; never fetches or trusts a remote target."""
    _require(type(endpoint) is EgressPolicy and endpoint.path == SEND_PATH)
    card = pb.AgentCard(
        name='AegisFlow Retained Assessment Review',
        description='Synchronous metadata-only review; no task, file, streaming or push operations.',
        version='0.1.0', capabilities=pb.AgentCapabilities(),
        supported_interfaces=[pb.AgentInterface(url=f'https://{endpoint.hostname}:{endpoint.port}',
            protocol_binding='HTTP+JSON', protocol_version=VERSION)],
        default_input_modes=['application/json'], default_output_modes=['application/json'],
        skills=[pb.AgentSkill(id='retained-review', name='Retained assessment review',
            description='Send one proposal-v1 object as a JSON data part and receive a verdict-v1 data part.',
            tags=['data-reliability', 'read-only'])])
    card.security_schemes['mtls'].mtls_security_scheme.description = 'Mutual TLS and exact leaf/incident/run grants'
    card.security_requirements.add().schemes['mtls'].list.extend([])
    return card
