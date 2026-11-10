# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from aegisflow_dr.registry import load_catalog

class RegistryTests(unittest.TestCase):
    def test_complete_original_catalog(self):
        self.assertEqual(len(load_catalog(Path("docs/agent-catalog.json"))), 36)

    def test_duplicate_role_cannot_hide_missing_role(self):
        roles = json.loads(Path("docs/agent-catalog.json").read_text())
        roles[-1] = roles[0]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"
            p.write_text(json.dumps(roles))
            with self.assertRaises(ValueError): load_catalog(p)

    def test_packaged_catalog_matches_architecture_catalog(self):
        self.assertEqual(Path("docs/agent-catalog.json").read_bytes(),
                         Path("src/aegisflow_dr/data/agent-catalog.json").read_bytes())
