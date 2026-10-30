"""Verify the new portable skill artifact, including its real bundled example."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("skill_packager", ROOT / "tools/package_skill.py")
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class SkillPackageTests(unittest.TestCase):
    def test_portable_archive_contains_utf8_license_and_verified_example(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            output = directory / "skill.zip"
            manifest = packager.build(ROOT / "skills/evidence-case-design", output)
            paths = {row["path"] for row in manifest["files"]}
            self.assertTrue({"LICENSE", "SKILL.md", "assets/task-list.contract.json"} <= paths)
            with zipfile.ZipFile(output) as archive:
                for row in manifest["files"]:
                    content = archive.read("evidence-case-design/" + row["path"])
                    content.decode("utf-8")
                    self.assertEqual(row["sha256"], hashlib.sha256(content).hexdigest())
                contract = directory / "contract.json"
                contract.write_bytes(archive.read("evidence-case-design/assets/task-list.contract.json"))
            subprocess.run([sys.executable, "-m", "evidence_test_workbench", "compile",
                            str(contract), "--output", str(directory / "result")],
                           cwd=ROOT, check=True, capture_output=True)
            summary = json.loads((directory / "result/summary.json").read_text(encoding="utf-8"))
            self.assertEqual(4, summary["core_cases"])
            self.assertEqual(1, summary["deferred_obligations"])
            self.assertFalse(summary["approved"])
            with self.assertRaises(FileExistsError):
                packager.build(ROOT / "skills/evidence-case-design", output)

    def test_missing_portable_reference_is_rejected_before_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            skill = directory / "skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text("[Missing](references/missing.md)", encoding="utf-8")
            (skill / "LICENSE").write_text("Test license", encoding="utf-8")
            with self.assertRaises(ValueError):
                packager.build(skill, directory / "invalid.zip")
            self.assertFalse((directory / "invalid.zip").exists())
