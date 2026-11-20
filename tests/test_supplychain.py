# SPDX-License-Identifier: Apache-2.0
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from aegisflow_dr import supplychain as sc


class Meta(dict):
    def __init__(self, classifiers=(), **fields):
        super().__init__(fields)
        self.classifiers = list(classifiers)

    def get_all(self, key):
        return self.classifiers if key == "Classifier" else None


def world(entries):
    """entries: name -> (version, license, [requires])"""
    def lookup(name):
        if name not in entries:
            return None
        version, license_, requires = entries[name]
        return {"name": name, "version": version, "license": license_, "requires": requires}
    return lookup


class ParseTests(unittest.TestCase):
    def test_names_normalise(self):
        self.assertEqual(sc.normalize("Foo_Bar.baz"), "foo-bar-baz")

    def test_requirement_parts(self):
        r = sc.parse_requirement("Pkg_X[a, b]>=1.0,<2 ; python_version < '3.13'")
        self.assertEqual((r["name"], r["extras"], r["specifier"], r["marker"]),
                         ("pkg-x", ["a", "b"], ">=1.0,<2", "python_version < '3.13'"))
        plain = sc.parse_requirement("jsonschema==4.26.0")
        self.assertEqual((plain["extras"], plain["marker"]), ([], None))

    def test_invalid_requirement_rejected(self):
        for bad in ("", "  ", "!!bad"):
            with self.assertRaises(ValueError):
                sc.parse_requirement(bad)


class LicenseTests(unittest.TestCase):
    def test_expression_wins(self):
        self.assertEqual(sc.license_of(Meta(["License :: OSI Approved :: MIT License"], **{"License-Expression": " MIT "})), "MIT")

    def test_classifiers_are_mapped_and_combined(self):
        meta = Meta(["License :: OSI Approved", "License :: OSI Approved :: MIT License",
                     "License :: OSI Approved :: Apache Software License", "Programming Language :: Python"])
        self.assertEqual(sc.license_of(meta), "Apache-2.0 AND MIT")

    def test_short_license_field(self):
        self.assertEqual(sc.license_of(Meta(License="3-Clause BSD License")), "BSD-3-Clause")
        self.assertEqual(sc.license_of(Meta(License="Zlib")), "Zlib")

    def test_long_or_missing_text_is_unknown(self):
        self.assertEqual(sc.license_of(Meta(License="x" * 65)), "UNKNOWN")
        self.assertEqual(sc.license_of(Meta(License="line one\nline two")), "UNKNOWN")
        self.assertEqual(sc.license_of(Meta()), "UNKNOWN")

    def test_allowed_is_fail_closed(self):
        for ok in ("MIT", "MIT OR GPL-3.0-only", "Apache-2.0 OR BSD-3-Clause", "MIT AND ISC"):
            self.assertTrue(sc.license_allowed(ok), ok)
        for bad in ("UNKNOWN", "GPL-3.0-only", "MIT AND GPL-3.0-only", "(MIT)", "MIT WITH x", "", "  ", None, 3):
            self.assertFalse(sc.license_allowed(bad), bad)


class ClosureTests(unittest.TestCase):
    def test_transitive_closure_is_sorted_and_deduplicated(self):
        components, missing, conditional = sc.closure(["a"], world({
            "a": ("1", "MIT", ["b>=1", "c"]), "b": ("2", "MIT", ["c"]), "c": ("3", "ISC", [])}))
        self.assertEqual([c["name"] for c in components], ["a", "b", "c"])
        self.assertEqual((missing, conditional), ([], []))

    def test_extras_only_followed_when_requested(self):
        entries = {"a": ("1", "MIT", ["x; extra == 'fast'"]), "b": ("1", "MIT", ["x; extra == 'fast'"]),
                   "x": ("1", "MIT", [])}
        self.assertEqual([c["name"] for c in sc.closure(["a"], world(entries))[0]], ["a"])
        entries["root"] = ("1", "MIT", ["a[fast]", "b"])
        names = [c["name"] for c in sc.closure(["root"], world(entries))[0]]
        self.assertEqual(names, ["a", "b", "root", "x"])

    def test_missing_dependency_split_by_marker(self):
        entries = {"a": ("1", "MIT", ["gone", "win; sys_platform == 'win32'", "both", "both; python_version < '3'"])}
        components, missing, conditional = sc.closure(["a"], world(entries))
        self.assertEqual((missing, conditional), (["both", "gone"], ["win"]))
        self.assertEqual(len(components), 1)

    def test_conditional_then_unconditional_reference_is_required(self):
        entries = {"a": ("1", "MIT", ["m; sys_platform == 'win32'", "m"])}
        self.assertEqual(sc.closure(["a"], world(entries))[1], ["m"])

    def test_cycles_terminate(self):
        entries = {"a": ("1", "MIT", ["b"]), "b": ("1", "MIT", ["a"])}
        self.assertEqual(len(sc.closure(["a"], world(entries))[0]), 2)

    def test_real_environment(self):
        components, missing, _ = sc.closure(["jsonschema"])
        self.assertEqual(missing, [])
        self.assertIn("jsonschema", [c["name"] for c in components])
        self.assertIsNone(sc.installed("definitely-not-installed-package"))
        record = sc.installed("JSONSchema")
        self.assertEqual(record["name"], "jsonschema")
        self.assertTrue(record["version"])


class CheckTests(unittest.TestCase):
    COMPONENTS = [{"name": "a", "version": "1", "license": "MIT"},
                  {"name": "b", "version": "2", "license": "GPL-3.0-only"},
                  {"name": "c", "version": "3", "license": "MPL-2.0"},
                  {"name": "d", "version": "4", "license": "UNKNOWN"}]

    def test_problems_and_reviews_are_separate(self):
        problems, reviews = sc.check(self.COMPONENTS, ["gone"])
        self.assertEqual(problems, ["licence not allowed: b 2 (GPL-3.0-only)", "licence not allowed: d 4 (UNKNOWN)",
                                    "not installed: gone"])
        self.assertEqual(reviews, ["licence needs review: c 3 (MPL-2.0)"])

    def test_clean_input_passes(self):
        self.assertEqual(sc.check(self.COMPONENTS[:1]), ([], []))


class SbomTests(unittest.TestCase):
    def test_shape_and_determinism(self):
        components = [{"name": "a", "version": "1", "license": "MIT"}]
        first = sc.build_sbom(components, root="r", root_version="9")
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(sc.build_sbom(components, root="r", root_version="9"), sort_keys=True))
        self.assertEqual(first["bomFormat"], "CycloneDX")
        self.assertEqual(first["metadata"]["component"], {"type": "application", "name": "r", "version": "9"})
        self.assertEqual(first["components"][0]["purl"], "pkg:pypi/a@1")
        self.assertEqual(first["components"][0]["licenses"], [{"expression": "MIT"}])
        self.assertNotIn("serialNumber", first)
        self.assertNotIn("timestamp", first["metadata"])


class ToolTests(unittest.TestCase):
    def test_project_dependencies_pass_and_sbom_is_written(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("check_supply_chain", root / "tools" / "check_supply_chain.py")
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()) as out:
            code = tool.main(root / "pyproject.toml", Path(tmp) / "sbom.json")
            sbom = json.loads((Path(tmp) / "sbom.json").read_text("utf-8"))
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(sbom["metadata"]["component"]["name"], "aegisflow-data-reliability")
        self.assertIn("jsonschema", [c["name"] for c in sbom["components"]])


if __name__ == "__main__":
    unittest.main()
