"""A dependency-free local CLI; no credentials, network, or model calls."""
from __future__ import annotations

import argparse
import json
from importlib.resources import files
from pathlib import Path
import sys

from .module_generation import compile_module


def demo_contract():
    return json.loads(files("evidence_test_workbench").joinpath("data/task-list.contract.json").read_text(encoding="utf-8"))


def render_markdown(result):
    summary = result["summary"]
    lines = ["# Test case drafts", "", "Status: **unapproved; not executed**.", "",
             "Source-claim confirmation is supplied by the input author. This compiler does not verify source truth or completeness.", "",
             f"Phase: {summary['phase']}. Cases: {len(result['model']['cases'])}. "
             f"Generation issues: {len(result['tasks'])}. Backlog items: {len(result['backlog'])}.", ""]
    for case in result["model"]["cases"]:
        lines.extend([f"## {case['id']}: {case['title']}", "",
                      f"Claims: {', '.join(case['claim_ids'])}. Status: unapproved; not executed.", "", "Preparation:", ""])
        for prep in case["preconditions"]:
            lines.append(f"- {prep['setup']} Required state: {prep['state']}.")
        lines.extend(["", "Steps:", ""])
        for index, step in enumerate(case["steps"], 1):
            lines.extend([f"{index}. {step['action']}", f"   Expected: {step['expected'].replace(chr(10), chr(10) + '   ')}"])
        lines.append("")
    if result["tasks"]:
        lines.extend(["## Generation issues", ""])
        for task in result["tasks"]:
            lines.append(f"- {task.get('obligation_id', 'unknown')}: {task['message']}")
        lines.append("")
    if result["backlog"]:
        lines.extend(["## Deferred or unresolved scope", ""])
        for item in result["backlog"]:
            lines.append(f"- {item['id']} ({item['status']}): {item['objective']} — {item['reason']}")
        lines.append("")
    gaps = [o for o in result["model"]["coverage_obligations"] if o["status"] != "planned"]
    if gaps:
        lines.extend(["## In-scope coverage gaps", ""])
        for gap in gaps:
            lines.append(f"- {gap['id']} ({gap['status']}): {gap.get('rationale', gap['objective'])}")
        lines.append("")
    return "\n".join(lines)


def write_outputs(output, contract, result, *, synthetic=False):
    # Never silently overwrite a previous report or a user's data directory.
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (("contract.json", contract), ("cases.json", result), ("summary.json", result["summary"])):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "cases.md").write_text(render_markdown(result), encoding="utf-8")
    if synthetic:
        (output / "requirements.md").write_text(files("evidence_test_workbench").joinpath("data/requirements.md").read_text(encoding="utf-8"), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compile evidence-linked drafts offline; never approve or execute tests.")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Replay a small public synthetic task-list fixture.")
    compile_parser = commands.add_parser("compile", help="Compile an explicit behavior contract JSON file.")
    compile_parser.add_argument("contract", type=Path)
    compile_parser.add_argument("--catalog", type=Path, help="Optional independent coverage inventory JSON.")
    for command in (demo, compile_parser):
        command.add_argument("--output", type=Path, default=Path("demo-output") if command is demo else Path("build/cases"), help="New directory for artifacts; existing directories are preserved.")
        command.add_argument("--phase", choices=("core", "coupling"), default="core")
    args = parser.parse_args(argv)
    try:
        contract = demo_contract() if args.command == "demo" else json.loads(args.contract.read_text(encoding="utf-8-sig"))
        catalog = json.loads(args.catalog.read_text(encoding="utf-8-sig")) if getattr(args, "catalog", None) else None
        result = compile_module(contract, phase=args.phase, catalog=catalog)
        write_outputs(args.output, contract, result, synthetic=args.command == "demo")
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"output": str(args.output.resolve()), **result["summary"]}, ensure_ascii=True, indent=2))
    return 0
