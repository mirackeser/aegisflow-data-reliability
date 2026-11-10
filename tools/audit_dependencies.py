# SPDX-License-Identifier: Apache-2.0
"""Audit runtime and all optional-profile requirements from one authoritative project manifest."""
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import tomllib


def requirements(path: Path) -> list[str]:
    project = tomllib.loads(path.read_text(encoding='utf-8'))['project']
    runtime = project['dependencies']
    groups = project['optional-dependencies']
    test = groups['test']
    if any(type(group) is not list for group in groups.values()):
        raise ValueError('Invalid optional dependency group')
    optional = [item for group in groups.values() for item in group]
    if (type(runtime) is not list or type(test) is not list or not runtime or not test
            or any(type(item) is not str or not item.strip() or '\n' in item or '\r' in item
                   for item in runtime + optional)):
        raise ValueError('Invalid project dependency declaration')
    return sorted(set(runtime + optional))


def audit(path: Path) -> int:
    declared = requirements(path)
    with TemporaryDirectory() as temporary:
        manifest = Path(temporary) / 'requirements.txt'
        manifest.write_text('\n'.join(declared) + '\n')
        return subprocess.run([sys.executable, '-m', 'pip_audit', '--strict', '--progress-spinner', 'off', '--cache-dir', str(Path(temporary) / 'cache'),
                               '-r', str(manifest)], check=False).returncode


if __name__ == '__main__':
    raise SystemExit(audit(Path('pyproject.toml')))
