"""Bind every original ordered user change to a compact step or an open gap.

The host supplies the interpretation and continuity explanation. Coordinates,
quotes and rendered case checks establish traceability, never semantic truth.
Only requests explicitly opting into this version require the new contract.
"""
from copy import deepcopy

from .module_generation import GenerationError


POLICY = "usage-journeys-v1"
STATUSES = {"step", "unresearched", "gap_rule", "gap_method", "out_of_scope"}
FIELDS = {"change_index", "change", "status", "step_ref", "gap_ids", "reason", "continuity"}
STEP_FIELDS = {"scenario_id", "step_index", "action_quote", "expected_quote"}
INSTRUCTIONS = """\
usage_journeys逐项保留relationship_context.profile.usage_scenarios的id、user_task、context及changes原文顺序。
每个change单独记录change_index（从0计数，重复文字仍是不同项）；status=step时引用原紧凑step的scenario_id、step_index、action_quote、expected_quote，原文子串须实际存在。
同一场景内引用的step_index不倒序；同一步可支持相邻多个变化，但引用相同不证明语义等价；跨场景须在continuity说明前后状态如何衔接，不得回到已结束的场景块。
未查变化保留unresearched；规则或方法缺口绑定实际gap_rule/gap_method，说明具体待补工作；out_of_scope说明相对原任务的取舍，不能因固定池未收录而删除。
非step项的step_ref为null；没有缺口引用时gap_ids=[]。每项reason非空，非跨场景时continuity可为空。
登记gap和交付局部用例都不代表原任务完成；程序只核结构、原序和实际步骤引用，独立评审仍须判断连续性与关键变化的业务含义。
"""
GUIDE = [{"id": "exact original usage scenario ID", "user_task": "original user_task",
          "context": "original context", "changes": [{"change_index": 0,
              "change": "original change text", "status": "step|unresearched|gap_rule|gap_method|out_of_scope",
              "step_ref": {"scenario_id": "compact scenario ID", "step_index": 0,
                           "action_quote": "verbatim action substring", "expected_quote": "verbatim expected substring"},
              "gap_ids": [], "reason": "evidence or concrete remaining work", "continuity": "cross-scenario state handoff"}]}]


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _validate_shape(journeys, originals):
    if not isinstance(journeys, list) or len(journeys) != len(originals):
        raise GenerationError("Every original user situation requires an ordered usage journey")
    for journey, original in zip(journeys, originals):
        if (not isinstance(journey, dict) or set(journey) != {"id", "user_task", "context", "changes"}
                or any(journey.get(key) != original.get(key) for key in ("id", "user_task", "context"))):
            raise GenerationError("Original usage journey identity, task, context or order was replaced")
        changes = journey["changes"]
        if not isinstance(changes, list) or len(changes) != len(original["changes"]):
            raise GenerationError("Every original usage change requires an individual disposition")
        previous, finished = None, set()
        for index, (change, text) in enumerate(zip(changes, original["changes"])):
            if (not isinstance(change, dict) or set(change) != FIELDS
                    or type(change["change_index"]) is not int or change["change_index"] != index
                    or change["change"] != text or not isinstance(change["status"], str)
                    or change["status"] not in STATUSES or not _text(change["reason"])
                    or not isinstance(change["continuity"], str)):
                raise GenerationError("Usage change fields, original text, index or order are invalid")
            ids = change["gap_ids"]
            if (not isinstance(ids, list) or any(not _text(gid) for gid in ids) or len(set(ids)) != len(ids)):
                raise GenerationError("Usage change gap_ids require unique string references")
            step = change["step_ref"]
            if change["status"] == "step":
                if (not isinstance(step, dict) or not STEP_FIELDS <= set(step)
                        or set(step) - (STEP_FIELDS | {"method_step_index"})
                        or not _text(step["scenario_id"]) or type(step["step_index"]) is not int
                        or step["step_index"] < 0 or not _text(step["action_quote"])
                        or not _text(step["expected_quote"]) or ids
                        or ("method_step_index" in step and (type(step["method_step_index"]) is not int or step["method_step_index"] < 0))):
                    raise GenerationError("A usage change step requires compact coordinates and action/result quotes")
                sid = step["scenario_id"]
                coordinate = (step["step_index"], step.get("method_step_index", 0))
                if previous:
                    if sid == previous[0] and coordinate < previous[1]:
                        raise GenerationError("Usage changes must follow the original compact step order")
                    if sid != previous[0]:
                        if not _text(change["continuity"]):
                            raise GenerationError("Cross-scenario usage changes require a continuity explanation")
                        finished.add(previous[0])
                        if sid in finished:
                            raise GenerationError("Usage changes cannot return to an already finished scenario block")
                previous = (sid, coordinate)
            elif step is not None:
                raise GenerationError("An unresolved or excluded usage change cannot claim a step")
            if change["status"] in {"gap_rule", "gap_method"}:
                if not ids:
                    raise GenerationError("Usage change gaps require an actual matching gap")
            elif ids:
                raise GenerationError("Only usage change gap dispositions may reference gaps")


def validate_usage_journeys(request, response, *, expanded_response=None):
    if "usage_journey_policy" not in request:
        if "usage_journeys" in response:
            raise GenerationError("Usage journeys require the explicitly bound journey protocol")
        return None
    if request["usage_journey_policy"] != POLICY or "relationship_context" not in request:
        raise GenerationError("Unknown or unbound usage journey protocol")
    originals = request["relationship_context"]["profile"]["usage_scenarios"]
    journeys = response.get("usage_journeys")
    _validate_shape(journeys, originals)
    scenarios = {s["id"]: s for s in response["scenarios"]}
    expanded = {s["id"]: s for s in (expanded_response or {}).get("scenarios", [])}
    gaps = {g["id"]: g for g in response["gaps"]}
    for journey in journeys:
        for change in journey["changes"]:
            status, ref = change["status"], change["step_ref"]
            if status == "step":
                steps = scenarios.get(ref["scenario_id"], {}).get("steps", [])
                if ref["step_index"] >= len(steps):
                    raise GenerationError("Usage change references an unknown original compact step")
                step = steps[ref["step_index"]]
                if "method_id" in step:
                    at = ref.get("method_step_index")
                    candidates = [s for s in expanded.get(ref["scenario_id"], {}).get("steps", [])
                                  if s.get("_compact_step_index") == ref["step_index"]]
                    if type(at) is not int or not 0 <= at < len(candidates):
                        raise GenerationError("Usage change in a public method requires a valid method_step_index and actual expansion")
                    step = candidates[at]
                elif "method_step_index" in ref:
                    raise GenerationError("method_step_index is only valid for a public method call")
                if (not isinstance(step, dict) or not isinstance(step.get("action"), str)
                        or not isinstance(step.get("expected"), str)
                        or ref["action_quote"] not in step["action"] or ref["expected_quote"] not in step["expected"]):
                    raise GenerationError("Usage change action/result quote must match its original compact step")
            elif status in {"gap_rule", "gap_method"} and any(gaps.get(gid, {}).get("status") != status for gid in change["gap_ids"]):
                raise GenerationError("Usage change gap status disagrees with its actual gap")
    return deepcopy(journeys)


def _observed_steps(path, ref):
    observed = ([b for b in path if b.get("compact_step_index") == ref["step_index"]]
        if any("compact_step_index" in b for b in path) else path[ref["step_index"]:ref["step_index"] + 1])
    if "method_step_index" in ref:
        at = ref["method_step_index"]
        observed = observed[at:at + 1]
    return observed


def validate_usage_journey_model(model, *, allow_missing_targets=False):
    if "usage_journeys" not in model:
        if model.get("usage_coverage", {}).get("journey_policy") == POLICY:
            raise GenerationError("Stored usage journey denominator was removed")
        return
    record = model.get("relationship_coverage")
    if not isinstance(record, dict):
        raise GenerationError("Stored usage journeys lost their original relationship profile")
    originals = record["context"]["profile"]["usage_scenarios"]
    _validate_shape(model["usage_journeys"], originals)
    obligations = {o["id"]: o for o in model.get("coverage_obligations", [])}
    behaviors = {b["id"]: b for b in model.get("behaviors", [])}
    for journey in model["usage_journeys"]:
        for change in journey["changes"]:
            ref = change["step_ref"]
            if ref is not None:
                target = obligations.get(ref["scenario_id"])
                if target is None:
                    if allow_missing_targets:
                        continue
                    raise GenerationError("Stored usage change references an unknown scenario")
                path = [behaviors[b] for b in target.get("behavior_ids", []) if b in behaviors]
                observed = _observed_steps(path, ref)
                if not any(isinstance(b.get("trigger"), str) and ref["action_quote"] in b["trigger"]
                        and any(isinstance(v, str) and ref["expected_quote"] in v for v in b.get("outcomes", [])) for b in observed):
                    raise GenerationError("Stored usage change no longer matches its original compact action/result")
            for gid in change["gap_ids"]:
                if gid not in obligations:
                    if allow_missing_targets:
                        continue
                    raise GenerationError("Stored usage change references an unknown gap")
                if obligations[gid].get("status") != change["status"]:
                    raise GenerationError("Stored usage change lost its matching gap status")


def journey_coverage(model, obligations, behaviors, bindings):
    """Recompute local case links while retaining the full original denominator."""
    from .module_generation import _render
    rows, unresolved = [], []
    for journey in model["usage_journeys"]:
        changes = []
        for change in journey["changes"]:
            ref, case_ids = change["step_ref"], []
            if ref is not None and ref["scenario_id"] in obligations:
                target = obligations[ref["scenario_id"]]
                target_path = [behaviors[b] for b in target.get("behavior_ids", []) if b in behaviors]
                observed = _observed_steps(target_path, ref)
                for case in model.get("cases", []):
                    if ref["scenario_id"] not in case.get("obligation_ids", []):
                        continue
                    binding = bindings.get(case["id"])
                    path = binding["path"] if binding else target.get("behavior_ids", [])
                    values = binding["bindings"] if binding else {}
                    if not binding and any("{" in ref[k] or "}" in ref[k] for k in ("action_quote", "expected_quote")):
                        continue
                    action, expected = (_render(ref[k], values) for k in ("action_quote", "expected_quote"))
                    for behavior in observed:
                        if behavior["id"] not in path:
                            continue
                        index = path.index(behavior["id"])
                        if index >= len(case.get("steps", [])):
                            continue
                        step = case["steps"][index]
                        if (isinstance(step.get("action"), str) and action in step["action"]
                                and isinstance(step.get("expected"), str) and expected in step["expected"]):
                            case_ids.append(case["id"])
                            break
            status = change["status"]
            if status == "step":
                status = "planned_unreviewed" if case_ids else "not_generated_in_scope"
            row = {"change_index": change["change_index"], "change": change["change"], "status": status,
                   "step_ref": deepcopy(ref), "gap_ids": deepcopy(change["gap_ids"]),
                   "reason": change["reason"], "continuity": change["continuity"], "case_ids": sorted(set(case_ids))}
            changes.append(row)
            if status != "planned_unreviewed":
                unresolved.append({"journey_id": journey["id"], "change_index": change["change_index"], "status": status})
        rows.append({key: deepcopy(journey[key]) for key in ("id", "user_task", "context")})
        rows[-1]["changes"] = changes
    count = sum(len(j["changes"]) for j in rows)
    return {"journey_policy": POLICY, "journeys": rows, "journey_change_count": count,
            "unresolved_journey_changes": unresolved, "all_journey_changes_generated": bool(count) and not unresolved}
