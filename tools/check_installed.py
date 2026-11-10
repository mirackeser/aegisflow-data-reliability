# SPDX-License-Identifier: Apache-2.0
"""Exercise the installed CLI from a directory outside the source checkout."""
import json
from importlib.metadata import distribution
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
    dist = distribution("aegisflow-data-reliability")
    if dist.metadata.get("License-Expression") != "Apache-2.0":
        raise RuntimeError("Installed license metadata is inconsistent")
    for filename in ("LICENSE", "NOTICE"):
        matches = [entry for entry in dist.files or ()
                   if str(entry).endswith(".dist-info/licenses/" + filename)]
        if len(matches) != 1 or not dist.locate_file(matches[0]).is_file():
            raise RuntimeError("Installed license file missing: " + filename)
    gateway = subprocess.run([sys.executable, "-m", "aegisflow_dr", "gateway-demo"],
                             capture_output=True, text=True, check=True, timeout=20)
    result = json.loads(gateway.stdout)
    if result["outcome"] != "OK" or result["report"]["status"] != "PASS":
        raise RuntimeError("Installed gateway demo failed")
    catalog = subprocess.run([sys.executable, "-m", "aegisflow_dr", "catalog"],
                             capture_output=True, text=True, check=True)
    if "36 planned specialist roles" not in catalog.stdout:
        raise RuntimeError("Installed catalog validation failed")
    for arguments, exit_code, status in SCENARIOS:
        result = subprocess.run([sys.executable, "-m", "aegisflow_dr", *arguments],
                                capture_output=True, text=True, timeout=20)
        if result.returncode != exit_code or json.loads(result.stdout)["status"] != status:
            raise RuntimeError(f"Installed CLI regression: {arguments}")
    print("Installed license, catalog, gateway and seven diagnostic/batch scenarios passed.")


if __name__ == "__main__":
    main()
