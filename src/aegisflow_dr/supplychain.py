# SPDX-License-Identifier: Apache-2.0
"""Dependency closure, deterministic SBOM and fail-closed licence check (work package A05).

The SBOM lists what is installed in the environment it runs in. It is not a lock file and
says nothing about vulnerabilities (``tools/audit_dependencies.py`` covers those).
"""
from importlib import metadata
import re

ALLOWED_LICENSES = frozenset({"MIT", "MIT-0", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "PSF-2.0"})
REVIEW_LICENSES = frozenset({"MPL-2.0"})
_NAMES = {"3-Clause BSD License": "BSD-3-Clause", "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0", "MIT License": "MIT", "Apache Software License": "Apache-2.0", "Apache License 2.0": "Apache-2.0",
          "BSD License": "BSD-3-Clause", "ISC License (ISCL)": "ISC", "Python Software Foundation License": "PSF-2.0"}
_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?\s*([^;]*?)\s*(?:;(.*))?$")
_EXTRA = re.compile(r"""extra\s*==\s*['"]([^'"]+)['"]""")


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirement(text):
    match = _REQUIREMENT.match(text)
    if not match:
        raise ValueError("Invalid requirement")
    name, extras, specifier, marker = match.groups()
    return {"name": normalize(name), "extras": sorted(e.strip() for e in (extras or "").split(",") if e.strip()),
            "specifier": specifier.strip(), "marker": marker.strip() if marker else None}


def license_of(meta):
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip()
    names = sorted({_NAMES.get(c.split(" :: ")[-1], c.split(" :: ")[-1]) for c in meta.get_all("Classifier") or []
                    if c.startswith("License :: ") and c.split(" :: ")[-1] != "OSI Approved"})
    if names:
        return " AND ".join(names)
    text = (meta.get("License") or "").strip()
    if text and len(text) <= 64 and "\n" not in text:
        return _NAMES.get(text, text)
    return "UNKNOWN"


def installed(name):
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    return {"name": normalize(dist.metadata["Name"]), "version": dist.version, "license": license_of(dist.metadata),
            "requires": list(dist.requires or [])}


def closure(roots, lookup=installed):
    """Return (components, missing, conditional_missing).

    ``missing`` holds dependencies reached through a requirement without a marker; those are
    real gaps. ``conditional_missing`` are only needed on other platforms or Python versions.
    """
    components, required, seen = {}, {}, set()
    queue = [(normalize(name), (), False) for name in roots]
    while queue:
        name, extras, conditional = queue.pop()
        if (name, extras, conditional) in seen:
            continue
        seen.add((name, extras, conditional))
        record = lookup(name)
        if record is None:
            required[name] = required.get(name, False) or not conditional
            continue
        components[record["name"]] = {key: record[key] for key in ("name", "version", "license")}
        for text in record["requires"]:
            req = parse_requirement(text)
            wanted = _EXTRA.findall(req["marker"] or "")
            if wanted and not set(wanted) & set(extras):
                continue
            queue.append((req["name"], tuple(req["extras"]), conditional or bool(req["marker"] and not wanted)))
    return ([components[k] for k in sorted(components)], sorted(n for n, r in required.items() if r),
            sorted(n for n, r in required.items() if not r))


def build_sbom(components, *, root="aegisflow-data-reliability", root_version="0.1.0"):
    """CycloneDX 1.5-shaped, with no timestamp or serial so equal inputs give equal bytes."""
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
            "metadata": {"component": {"type": "application", "name": root, "version": root_version}},
            "components": [{"type": "library", "name": c["name"], "version": c["version"],
                            "purl": "pkg:pypi/%s@%s" % (c["name"], c["version"]),
                            "licenses": [{"expression": c["license"]}]} for c in components]}


def license_allowed(expression, allowed=ALLOWED_LICENSES):
    """Fail closed: unknown names, parentheses and unknown operators are all rejected."""
    if not isinstance(expression, str) or not expression.strip() or "(" in expression or ")" in expression:
        return False
    return any(all(term.strip() in allowed for term in either.split(" AND ")) for either in expression.split(" OR "))


def check(components, missing=(), allowed=ALLOWED_LICENSES):
    """Return (problems, reviews). Problems fail the check; reviews need a human decision."""
    problems = ["licence not allowed: %s %s (%s)" % (c["name"], c["version"], c["license"])
                for c in components if c["license"] not in REVIEW_LICENSES and not license_allowed(c["license"], allowed)]
    reviews = ["licence needs review: %s %s (%s)" % (c["name"], c["version"], c["license"])
               for c in components if c["license"] in REVIEW_LICENSES]
    return problems + ["not installed: %s" % name for name in missing], reviews
