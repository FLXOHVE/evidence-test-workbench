"""Offline public synthetic regressions; these do not certify business coverage."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from evidence_test_workbench import GenerationError, compile_module
from evidence_test_workbench.cli import demo_contract, render_markdown


class CompilerTests(unittest.TestCase):
    def test_demo_keeps_unresolved_scope_and_never_approves_or_executes(self):
        result = compile_module(demo_contract())
        self.assertEqual(4, len(result["model"]["cases"]))
        self.assertFalse(result["summary"]["approved"])
        self.assertEqual("pending", result["summary"]["independent_review"])
        self.assertEqual(["O-SYNC"], [row["id"] for row in result["backlog"]])
        self.assertTrue(all(case["result"] == "未执行" for case in result["model"]["cases"]))

    def test_compile_does_not_mutate_input(self):
        contract = demo_contract()
        original = deepcopy(contract)
        compile_module(contract)
        self.assertEqual(original, contract)

    def test_repeated_compilation_has_identical_semantic_output(self):
        first, second = (compile_module(demo_contract()) for _ in range(2))
        first["summary"].pop("elapsed_seconds")
        second["summary"].pop("elapsed_seconds")
        self.assertEqual(first, second)

    def test_case_ids_survive_title_and_variant_order_changes(self):
        contract = demo_contract()
        before = {c["id"] for c in compile_module(contract)["model"]["cases"]}
        contract["recipes"][0]["title"] = "Reworded {filter} title"
        contract["recipes"][0]["variants"].reverse()
        after = {c["id"] for c in compile_module(contract)["model"]["cases"]}
        self.assertEqual(before, after)

    def test_unconfirmed_claim_blocks_cases_that_depend_on_it(self):
        contract = demo_contract()
        contract["model"]["source_claims"][0]["semantic_status"] = "proposal"
        result = compile_module(contract)
        self.assertEqual(1, len(result["model"]["cases"]))
        self.assertTrue(any("unconfirmed" in row["message"] for row in result["tasks"]))
        self.assertEqual("gap_method", result["model"]["coverage_obligations"][0]["status"])

    def test_missing_preparation_becomes_explicit_gap(self):
        contract = demo_contract()
        contract["preparations"] = []
        result = compile_module(contract)
        self.assertEqual([], result["model"]["cases"])
        self.assertEqual({"gap_method"}, {o["status"] for o in result["model"]["coverage_obligations"]})

    def test_blank_rendered_text_cannot_be_a_successful_case(self):
        for blank in ("", " ", "\n\t"):
            for field in ("expected", "filter"):
                with self.subTest(blank=repr(blank), field=field):
                    contract = demo_contract()
                    contract["recipes"][0]["variants"][0]["bindings"][field] = blank
                    # Use a binding-only action so this checks final text, not
                    # just whether the original template string was nonempty.
                    if field == "filter":
                        contract["model"]["behaviors"][0]["trigger"] = "{filter}"
                    result = compile_module(contract)
                    self.assertEqual(3, len(result["model"]["cases"]))
                    self.assertTrue(any("Rendered text" in row["message"] for row in result["tasks"]))

    def test_unknown_obligation_status_cannot_silently_drop_scope(self):
        for status in ("plannned", None, [], ""):
            with self.subTest(status=status):
                contract = demo_contract()
                contract["model"]["coverage_obligations"][0]["status"] = status
                with self.assertRaisesRegex(GenerationError, "Invalid coverage obligation status"):
                    compile_module(contract)

    def test_expected_results_must_be_an_array_of_nonempty_strings(self):
        for outcomes in ("Success", {}, None, [""], [" "], [None], [1]):
            with self.subTest(outcomes=outcomes):
                contract = demo_contract()
                contract["model"]["behaviors"][0]["outcomes"] = outcomes
                result = compile_module(contract)
                self.assertEqual(1, len(result["model"]["cases"]))
                self.assertTrue(result["tasks"])

    def test_unknown_expected_result_is_not_invented(self):
        contract = demo_contract()
        contract["model"]["behaviors"][0]["outcomes"] = []
        result = compile_module(contract)
        self.assertEqual(1, len(result["model"]["cases"]))
        self.assertTrue(any("Observable expected result missing" in row["message"] for row in result["tasks"]))

    def test_disconnected_path_does_not_generate_archive_case(self):
        contract = demo_contract()
        contract["model"]["behaviors"][1]["next_state"] = "Unrelated state"
        result = compile_module(contract)
        self.assertEqual(3, len(result["model"]["cases"]))
        self.assertTrue(any("Unconnected behavior path" in row["message"] for row in result["tasks"]))

    def test_one_bad_variant_does_not_discard_good_rows(self):
        contract = demo_contract()
        contract["recipes"][0]["variants"][0]["bindings"].pop("expected")
        result = compile_module(contract)
        self.assertEqual(3, len(result["model"]["cases"]))
        self.assertTrue(any(row.get("variant_id") == "all" for row in result["tasks"]))

    def test_title_only_duplicates_do_not_inflate_case_count(self):
        contract = demo_contract()
        recipe = contract["recipes"][0]
        recipe["title"] = "{label}"
        recipe["variants"] = [
            {"id": "a", "bindings": {"filter": "All", "expected": "All tasks visible", "label": "First"}},
            {"id": "b", "bindings": {"filter": "All", "expected": "All tasks visible", "label": "Second"}},
        ]
        result = compile_module(contract)
        self.assertEqual(2, len(result["model"]["cases"]))
        self.assertTrue(any("Equivalent variant" in row["message"] for row in result["tasks"]))

    def test_unsafe_template_attribute_access_is_rejected(self):
        contract = demo_contract()
        contract["recipes"][0]["title"] = "{filter.__class__}"
        result = compile_module(contract)
        self.assertEqual(1, len(result["model"]["cases"]))
        self.assertTrue(any("Only simple" in row["message"] for row in result["tasks"]))

    def test_core_prerequisite_cannot_be_hidden_in_coupling(self):
        contract = demo_contract()
        contract["model"]["coverage_obligations"][-1].update(required_for_core=True, generation_phase="coupling")
        with self.assertRaises(GenerationError):
            compile_module(contract)

    def test_coupling_includes_unresolved_rule_without_fabricating_case(self):
        result = compile_module(demo_contract(), phase="coupling")
        self.assertEqual(4, len(result["model"]["cases"]))
        self.assertEqual("gap_rule", result["model"]["coverage_obligations"][-1]["status"])
        self.assertEqual("Q-SYNC", result["model"]["open_questions"][0]["id"])
        self.assertIn("In-scope coverage gaps", render_markdown(result))

    def test_malformed_model_raises_domain_error(self):
        for invalid in (None, 1, "invalid", []):
            with self.subTest(model=invalid):
                contract = demo_contract()
                contract["model"] = invalid
                with self.assertRaisesRegex(GenerationError, "Model must be an object"):
                    compile_module(contract)

    def test_duplicate_ids_fail_before_compilation(self):
        contract = demo_contract()
        contract["recipes"].append(deepcopy(contract["recipes"][0]))
        with self.assertRaisesRegex(GenerationError, "Duplicate"):
            compile_module(contract)

    def test_integer_boundaries_require_explicit_outside_oracles(self):
        contract = demo_contract()
        contract["model"]["behaviors"][0].update(trigger="Enter value {value}", outcomes=["{expected}"])
        contract["model"]["source_claims"][0].update(
            quote="Synthetic numeric setting accepts integers from 1 through 10; outside values are rejected.",
            statement="Synthetic numeric setting has a confirmed inclusive 1..10 range.")
        recipe = contract["recipes"][0]
        recipe.pop("variants")
        recipe.update(title="Set value {value}", integer_boundary={
            "minimum": 1, "maximum": 10, "step": 1, "valid_expected": "Value {value} accepted",
            "claim_ids": ["CL-FILTER"], "include_outside": True,
        })
        # A separate explicit synthetic numeric rule exercises boundary expansion.
        partial = compile_module(contract)
        self.assertEqual(5, len(partial["model"]["cases"]))
        self.assertTrue(any(row.get("variant_id") == "outside" for row in partial["tasks"]))
        recipe["integer_boundary"].update(outside_input_supported=True,
            below_expected="Below minimum rejected", above_expected="Above maximum rejected",
            below_claim_ids=["CL-FILTER"], above_claim_ids=["CL-FILTER"])
        self.assertEqual(7, len(compile_module(contract)["model"]["cases"]))


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-X", "utf8", "-m", "evidence_test_workbench", *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8")

    def test_demo_exports_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report"
            first = self.run_cli("demo", "--output", target)
            self.assertEqual(0, first.returncode, first.stderr)
            before = (target / "cases.json").read_bytes()
            data = json.loads(before)
            self.assertEqual(4, len(data["model"]["cases"]))
            self.assertIn("O-SYNC", (target / "cases.md").read_text(encoding="utf-8"))
            self.assertTrue((target / "requirements.md").is_file())
            repeated = self.run_cli("demo", "--output", target)
            self.assertEqual(2, repeated.returncode)
            self.assertEqual(before, (target / "cases.json").read_bytes())

    def test_malformed_contract_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "bad.json", Path(directory) / "report"
            source.write_text('{"model":', encoding="utf-8")
            result = self.run_cli("compile", source, "--output", target)
            self.assertEqual(2, result.returncode)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(target.exists())

    def test_exported_contract_can_be_recompiled(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first", Path(directory) / "second"
            self.assertEqual(0, self.run_cli("demo", "--output", first).returncode)
            compiled = self.run_cli("compile", first / "contract.json", "--output", second, "--phase", "coupling")
            self.assertEqual(0, compiled.returncode, compiled.stderr)
            result = json.loads((second / "cases.json").read_text(encoding="utf-8"))
            self.assertEqual("gap_rule", result["model"]["coverage_obligations"][-1]["status"])


if __name__ == "__main__":
    unittest.main()
