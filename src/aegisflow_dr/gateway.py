# SPDX-License-Identifier: Apache-2.0
"""A local tool boundary for trusted host-configured permissions and budgets."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from threading import Lock
from time import monotonic
from typing import Callable

from .batch import DATASETS, TRANSFORMS, downstream, run_batch
from .pipeline import MAX_INPUT_BYTES, InputRejected, diagnose_csv

TOOLS = frozenset({"diagnose_csv", "run_batch", "query_lineage"})


@dataclass(frozen=True)
class ToolRequest:
    tool: str
    dataset: str
    csv_text: str | None = None
    transform: str = "clean"

    @classmethod
    def from_mapping(cls, value: dict) -> ToolRequest:
        if type(value) is not dict or set(value) - {"tool", "dataset", "csv_text", "transform"}:
            raise ValueError("Invalid request fields")
        tool, dataset = value.get("tool"), value.get("dataset")
        transform = value.get("transform", "clean")
        text = value.get("csv_text")
        if type(tool) is not str or tool not in TOOLS:
            raise ValueError("Unknown tool")
        if type(dataset) is not str or dataset not in DATASETS:
            raise ValueError("Unknown dataset")
        if type(transform) is not str or transform not in TRANSFORMS:
            raise ValueError("Unknown transform")
        if tool == "query_lineage":
            if text is not None or transform != "clean":
                raise ValueError("Lineage does not accept CSV or transform options")
        elif type(text) is not str or dataset != "source_orders":
            raise ValueError("CSV tools require source_orders and CSV text")
        if tool == "diagnose_csv" and transform != "clean":
            raise ValueError("Source diagnosis does not accept a transform")
        return cls(tool, dataset, text, transform)


@dataclass(frozen=True)
class ToolPolicy:
    """Construct in trusted host code; never accept policy from an agent request."""
    grants: frozenset[tuple[str, str]]
    max_calls: int = 4
    max_input_bytes: int = MAX_INPUT_BYTES
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if type(self.grants) is not frozenset:
            raise ValueError("Grants must be immutable")
        for grant in self.grants:
            if (type(grant) is not tuple or len(grant) != 2
                    or type(grant[0]) is not str or grant[0] not in TOOLS
                    or type(grant[1]) is not str or grant[1] not in DATASETS):
                raise ValueError("Unknown grant")
        if type(self.max_calls) is not int or not 1 <= self.max_calls <= 100:
            raise ValueError("Invalid call budget")
        if type(self.max_input_bytes) is not int or not 1 <= self.max_input_bytes <= MAX_INPUT_BYTES:
            raise ValueError("Invalid byte budget")
        if (type(self.timeout_seconds) not in (int, float)
                or not math.isfinite(self.timeout_seconds)
                or not 0 < self.timeout_seconds <= 60):
            raise ValueError("Invalid deadline")


@dataclass(frozen=True)
class ToolResult:
    outcome: str
    report: dict | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, indent=2, ensure_ascii=False)


class ToolGateway:
    """One in-process investigation session; denied calls never reach a tool.

    Calls are atomically reserved before dispatch, including calls that fail.
    Deadlines are checked before/after execution, not hard task preemption.
    This is not an OS sandbox, identity provider or persistent quota store.
    """
    def __init__(self, policy: ToolPolicy, *, clock: Callable[[], float] = monotonic):
        if type(policy) is not ToolPolicy:
            raise ValueError("A trusted ToolPolicy is required")
        self._policy = policy
        self._clock = clock
        self._deadline = clock() + policy.timeout_seconds
        self._calls = 0
        self._lock = Lock()

    @property
    def calls_used(self) -> int:
        with self._lock:
            return self._calls

    def execute(self, request: ToolRequest) -> ToolResult:
        try:
            if type(request) is not ToolRequest:
                return ToolResult("INVALID_REQUEST")
            validated = ToolRequest.from_mapping({"tool": request.tool, "dataset": request.dataset,
                                                  "csv_text": request.csv_text,
                                                  "transform": request.transform})
        except (ValueError, TypeError):
            return ToolResult("INVALID_REQUEST")
        if (validated.tool, validated.dataset) not in self._policy.grants:
            return ToolResult("DENIED")
        try:
            text = validated.csv_text
            if text is not None and len(text) > self._policy.max_input_bytes:
                return ToolResult("INPUT_REJECTED")
            payload = text.encode("utf-8") if text is not None else b""
            if len(payload) > self._policy.max_input_bytes:
                return ToolResult("INPUT_REJECTED")
        except UnicodeEncodeError:
            return ToolResult("INPUT_REJECTED")
        with self._lock:
            if self._clock() >= self._deadline:
                return ToolResult("DEADLINE_EXCEEDED")
            if self._calls >= self._policy.max_calls:
                return ToolResult("BUDGET_EXCEEDED")
            self._calls += 1
        try:
            if validated.tool == "query_lineage":
                report = {"dataset": validated.dataset,
                          "potential_downstream": list(downstream(validated.dataset)),
                          "lineage_kind": "declared_dataset_dag"}
            elif validated.tool == "diagnose_csv":
                report = json.loads(diagnose_csv(payload).to_json())
            else:
                report = json.loads(run_batch(payload, transform=validated.transform).to_json())
            result = ToolResult("OK", report)
        except InputRejected:
            result = ToolResult("INPUT_REJECTED")
        except Exception:
            # Tool errors must not leak raw data, paths or exception details.
            result = ToolResult("TOOL_ERROR")
        if self._clock() >= self._deadline:
            return ToolResult("DEADLINE_EXCEEDED")
        return result
