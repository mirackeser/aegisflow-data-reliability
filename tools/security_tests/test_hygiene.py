# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_repository_hygiene import inspect_files, pdf_text


class HygieneTests(unittest.TestCase):
    def test_sensitive_and_generated_tracked_paths_fail_without_content_disclosure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['.env.production', 'private.pem', 'work/session.json', 'build/output.py']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('sensitive-value-must-not-be-printed')
            findings = inspect_files(root, ['.env.production', 'private.pem', 'work/session.json', 'build/output.py'])
            self.assertEqual(len(findings), 4)
            self.assertNotIn('sensitive-value', str(findings))

    def test_safe_template_and_source_are_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['.env.example', 'app.py']:
                (root / name).write_text('example setting')
            self.assertEqual(inspect_files(root, ['.env.example', 'app.py']), [])

    def test_internal_archive_metadata_and_personal_paths_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'docs/source').mkdir(parents=True)
            (root / 'docs/source/raw.html').write_text('data-' + 'dil-response=')
            (root / 'notes.md').write_text('/' + 'Users/example/private/project')
            self.assertEqual(len(inspect_files(root, ['docs/source/raw.html', 'notes.md'])), 2)

    def test_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'link').symlink_to(root / 'unavailable-sensitive-target')
            self.assertEqual(inspect_files(root, ['link'])[0][1], 'tracked symlink requires review')

    def test_traversal_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(len(inspect_files(Path(directory), ['../secret', '/absolute'])), 2)

    def test_pdf_metadata_is_inspected(self):
        from pypdf import PdfWriter
        import io
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_metadata({'/Subject': 'conversation' + '_id: internal'})
        stream = io.BytesIO()
        writer.write(stream)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'document.pdf').write_bytes(stream.getvalue())
            self.assertEqual(inspect_files(root, ['document.pdf'])[0][1], 'internal chat or renderer residue')

    def test_embedded_attachments_require_review(self):
        from pypdf import PdfWriter
        import io
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_attachment('unreviewed.txt', b'example')
        stream = io.BytesIO()
        writer.write(stream)
        with self.assertRaises(ValueError): pdf_text(stream.getvalue())

    def test_every_reachable_historical_pdf_version_is_extracted(self):
        from pypdf import PdfWriter
        from check_repository_hygiene import export_pdf_history
        import subprocess
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as exported:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            for index in (1, 2):
                writer = PdfWriter()
                writer.add_blank_page(width=100, height=100)
                writer.add_metadata({'/Subject': f'historical-marker-{index}'})
                with (root / 'design.pdf').open('wb') as stream: writer.write(stream)
                subprocess.run(['git', 'add', 'design.pdf'], cwd=root, check=True)
                subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                                'commit', '-qm', f'Fixture version {index}'], cwd=root, check=True)
            self.assertEqual(export_pdf_history(root, Path(exported)), 2)
            text = ''.join(p.read_text() for p in Path(exported).glob('*.txt'))
            self.assertIn('historical-marker-1', text)
            self.assertIn('historical-marker-2', text)
