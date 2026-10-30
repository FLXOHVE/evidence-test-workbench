"""Compile confirmed module behavior recipes; never infer product rules from prose.

An agent/adapter normalizes sources once. This pure, platform-callable compiler
expands reusable paths and explicit decision/boundary rows into v2 draft cases.
It neither searches sources nor approves cases. Coupling is a separate queue.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from string import Formatter
from time import perf_counter

GENERATOR_VERSION = "module-batch-v1"
OBLIGATION_STATUSES = {"planned", "gap_rule", "gap_method", "not_applicable"}


class GenerationError(ValueError):
    pass


def _index(items, name):
    if not isinstance(items, list):
        raise GenerationError(f"{name} must be an array")
    result = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise GenerationError(f"{name} requires stable non-empty IDs")
        if item["id"] in result:
            raise GenerationError(f"Duplicate {name} ID: {item['id']}")
        result[item["id"]] = item
    return result


def generation_phase(item):
    """Mandatory baseline/safety prerequisites cannot be deferred as coupling."""
    if item.get("required_for_core") is True:
        if item.get("generation_phase", "core") != "core":
            raise GenerationError(f"Mandatory core prerequisite deferred: {item['id']}")
        return "core"
    phase = item.get("generation_phase", "coupling" if item.get("origin") == "dependency" else "core")
    if phase not in {"core", "coupling"}:
        raise GenerationError(f"Invalid generation phase: {item['id']}")
    return phase


def scoped_catalog(catalog, *, phase):
    if catalog is None:
        return None
    result = deepcopy(catalog)
    _index(result.get("items"), "catalog items")
    result["items"] = [item for item in result["items"]
                       if phase == "coupling" or generation_phase(item) == "core"]
    return result


def _render(template, bindings):
    if not isinstance(template, str) or not template.strip():
        raise GenerationError("Text/observable expectation is missing")
    for _, field, spec, conversion in Formatter().parse(template):
        if field is not None:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field) or spec or conversion:
                raise GenerationError("Only simple {binding} placeholders are allowed")
            if field not in bindings:
                raise GenerationError(f"Missing binding: {field}")
            if not isinstance(bindings[field], (str, int, float)) or isinstance(bindings[field], bool):
                raise GenerationError(f"Non-scalar binding: {field}")
    rendered = template.format_map(bindings)
    if not rendered.strip():
        raise GenerationError("Rendered text/observable expectation is empty")
    return rendered


def _confirmed(refs, claims):
    if not isinstance(refs, list) or not refs:
        raise GenerationError("Confirmed source claim IDs are required")
    for ref in refs:
        if ref not in claims or claims[ref].get("semantic_status") != "confirmed":
            raise GenerationError(f"Unknown/unconfirmed source claim: {ref}")
    return refs


def _variants(recipe, claims, issues):
    if "integer_boundary" in recipe and "variants" in recipe:
        raise GenerationError("Choose explicit rows or integer_boundary, not both")
    if "integer_boundary" not in recipe:
        rows = recipe.get("variants", [{"id": "base", "bindings": {}}])
        if not rows:
            raise GenerationError("Explicit variant rows cannot be empty")
        _index(rows, "variants")
        for row in rows:
            if not isinstance(row.get("bindings", {}), dict):
                raise GenerationError("Variant bindings must be an object")
        return rows
    rule = recipe["integer_boundary"]
    _confirmed(rule.get("claim_ids"), claims)
    low, high, step = (rule.get(key) for key in ("minimum", "maximum", "step"))
    if any(type(value) is not int for value in (low, high, step)) or step <= 0 or high < low:
        raise GenerationError("Boundary requires confirmed integer min/max and positive step")
    if (high - low) % step:
        raise GenerationError("Maximum is not on the confirmed step lattice")
    expected = rule.get("valid_expected")
    if not isinstance(expected, str) or not expected.strip():
        raise GenerationError("Boundary valid_expected is missing; do not invent an oracle")
    values = [("minimum", low), ("near_minimum", low + step),
              ("near_maximum", high - step), ("maximum", high)]
    seen, rows = set(), []
    for name, value in values:
        if low <= value <= high and value not in seen:
            seen.add(value)
            rows.append({"id": name, "bindings": {"value": value, "expected": _render(expected, {"value": value})},
                         "claim_ids": rule["claim_ids"]})
    if rule.get("include_outside") is True:
        if rule.get("outside_input_supported") is not True:
            issues.append({"variant_id": "outside", "message": "No confirmed method for input outside the UI range"})
            return rows
        for name, value in (("below", low - step), ("above", high + step)):
            oracle = rule.get(name + "_expected")
            try:
                _confirmed(rule.get(name + "_claim_ids"), claims)
                if not isinstance(oracle, str) or not oracle.strip():
                    raise GenerationError(f"No confirmed {name} expectation")
                rows.append({"id": name, "bindings": {"value": value, "expected": _render(oracle, {"value": value})},
                             "claim_ids": rule[name + "_claim_ids"]})
            except GenerationError as exc:
                issues.append({"variant_id": name, "message": str(exc)})
    return rows


def _expand_case(namespace, module, recipe_id, recipe, row, obligation, behaviors, preparations, refs, claims):
    bindings = row.get("bindings", {})
    if row.get("claim_ids"):
        _confirmed(row["claim_ids"], claims)
    case_refs = set(refs)
    scope_mode = recipe.get("case_claim_scope")
    if scope_mode not in {None, "explicit"}:
        raise GenerationError("Unsupported case claim scope mode")
    if scope_mode == "explicit":
        # Scenario-level claim_ids are the explicit business traceability scope.
        # Shared preparations can legitimately carry broader reusable evidence;
        # keep method provenance, but do not make unrelated business claims look
        # covered by every case that reuses the preparation.
        case_refs = set(_confirmed(recipe.get("claim_ids"), claims))
        case_refs.update(ref for ref in refs if ref.startswith("method:"))
    stable_key = json.dumps([namespace, recipe_id, row["id"]], ensure_ascii=False)
    case = {
        "id": namespace + "-" + hashlib.sha256(stable_key.encode()).hexdigest()[:16], "module": module,
        "title": _render(recipe.get("title"), bindings),
        "priority": row.get("priority", recipe.get("priority")),
        "priority_reason": _render(row.get("priority_reason", recipe.get("priority_reason")), bindings),
        "smoke": deepcopy(row.get("smoke", recipe.get("smoke"))),
        "obligation_ids": [obligation["id"]], "claim_ids": sorted(case_refs | set(row.get("claim_ids", []))),
        "preconditions": [{"state": _render(preparations[key].get("state"), bindings),
                           "setup": _render(preparations[key].get("setup"), bindings)} for key in recipe["preparation_ids"]],
        "steps": [{"action": _render(behaviors[key].get("trigger"), bindings),
                   "expected": "\n".join(_render(value, bindings) for value in behaviors[key]["outcomes"]),
                   "exact_text_claim_ids": deepcopy(behaviors[key].get("exact_text_claim_ids", [])),
                   **({"verification_kind": behaviors[key]["verification_kind"]}
                      if "verification_kind" in behaviors[key] else {})} for key in recipe["path"]],
        "notes": _render(recipe.get("notes") or "批量生成草稿，待独立评审。", bindings),
        "result": "未执行", "actual": "",
        "generation": {"recipe_id": recipe_id, "variant_id": row["id"],
                       "phase": generation_phase(obligation), "generator": GENERATOR_VERSION},
    }
    if "case_focus" in obligation:
        focus = obligation["case_focus"]
        expanded_checks = {check["expanded_step_index"] for check in focus["checks"]}
        history = deepcopy(focus["continuous_history"])
        if history is not None:
            compact_history = set(history["step_indices"])
            history["step_indices"] = [i for i, key in enumerate(recipe["path"])
                if behaviors[key].get("compact_step_index") in compact_history]
        case["generation"]["case_focus"] = {
            key: _render(focus[key], bindings) for key in (
                "goal_id", "purpose", "condition", "failure_consequence")}
        case["generation"]["case_focus"].update(
            semantic_verified=False,
            continuous_history=history,
            checks=[{"step_index": i, "action_quote": case["steps"][i]["action"],
                     "expected_quote": case["steps"][i]["expected"]}
                    for i, key in enumerate(recipe["path"])
                    if i in expanded_checks])
    for annotation in ("continuation", "decomposition"):
        if annotation in recipe:
            case["generation"][annotation] = deepcopy(recipe[annotation])
    if "continuation" in recipe:
        case["notes"] += " 连续执行前驱用例 " + recipe["continuation"]["case_id"] + " 后继续：" + recipe["continuation"]["handoff"]
    from .execution_contract import annotate_case, validate_case
    annotate_case(case, recipe, behaviors, bindings)
    validate_case(case)
    return case


def compile_module(contract: dict, *, phase="core", catalog=None) -> dict:
    """Return an entire phase, scoped model/catalog, backlog and honest metrics.

    Recipe-local omissions become scoped design/preparation tasks, not invented
    product decisions. Invalid global contracts fail atomically. Nothing is
    considered independently reviewed merely because this function succeeds.
    """
    started = perf_counter()
    from .usage_coverage import KINDS, refresh_usage_coverage, validate_usage_model
    if phase not in {"core", "coupling"}:
        raise GenerationError("Phase must be core or coupling")
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise GenerationError("Module contract schema_version must be 1")
    module, namespace = contract.get("module"), contract.get("case_namespace")
    if not isinstance(module, str) or not module.strip():
        raise GenerationError("Module name is required")
    if not isinstance(namespace, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", namespace):
        raise GenerationError("Stable case_namespace is required")
    model = deepcopy(contract.get("model", {}))
    if not isinstance(model, dict):
        raise GenerationError("Model must be an object")
    if "independent_source_policy" in model:
        model["independent_source_phase"] = phase
    if model.get("schema_version") != 2 or model.get("cases"):
        raise GenerationError("Input must be a v2 behavior model without prewritten cases")
    claims = _index(model.get("source_claims"), "source_claims")
    behaviors = _index(model.get("behaviors"), "behaviors")
    relations = _index(model.get("dependency_relations"), "dependency_relations")
    obligations = _index(model.get("coverage_obligations"), "coverage_obligations")
    for obligation in obligations.values():
        status = obligation.get("status")
        if not isinstance(status, str) or status not in OBLIGATION_STATUSES:
            raise GenerationError(f"Invalid coverage obligation status: {obligation['id']}")
    preparations = _index(contract.get("preparations"), "preparations")
    recipes = _index(contract.get("recipes"), "recipes")
    if not isinstance(model.get("open_questions"), list):
        raise GenerationError("open_questions must be an array")
    from .scenario_drafts import validate_scenario_drafts, scenario_draft_claim_ids
    try:
        validate_scenario_drafts(model)
    except ValueError as exc:
        raise GenerationError(str(exc)) from exc
    validate_usage_model(model)
    selected = {key for key, item in obligations.items()
                if phase == "coupling" or generation_phase(item) == "core"}
    if not selected:
        raise GenerationError("No module-core coverage obligations")
    if catalog is not None:
        cat_items = _index(catalog.get("items"), "catalog items")
        source_only = (catalog.get("source_audit") or {}).get("request", {}).get("source_branch_policy") == "source-branches-v1"
        core_planned_refs = {ref for o in obligations.values() if generation_phase(o) == "core" and o["status"] == "planned"
                             for ref in o.get("catalog_refs", [])}
        for obligation in obligations.values():
            for ref in obligation.get("catalog_refs", []):
                if (ref in cat_items and generation_phase(obligation) != generation_phase(cat_items[ref])
                        and not (source_only and ((generation_phase(obligation) == "core"
                                 and generation_phase(cat_items[ref]) == "coupling")
                                 or (generation_phase(obligation) == "coupling" and ref in core_planned_refs)))):
                    raise GenerationError(f"Phase disagrees with independent catalog: {ref}")
    tasks, cases, covered = [], [], set()
    usage_bindings = []
    for recipe_id, recipe in recipes.items():
        oid = recipe.get("obligation_id")
        if oid not in obligations:
            raise GenerationError(f"Recipe {recipe_id} has unknown obligation: {oid}")
        if oid not in selected or obligations[oid].get("status") != "planned":
            continue
        try:
            path = recipe.get("path")
            if not isinstance(path, list) or not path or any(key not in behaviors for key in path):
                raise GenerationError("Explicit executable behavior path is missing")
            if not set(obligations[oid].get("behavior_ids", [])) <= set(path):
                raise GenerationError("Path does not exercise all linked behavior targets")
            prep_ids = recipe.get("preparation_ids")
            if not isinstance(prep_ids, list) or not prep_ids or any(key not in preparations for key in prep_ids):
                raise GenerationError("Preparation state/setup is missing")
            if behaviors[path[0]].get("state") not in [preparations[key].get("state") for key in prep_ids]:
                raise GenerationError("Preparations do not establish the first behavior state")
            for left, right in zip(path, path[1:]):
                if not behaviors[left].get("next_state") or behaviors[left]["next_state"] != behaviors[right].get("state"):
                    raise GenerationError(f"Unconnected behavior path: {left} -> {right}")
            refs = set()
            for key in path:
                if ("verification_kind" in behaviors[key] and (not isinstance(behaviors[key]["verification_kind"], str)
                        or behaviors[key]["verification_kind"] not in KINDS)):
                    raise GenerationError("Unknown behavior verification_kind")
                refs.update(_confirmed(behaviors[key].get("claim_ids"), claims))
                if not isinstance(behaviors[key].get("outcomes"), list) or not behaviors[key]["outcomes"]:
                    raise GenerationError(f"Observable expected result missing: {key}")
            for key in prep_ids:
                refs.update(_confirmed(preparations[key].get("claim_ids"), claims))
            generated, row_issues, semantic_rows = [], [], set()
            for row in _variants(recipe, claims, row_issues):
                try:
                    case = _expand_case(namespace, module, recipe_id, recipe, row, obligations[oid],
                                        behaviors, preparations, refs, claims)
                    semantic = json.dumps({key: case[key] for key in ("module", "preconditions", "steps")},
                                          ensure_ascii=False, sort_keys=True)
                    if semantic in semantic_rows:
                        raise GenerationError("Equivalent variant only changes its title/ID; not an additional case")
                    semantic_rows.add(semantic)
                    generated.append(case)
                    if "usage_goals" in model or "source_branch_coverage" in model or "coverage_plan" in model:
                        usage_bindings.append({"case_id": case["id"], "obligation_id": oid,
                            "path": deepcopy(path), "bindings": deepcopy(row.get("bindings", {}))})
                except (GenerationError, ValueError, TypeError) as exc:
                    row_issues.append({"variant_id": row["id"], "message": str(exc)})
            cases.extend(generated)
            if generated:
                covered.add(oid)
            tasks.extend({"category": "design_defect", "recipe_id": recipe_id, "obligation_id": oid,
                          **issue} for issue in row_issues)
        except (GenerationError, ValueError, TypeError) as exc:
            tasks.append({"category": "design_defect", "recipe_id": recipe_id,
                          "obligation_id": oid, "message": str(exc)})
    for oid in selected:
        if obligations[oid].get("status") == "planned" and oid not in covered:
            tasks.append({"category": "design_defect", "obligation_id": oid,
                          "message": "明确覆盖目标尚无可展开的行为路径，不是产品规则冲突。"})
    from .scenario_drafts import RULE_EVIDENCE_POLICY
    if model.get("design_rule_evidence_policy") == RULE_EVIDENCE_POLICY:
        # A core projection may still carry a pending goal's evidence. Keep
        # its real deferred design, never a bare exemption ID or a new case.
        model["deferred_scenario_designs"] = [deepcopy(item) for item in model["coverage_obligations"]
            if item["id"] not in selected and item.get("scenario_drafts")]
    model["coverage_obligations"] = [item for item in model["coverage_obligations"] if item["id"] in selected]
    # Keep failed recipes as explicit scoped gaps; do not silently omit them.
    for item in model["coverage_obligations"]:
        if item.get("status") == "planned" and item["id"] not in covered:
            item.update(status="gap_method", rationale="; ".join(task["message"] for task in tasks if task["obligation_id"] == item["id"]))
    behavior_ids = {key for item in model["coverage_obligations"] for key in item.get("behavior_ids", [])}
    behavior_ids.update(key for recipe in recipes.values() if recipe.get("obligation_id") in selected for key in recipe.get("path", []))
    relation_ids = {key for item in model["coverage_obligations"] for key in item.get("relation_ids", [])}
    model["behaviors"] = [item for item in model["behaviors"] if item["id"] in behavior_ids]
    model["dependency_relations"] = [item for item in model["dependency_relations"] if item["id"] in relation_ids]
    claim_ids = {key for item in model["behaviors"] + model["dependency_relations"]
                 for key in item.get("claim_ids", []) + item.get("exact_text_claim_ids", [])}
    claim_ids.update(key for case in cases for key in case["claim_ids"])
    claim_ids.update(key for goal in model.get("usage_goals", []) for key in goal.get("claim_ids", []))
    claim_ids.update(key for row in model.get("relationship_coverage", {}).get("dispositions", [])
                     for key in row.get("claim_ids", []))
    claim_ids.update(key for row in model.get("source_branch_coverage", {}).get("dispositions", [])
                     for key in row.get("claim_ids", []))
    claim_ids.update(scenario_draft_claim_ids(model))
    claim_ids.update(model.get("coverage_plan", {}).get("claim_ids", []))
    claim_ids.update(cid for step in model.get("suite_cleanup", {}).get("steps", []) for cid in step.get("claim_ids", []))
    model["source_claims"] = [item for item in model["source_claims"] if item["id"] in claim_ids]
    questions = []
    for question in model.get("open_questions", []):
        refs = question.get("affected_obligation_ids", [])
        if not refs or set(refs) & selected:
            value = deepcopy(question)
            if refs:
                value["affected_obligation_ids"] = [key for key in refs if key in selected]
            questions.append(value)
    model["open_questions"], model["cases"] = questions, cases
    from .case_decomposition import validate_continuations
    validate_continuations(cases)
    from .coverage_plan import refresh as refresh_coverage_plan
    refresh_coverage_plan(model, usage_bindings)
    if "usage_goals" in model:
        model.setdefault("usage_coverage", {})["case_bindings"] = usage_bindings
    if "source_branch_coverage" in model:
        model["source_branch_coverage"]["case_bindings"] = deepcopy(usage_bindings)
    refresh_usage_coverage(model, allow_missing_targets=True)
    from .relationship_coverage import refresh_relationship_coverage
    refresh_relationship_coverage(model)
    from .source_branch_contract import refresh_source_branch_coverage
    refresh_source_branch_coverage(model)
    model["generation_tasks"] = deepcopy(tasks)
    catalog_scope = scoped_catalog(catalog, phase=phase)
    backlog = [{"id": oid, "objective": item.get("objective"), "status": item.get("status"),
                "phase": generation_phase(item), "catalog_refs": item.get("catalog_refs", []),
                "reason": item.get("rationale", "待模块自身草稿完成后扩展")}
               for oid, item in obligations.items() if oid not in selected]
    if catalog is not None:
        handled = {ref for item in obligations.values() for ref in item.get("catalog_refs", [])}
        backlog.extend({"id": "catalog:" + item["id"], "kind": "unmodeled_catalog",
                        "objective": item.get("objective"), "status": "not_modeled",
                        "phase": generation_phase(item), "source_refs": item.get("source_refs", []),
                        "reason": "独立目录已有覆盖目标，行为义务尚未建模；不是产品规则冲突。"}
                       for item in catalog["items"] if item["id"] not in handled)
    if "relationship_coverage" in model:
        record = model["relationship_coverage"]
        backlog.extend({"id": "relationship:" + cid, "kind": "relationship_investigation",
            "objective": "核对资源关联候选 " + cid, "status": row["status"], "phase": "coupling",
            "reason": row["reason"]}
            for row in record["dispositions"] if row["status"] in {"unresearched", "gap_rule", "gap_method"}
            for cid in row["candidate_ids"])
    if "usage_journeys" in model:
        for journey in model["usage_coverage"]["journeys"]:
            backlog.extend({"id": "usage:" + journey["id"] + ":" + str(change["change_index"]),
                "kind": "usage_journey_change", "objective": change["change"],
                "journey_id": journey["id"], "change_index": change["change_index"],
                "status": change["status"], "phase": phase, "reason": change["reason"]}
                for change in journey["changes"] if change["status"] != "planned_unreviewed")
    if "source_branch_coverage" in model:
        record = model["source_branch_coverage"]
        if record["inventory"] is None:
            backlog.append({"id": "source-branches:inventory", "kind": "source_branch_inventory",
                "objective": "从完整已读来源独立推导触发/状态/恢复分支", "status": "not_assessed",
                "phase": "coupling", "reason": "已有规则/情境清单不能自证没有遗漏整个分支。"})
        else:
            pending = set(record["pending_branch_ids"])
            backlog.extend({"id": "source-branch:" + row["branch_id"], "kind": "source_branch",
                "objective": row["branch_id"], "status": row["status"], "phase": "coupling", "reason": row["reason"]}
                for row in record["dispositions"] if row["branch_id"] in pending)
    coverage_summary = {}
    if "coverage_plan" in model:
        record = model["coverage_plan"]
        pending = set(record["unresolved_obligation_ids"])
        statuses = {r["id"]: r["status"] for r in record["generated_obligations"]}
        backlog.extend({"id": "source-plan:" + o["id"], "kind": "source_coverage_obligation",
            "objective": o["purpose"], "status": statuses[o["id"]], "phase": phase, "reason": o["reason"]}
            for o in record["analysis"]["obligations"] if o["id"] in pending)
        backlog.extend({"id": "source-pair:" + row["resource_id"] + ":" + row["change_id"] + ":" + row["consumer_id"],
            "kind": "shared_state_consumer", "objective": "共享状态变化后的消费检查", "phase": phase,
            "reason": "原始来源分析中仍有未完成的变化/消费组合。", **row} for row in record["unresolved_pairs"])
        coverage_summary["source_coverage_plan"] = {"policy": record["policy"],
            "obligations": len(record["analysis"]["obligations"]), "unresolved_obligations": len(pending),
            "change_consumer_pairs": len(record["generated_pairs"]), "unresolved_pairs": len(record["unresolved_pairs"]),
            "semantic_verified": False, "complete": False}
    return {"model": model, "catalog": catalog_scope, "tasks": tasks, "backlog": backlog,
            "summary": {"phase": phase, "core_cases": sum(case["generation"]["phase"] == "core" for case in cases),
                        "coupling_cases": sum(case["generation"]["phase"] == "coupling" for case in cases),
                        "selected_obligations": len(selected), "expanded_obligations": len(covered),
                        "generation_tasks": len(tasks),
                        "deferred_obligations": sum(item["phase"] == "coupling" for item in backlog) if phase == "core" else 0,
                        "unmodeled_catalog_items": sum(item.get("kind") == "unmodeled_catalog" for item in backlog),
                        "independent_review": "pending", "approved": False, **coverage_summary,
                        "elapsed_seconds": round(perf_counter() - started, 6)}}
