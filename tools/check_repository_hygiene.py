# SPDX-License-Identifier: Apache-2.0
"""Inspect tracked files without printing matching content or following symlinks."""
from __future__ import annotations

import argparse
from hashlib import sha256
import io
from pathlib import Path, PurePosixPath
import re
import subprocess

LOCAL_PATH = re.compile(r"/(?:Users|home)/[^\s<>\"']+")
INTERNAL = re.compile(r"data-dil-|chatgpt-mermaid-|chatgpt-content-reference|radix-_r_|"
                      r"conversation_id|message_id|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PRIVATE_SUFFIXES = {'.pem', '.key', '.p12', '.pfx', '.db', '.sqlite', '.sqlite3', '.har', '.log'}
PRIVATE_PARTS = {'.aws', '.ssh', '.kube', '.venv', '__pycache__', 'build', 'dist', 'work'}


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted or reader.attachments:
        raise ValueError('Encrypted or attached PDF content requires explicit review')
    return str(dict(reader.metadata or {})) + '\n' + '\n'.join(
        page.extract_text() or '' for page in reader.pages)


def inspect_files(root: Path, paths: list[str]) -> list[tuple[str, str]]:
    findings = []
    for relative in paths:
        path = PurePosixPath(relative)
        if path.is_absolute() or '..' in path.parts:
            findings.append((relative, 'invalid tracked path'))
            continue
        local = root.joinpath(*path.parts)
        if local.is_symlink():
            findings.append((relative, 'tracked symlink requires review'))
            continue
        name = path.name
        if (any(part in PRIVATE_PARTS or part.endswith('.egg-info') for part in path.parts)
                or path.suffix.lower() in PRIVATE_SUFFIXES
                or name.endswith(('.db-journal', '.db-wal', '.db-shm', '.pyc'))
                or (name.startswith('.env') and name not in {'.env.example', '.env.template'})):
            findings.append((relative, 'private or generated file is tracked'))
            continue
        data = local.read_bytes()
        if path.suffix.lower() == '.pdf':
            try:
                text = pdf_text(data)
            except Exception:
                findings.append((relative, 'PDF extraction or attachment check failed'))
                continue
        else:
            try:
                text = data.decode('utf-8')
            except UnicodeDecodeError:
                continue
        if LOCAL_PATH.search(text):
            findings.append((relative, 'personal absolute path'))
        # Restrict archival provenance checks; legitimate product code can use UUIDs.
        if (relative.startswith('docs/source/') or path.suffix.lower() in {'.svg', '.pdf'}):
            if INTERNAL.search(text):
                findings.append((relative, 'internal chat or renderer residue'))
    return findings


def export_pdf_history(root: Path, destination: Path) -> int:
    """Extract every reachable historical PDF blob for redacted secret scanning."""
    destination.mkdir(parents=True, exist_ok=True)
    listing = subprocess.check_output(['git', 'rev-list', '--objects', '--all'], cwd=root)
    seen = set()
    for line in listing.decode('utf-8').splitlines():
        fields = line.split(' ', 1)
        if len(fields) != 2 or not fields[1].lower().endswith('.pdf'):
            continue
        object_id = fields[0]
        if object_id in seen:
            continue
        if not re.fullmatch(r'[0-9a-f]{40,64}', object_id):
            raise ValueError('Invalid git object id')
        data = subprocess.check_output(['git', 'cat-file', 'blob', object_id], cwd=root)
        text = pdf_text(data)
        (destination / (sha256(data).hexdigest() + '.txt')).write_text(text, encoding='utf-8')
        seen.add(object_id)
    return len(seen)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--pdf-text-dir', type=Path, required=True)
    args = parser.parse_args()
    root = Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel']).decode().strip())
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    findings = inspect_files(root, [path for path in paths if path])
    for path, reason in findings:
        print(f'{path}: {reason}')
    if findings:
        return 1
    count = export_pdf_history(root, args.pdf_text_dir)
    print(f'Tracked file hygiene passed; extracted {count} historical PDF blobs for secret scanning.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
