# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from audit_dependencies import requirements, audit


class DependencyAuditTests(unittest.TestCase):
    def test_runtime_and_test_requirements_share_the_project_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'pyproject.toml'
            path.write_text('[project]\ndependencies=["alpha==1"]\n[project.optional-dependencies]\ntest=["beta==2","alpha==1"]\n')
            self.assertEqual(requirements(path),['alpha==1','beta==2'])

    def test_malformed_or_missing_groups_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'pyproject.toml'
            for content in ['[project]\ndependencies=[]\n[project.optional-dependencies]\ntest=["beta==2"]\n',
                            '[project]\ndependencies=[1]\n[project.optional-dependencies]\ntest=["beta==2"]\n',
                            '[project]\ndependencies=["alpha==1\\n--index-url=untrusted"]\n[project.optional-dependencies]\ntest=["beta==2"]\n']:
                path.write_text(content)
                with self.assertRaises(ValueError):requirements(path)
            path.write_text('[project]\ndependencies=["alpha==1"]\n')
            with self.assertRaises(KeyError):requirements(path)

    def test_failed_audit_propagates_and_temporary_manifest_is_removed(self):
        observed=[]
        def execute(args,**kwargs):
            path=Path(args[-1]);observed.append(path)
            self.assertIn('cryptography==50.0.2',path.read_text())
            self.assertIn('--strict',args)
            return type('Result',(),{'returncode':1})()
        with patch('audit_dependencies.subprocess.run',side_effect=execute):
            self.assertEqual(audit(Path('pyproject.toml')),1)
        self.assertFalse(observed[0].exists())
