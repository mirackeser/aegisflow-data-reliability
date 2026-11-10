"""CLI for local synthetic diagnostics and the planned role catalog."""
import argparse
from importlib.resources import files
import sys

from .pipeline import FAULTS, MAX_INPUT_BYTES, InputRejected, diagnose_csv, generate_orders
from .registry import load_catalog
from .batch import TRANSFORMS, run_batch


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
    commands.add_parser("catalog", help="Validate the 36 planned design roles")
    args = parser.parse_args(argv)
    try:
        if args.command in (None, "catalog"):
            roles = load_catalog(files("aegisflow_dr").joinpath("data/agent-catalog.json"))
            print(f"{len(roles)} planned specialist roles; runtime not implemented.")
            return 0
        if args.command in ("demo", "batch-demo"):
            payload = generate_orders(seed=args.seed, rows=args.rows, fault=args.fault)
        else:
            with open(args.path, "rb") as stream:
                payload = stream.read(MAX_INPUT_BYTES + 1)
        report = (run_batch(payload, transform=args.transform)
                  if args.command == "batch-demo" else diagnose_csv(payload))
    except (ValueError, OSError, InputRejected):
        # Never echo paths, raw rows or parsing exceptions into logs.
        print("Input rejected: use a readable, bounded synthetic UTF-8 CSV and valid options.",
              file=sys.stderr)
        return 2
    print(report.to_json())
    return 0 if report.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
