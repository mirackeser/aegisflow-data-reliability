# SPDX-License-Identifier: Apache-2.0
"""Print the SBOM for the installed project dependencies and fail on licence or install gaps."""
import json
from pathlib import Path
import sys
import tomllib

from aegisflow_dr import supplychain


def main(path=Path("pyproject.toml"), out=None):
    project = tomllib.loads(Path(path).read_text(encoding="utf-8"))["project"]
    declared = project["dependencies"] + [d for group in project["optional-dependencies"].values() for d in group]
    roots = sorted({supplychain.parse_requirement(d)["name"] for d in declared})
    components, missing, conditional = supplychain.closure(roots)
    problems, reviews = supplychain.check(components, missing)
    sbom = supplychain.build_sbom(components, root=project["name"], root_version=project["version"])
    if out:
        Path(out).write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("components: %d, conditional (other platforms): %s" % (len(components), ", ".join(conditional) or "none"))
    for line in reviews:
        print("REVIEW", line)
    for line in problems:
        print("FAIL", line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(out=sys.argv[1] if len(sys.argv) > 1 else None))
