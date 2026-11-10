"""Exercise the installed CLI from a directory outside the source checkout."""
import json
import subprocess
import sys

SCENARIOS = [
    (["demo"], 0, "PASS"),
    (["demo", "--fault", "schema_drift"], 1, "FAIL"),
    (["demo", "--fault", "null_total"], 1, "FAIL"),
    (["demo", "--fault", "duplicate_order"], 1, "FAIL"),
    (["batch-demo"], 0, "PASS"),
    (["batch-demo", "--transform", "exclude_first"], 1, "FAIL"),
    (["batch-demo", "--fault", "schema_drift"], 1, "BLOCKED"),
]


def main() -> None:
    catalog = subprocess.run([sys.executable, "-m", "aegisflow_dr", "catalog"],
                             capture_output=True, text=True, check=True)
    if "36 planned specialist roles" not in catalog.stdout:
        raise RuntimeError("Installed catalog validation failed")
    for arguments, exit_code, status in SCENARIOS:
        result = subprocess.run([sys.executable, "-m", "aegisflow_dr", *arguments],
                                capture_output=True, text=True, timeout=20)
        if result.returncode != exit_code or json.loads(result.stdout)["status"] != status:
            raise RuntimeError(f"Installed CLI regression: {arguments}")
    print("Installed catalog and seven diagnostic/batch scenarios passed.")


if __name__ == "__main__":
    main()
