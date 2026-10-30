"""Preserve user-task analysis without inventing product rules or completeness.

Step labels and quoted observations are model declarations. These structural
checks cannot decide whether an observation proves the intended user effect.
"""
from copy import deepcopy

from .module_generation import GenerationError


POLICY = "usage-goals-v1"
KINDS = {"configuration", "functional_effect"}
STATUSES = {"unresearched", "confirmed", "gap_rule", "gap_method", "out_of_scope"}
GOAL_FIELDS = {"id", "user_task", "context", "intended_effect", "verification_kind",
               "evidence_status", "claim_ids", "scenario_ids", "gap_ids", "effect_checks",
               "counterexample", "rationale"}


def build_usage_context(run, module):
    """Carry original intent alongside the selected, possibly narrower evidence."""
    boundaries = []
    for source in (run.get("baseline") or {}).get("sources", []):
        boundaries.append({key: deepcopy(source.get(key)) for key in (
            "source_id", "read_scope", "applicability_scope", "reading_boundary", "draft_scope",
            "comments_complete")})
    return {"policy": POLICY, "user_request": run.get("query", ""),
            "selected_scope": {"module": module,
                "configuration": deepcopy(run.get("target", {}).get("configuration")),
                "fixed_requirement_scope": deepcopy((run.get("fixed_requirements") or {}).get("scope")),
                "source_reading_boundaries": boundaries}}


def _index(items, label):
    if not isinstance(items, list):
        raise GenerationError(f"{label} must be an array")
    result = {}
    for item in items:
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                or not item["id"].strip() or item["id"] in result):
            raise GenerationError(f"{label} requires unique stable IDs")
        result[item["id"]] = item
    return result


def _refs(value, label):
    if (not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value)
            or len(value) != len(set(value))):
        raise GenerationError(f"{label} requires unique string references")
    return value


def _validate_shape(goals):
    indexed = _index(goals, "usage_goals")
    if not indexed:
        raise GenerationError("Usage analysis requires nonempty usage_goals")
    for goal in indexed.values():
        if set(goal) != GOAL_FIELDS:
            raise GenerationError("Usage goal fields must match the usage-goals-v1 contract")
        for key in ("user_task", "context", "intended_effect", "counterexample", "rationale"):
            if not isinstance(goal[key], str) or not goal[key].strip():
                raise GenerationError(f"Usage goal {goal['id']} requires {key}")
        if (not isinstance(goal["verification_kind"], str) or goal["verification_kind"] not in KINDS
                or not isinstance(goal["evidence_status"], str) or goal["evidence_status"] not in STATUSES):
            raise GenerationError("Unknown usage verification kind or evidence status")
        for key in ("claim_ids", "scenario_ids", "gap_ids"):
            _refs(goal[key], "usage_goal." + key)
        if not isinstance(goal["effect_checks"], list):
            raise GenerationError("Usage effect_checks must be an array")
        seen = set()
        for check in goal["effect_checks"]:
            if (not isinstance(check, dict) or set(check) != {"scenario_id", "step_index", "quote"}
                    or not isinstance(check["scenario_id"], str) or not check["scenario_id"].strip()
                    or type(check["step_index"]) is not int or check["step_index"] < 0
                    or not isinstance(check["quote"], str) or not check["quote"].strip()):
                raise GenerationError("Usage effect check requires scenario_id, zero-based step_index and quote")
            identity = (check["scenario_id"], check["step_index"], check["quote"])
            if identity in seen:
                raise GenerationError("Duplicate usage effect check")
            seen.add(identity)
        if goal["evidence_status"] == "confirmed":
            if not goal["claim_ids"] or not goal["scenario_ids"] or not goal["effect_checks"]:
                raise GenerationError("Confirmed usage goal needs confirmed claims, scenarios and effect checks")
            if {c["scenario_id"] for c in goal["effect_checks"]} != set(goal["scenario_ids"]):
                raise GenerationError("Each claimed usage scenario needs an explicit effect check")
        elif goal["effect_checks"]:
            raise GenerationError("Unresearched, gap or excluded usage goals cannot claim effect checks")
        if goal["evidence_status"] in {"gap_rule", "gap_method"} and not goal["gap_ids"]:
            raise GenerationError("Usage rule/method gap must reference an actual corresponding gap")
    return indexed


def _gap_kinds_match(status, kinds):
    kinds = set(kinds)
    return kinds == {status} or (status == "gap_rule" and kinds == {"gap_rule", "gap_method"})


def validate_usage_goals(request, response, *, claims=None):
    """Validate references against original compact steps, before method expansion.

    Legacy requests and replies without usage metadata retain their old shape.
    No natural-language matching or semantic completeness claim is made here.
    """
    if "usage_context" not in request and "usage_goals" not in response:
        return None
    goals = _validate_shape(response.get("usage_goals"))
    claims = claims if claims is not None else _index(response.get("claims"), "claims")
    scenarios = _index(response.get("scenarios"), "scenarios")
    gaps = _index(response.get("gaps"), "gaps")
    for scenario in scenarios.values():
        for step in scenario.get("steps", []):
            if (isinstance(step, dict) and "verification_kind" in step
                    and (not isinstance(step["verification_kind"], str) or step["verification_kind"] not in KINDS)):
                raise GenerationError("Unknown step verification_kind")
    for goal in goals.values():
        if set(goal["claim_ids"]) - claims.keys() or set(goal["scenario_ids"]) - scenarios.keys() or set(goal["gap_ids"]) - gaps.keys():
            raise GenerationError("Usage goal references an unknown claim, scenario or gap")
        status = goal["evidence_status"]
        if status == "confirmed" and any(claims[c].get("semantic_status") != "confirmed" for c in goal["claim_ids"]):
            raise GenerationError("Confirmed usage goal references an unconfirmed claim")
        if status in {"gap_rule", "gap_method"} and not _gap_kinds_match(status, [gaps[g].get("status") for g in goal["gap_ids"]]):
            raise GenerationError("Usage gap status disagrees with its referenced gap")
        for check in goal["effect_checks"]:
            steps = scenarios[check["scenario_id"]].get("steps", [])
            if check["step_index"] >= len(steps):
                raise GenerationError("Usage effect check step_index is outside the compact scenario")
            step = steps[check["step_index"]]
            if (not isinstance(step, dict) or not isinstance(step.get("expected"), str)
                    or check["quote"] not in step["expected"]):
                raise GenerationError("Usage effect check quote must occur verbatim in the original step expected result")
            if goal["verification_kind"] == "functional_effect" and step.get("verification_kind", "configuration") != "functional_effect":
                raise GenerationError("Functional effect cannot be claimed from a configuration-only step")
    return deepcopy(list(goals.values()))


def validate_usage_model(model, *, allow_missing_targets=False):
    """Check stored references, including preserved compact-step coordinates.

    Phase and delivery projections may omit targets; their original goals stay
    visible and are reported as not generated in that scope.
    """
    from .usage_journeys import validate_usage_journey_model
    validate_usage_journey_model(model, allow_missing_targets=allow_missing_targets)
    if "usage_goals" not in model:
        return
    goals = _validate_shape(model["usage_goals"])
    claims = _index(model.get("source_claims"), "source_claims")
    obligations = _index(model.get("coverage_obligations"), "coverage_obligations")
    behaviors = _index(model.get("behaviors"), "behaviors")
    for goal in goals.values():
        if set(goal["claim_ids"]) - claims.keys():
            raise GenerationError("Stored usage goal references an unknown claim")
        if goal["evidence_status"] == "confirmed" and any(
                claims[c].get("semantic_status") != "confirmed" for c in goal["claim_ids"]):
            raise GenerationError("Stored confirmed usage goal references an unconfirmed claim")
        for sid in goal["scenario_ids"]:
            if sid not in obligations and not allow_missing_targets:
                raise GenerationError("Stored usage goal references an unknown scenario")
        for gid in goal["gap_ids"]:
            if gid not in obligations:
                if not allow_missing_targets:
                    raise GenerationError("Stored usage goal references an unknown gap")
        if goal["evidence_status"] in {"gap_rule", "gap_method"}:
            kinds = [obligations[gid].get("status") for gid in goal["gap_ids"] if gid in obligations]
            partial = allow_missing_targets and len(kinds) < len(goal["gap_ids"])
            if not (_gap_kinds_match(goal["evidence_status"], kinds) or (partial and all(
                    k == goal["evidence_status"] or (goal["evidence_status"] == "gap_rule" and k == "gap_method") for k in kinds))):
                raise GenerationError("Stored usage gap status disagrees with its referenced gap")
        for check in goal["effect_checks"]:
            target = obligations.get(check["scenario_id"])
            if target is None:
                continue
            path = [behaviors[b] for b in target.get("behavior_ids", []) if b in behaviors]
            if any("compact_step_index" in b for b in path):
                observed = [b for b in path if b.get("compact_step_index") == check["step_index"]]
            else:
                observed = path[check["step_index"]:check["step_index"] + 1]
            if not any(any(isinstance(value, str) and check["quote"] in value for value in b.get("outcomes", []))
                    and (goal["verification_kind"] != "functional_effect" or b.get("verification_kind", "configuration") == "functional_effect")
                    for b in observed):
                raise GenerationError("Stored usage effect check no longer matches its cited observation or verification kind")


def _case_bindings(model, obligations, behaviors, previous):
    """Recheck compiler path/bindings against actual case actions and results."""
    from .module_generation import _render
    entries = previous.get("case_bindings", [])
    if not isinstance(entries, list):
        raise GenerationError("Usage case_bindings must be an array")
    cases = _index(model.get("cases", []), "cases")
    bindings = {}
    seen = set()
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {"case_id", "obligation_id", "path", "bindings"}
                or not isinstance(entry["case_id"], str) or entry["case_id"] in seen
                or not isinstance(entry["obligation_id"], str) or not isinstance(entry["bindings"], dict)):
            raise GenerationError("Invalid or duplicate usage case binding")
        seen.add(entry["case_id"])
        if entry["case_id"] not in cases:
            continue  # A delivery projection intentionally excludes this case.
        case, oid = cases[entry["case_id"]], entry["obligation_id"]
        path = entry["path"]
        if not isinstance(path, list) or any(not isinstance(b, str) or not b for b in path):
            raise GenerationError("Usage case binding path requires behavior IDs")
        if (oid not in obligations or oid not in case.get("obligation_ids", [])
                or not path or set(path) - behaviors.keys()
                or not set(obligations[oid].get("behavior_ids", [])) <= set(path)
                or len(case.get("steps", [])) != len(path)):
            raise GenerationError("Usage case binding does not exercise its actual obligation/path")
        for bid, step in zip(path, case["steps"]):
            behavior = behaviors[bid]
            expected = "\n".join(_render(value, entry["bindings"]) for value in behavior.get("outcomes", []))
            if (not isinstance(step, dict) or step.get("action") != _render(behavior.get("trigger"), entry["bindings"])
                    or step.get("expected") != expected
                    or step.get("verification_kind", "configuration") != behavior.get("verification_kind", "configuration")):
                raise GenerationError("Usage case binding differs from the actual rendered action/result")
        bindings[entry["case_id"]] = entry
    return bindings


def _case_observes(case, check, goal, target, behaviors, binding):
    from .module_generation import _render
    target_path = [behaviors[b] for b in target.get("behavior_ids", []) if b in behaviors]
    if any("compact_step_index" in b for b in target_path):
        observed = [b for b in target_path if b.get("compact_step_index") == check["step_index"]]
    else:
        observed = target_path[check["step_index"]:check["step_index"] + 1]
    if binding:
        path, values = binding["path"], binding["bindings"]
        try:
            quote = _render(check["quote"], values)
        except (GenerationError, ValueError):
            return False
    else:
        # Hand-authored models have no variant binding proof. Only literal,
        # directly positioned observations can be linked automatically.
        if "{" in check["quote"] or "}" in check["quote"]:
            return False
        path, quote = target.get("behavior_ids", []), check["quote"]
    for behavior in observed:
        if behavior["id"] not in path:
            continue
        position = path.index(behavior["id"])
        if position >= len(case.get("steps", [])):
            continue
        step = case["steps"][position]
        if (isinstance(step, dict) and isinstance(step.get("expected"), str) and quote in step["expected"]
                and (goal["verification_kind"] != "functional_effect"
                     or step.get("verification_kind", "configuration") == "functional_effect")):
            return True
    return False


def refresh_usage_coverage(model, *, allow_missing_targets=False):
    """Refresh actual generated-case links while retaining every unresolved goal."""
    if "usage_goals" not in model:
        return
    validate_usage_model(model, allow_missing_targets=allow_missing_targets)
    goals = _validate_shape(model["usage_goals"])
    obligations = {item["id"]: item for item in model.get("coverage_obligations", [])}
    behaviors = {item["id"]: item for item in model.get("behaviors", [])}
    previous = model.get("usage_coverage") or {}
    bindings = _case_bindings(model, obligations, behaviors, previous)
    rows = []
    for goal in goals.values():
        checked = {c["scenario_id"] for c in goal["effect_checks"]} & obligations.keys()
        case_ids = []
        for case in model.get("cases", []):
            targets = set(case.get("obligation_ids", [])) & checked
            checks = [check for check in goal["effect_checks"] if check["scenario_id"] in targets]
            if checks and all(_case_observes(case, check, goal, obligations[check["scenario_id"]],
                    behaviors, bindings.get(case["id"])) for check in checks):
                case_ids.append(case["id"])
        case_ids.sort()
        status = goal["evidence_status"]
        if status == "confirmed":
            status = ("planned_unreviewed" if goal["verification_kind"] == "functional_effect"
                      else "configuration_only") if case_ids else "not_generated_in_scope"
        rows.append({"goal_id": goal["id"], "verification_kind": goal["verification_kind"],
                     "evidence_status": goal["evidence_status"], "status": status, "case_ids": case_ids,
                     "scenario_ids": deepcopy(goal["scenario_ids"]), "gap_ids": deepcopy(goal["gap_ids"])})
    model["usage_coverage"] = {"policy": POLICY,
        "user_request": deepcopy(previous.get("user_request", "")),
        "selected_scope": deepcopy(previous.get("selected_scope", {})), "goals": rows,
        "case_bindings": [deepcopy(bindings[key]) for key in sorted(bindings)],
        "unresearched_goal_ids": [g["id"] for g in goals.values() if g["evidence_status"] == "unresearched"],
        "gap_goal_ids": [g["id"] for g in goals.values() if g["evidence_status"] in {"gap_rule", "gap_method"}],
        "excluded_goal_ids": [g["id"] for g in goals.values() if g["evidence_status"] == "out_of_scope"],
        "semantic_verified": False, "complete": False,
        "boundary": "Labels and quotes are structural evidence only; independent semantic review remains required."}
    if "usage_journeys" in model:
        from .usage_journeys import journey_coverage
        model["usage_coverage"].update(journey_coverage(model, obligations, behaviors, bindings))
