# SPDX-License-Identifier: Apache-2.0
"""CLI for local synthetic diagnostics and the planned role catalog."""
import argparse
from importlib.resources import files
import sys
import sqlite3
from pathlib import Path

from .pipeline import FAULTS, MAX_INPUT_BYTES, InputRejected, diagnose_csv, generate_orders
from .registry import load_catalog
from .batch import TRANSFORMS, run_batch
from .gateway import ToolGateway, ToolPolicy, ToolRequest
from .storage import IncidentStore, initialize


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AegisFlow Data Reliability research baseline")
    commands = parser.add_subparsers(dest="command")
    demo = commands.add_parser("demo", help="Generate and inspect in-memory synthetic orders")
    demo.add_argument("--fault", choices=FAULTS, default="clean")
    demo.add_argument("--seed", type=int, default=42)
    demo.add_argument("--rows", type=int, default=24)
    inspect = commands.add_parser("inspect", help="Inspect a local synthetic UTF-8 CSV")
    inspect.add_argument("path")
    batch = commands.add_parser("batch-demo", help="Run synthetic staging and SQL mart checks")
    batch.add_argument("--fault", choices=FAULTS, default="clean")
    batch.add_argument("--transform", choices=TRANSFORMS, default="clean")
    batch.add_argument("--seed", type=int, default=42)
    batch.add_argument("--rows", type=int, default=24)
    commands.add_parser("gateway-demo", help="Run a host-authorized synthetic tool call")
    commands.add_parser("catalog", help="Validate the 36 planned design roles")
    for command in ('store-init', 'record-source', 'read-incident', 'replay-incident', 'close-incident'):
        operation = commands.add_parser(command, help="Operate on an explicit local synthetic store")
        operation.add_argument('--db', required=True)
        if command == 'record-source':
            operation.add_argument('--source', required=True)
            operation.add_argument('--key', required=True)
        elif command != 'store-init':
            operation.add_argument('--incident', required=True)
        if command == 'close-incident':
            operation.add_argument('--expected-revision', type=int, required=True)
            operation.add_argument('--actor', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'store-init':
            initialize(Path(args.db))
            print('{"outcome": "INITIALIZED"}')
            return 0
        if args.command in ('record-source', 'read-incident', 'replay-incident', 'close-incident'):
            import json
            store = IncidentStore(Path(args.db))
            if args.command == 'record-source':
                with open(args.source, 'rb') as stream:
                    payload = stream.read(MAX_INPUT_BYTES + 1)
                result = store.record(payload, request_key=args.key)
            elif args.command == 'read-incident':
                result = store.read(args.incident)
            elif args.command == 'replay-incident':
                result = store.replay(args.incident)
            else:
                result = store.close(args.incident, expected_revision=args.expected_revision,
                                     actor=args.actor)
            print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
            return 1 if result.get('outcome') == 'MISMATCH' else 0
        if args.command in (None, "catalog"):
            roles = load_catalog(files("aegisflow_dr").joinpath("data/agent-catalog.json"))
            print(f"{len(roles)} planned specialist roles; runtime not implemented.")
            return 0
        if args.command == "gateway-demo":
            policy = ToolPolicy(frozenset({("run_batch", "source_orders")}), max_calls=1)
            request = ToolRequest("run_batch", "source_orders", generate_orders().decode("utf-8"))
            result = ToolGateway(policy).execute(request)
            print(result.to_json())
            return 0 if result.outcome == "OK" and result.report["status"] == "PASS" else 1
        if args.command in ("demo", "batch-demo"):
            payload = generate_orders(seed=args.seed, rows=args.rows, fault=args.fault)
        else:
            with open(args.path, "rb") as stream:
                payload = stream.read(MAX_INPUT_BYTES + 1)
        report = (run_batch(payload, transform=args.transform)
                  if args.command == "batch-demo" else diagnose_csv(payload))
    except (ValueError, OSError, InputRejected, sqlite3.DatabaseError):
        # Never echo paths, raw rows or parsing exceptions into logs.
        print("Input rejected: check synthetic input, store integrity/version and command options.",
              file=sys.stderr)
        return 2
    print(report.to_json())
    return 0 if report.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
