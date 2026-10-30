"""Lossless contiguous case decomposition inside a bounded review repair.

Only coordinates and execution handoffs change. No product rule or action is
inferred, rewritten, removed or copied from a different case.
"""
from copy import deepcopy
import hashlib
import json

from .module_generation import GenerationError

POLICY = "lossless-case-decomposition-v1"


def case_id(namespace, scenario_id):
    key = json.dumps([namespace, scenario_id, "base"], ensure_ascii=False)
    return namespace + "-" + hashlib.sha256(key.encode()).hexdigest()[:16]


def decompose(packet, response):
    if (packet.get("decomposition_policy") != POLICY
            or set(response) != {"schema_version", "request_id", "decompositions"}
            or type(response.get("schema_version")) is not int or response["schema_version"] != 1
            or response.get("request_id") != packet["request_id"]):
        raise GenerationError("A prepared decomposition repair is required")
    changes = response.get("decompositions")
    if not isinstance(changes, list) or not changes:
        raise GenerationError("Nonempty decomposition plans are required")
    original = packet["original_response"]
    result = deepcopy(original)
    scenes = {s["id"]: s for s in original["scenarios"]}
    allowed, seen, used = set(packet["scenario_ids"]), set(), set(scenes)
    remap, parts_by_scene = {}, {}
    added_preps = []
    request = packet["generation_request"]
    for change in changes:
        if (not isinstance(change, dict) or set(change) != {"scenario_id", "reason", "parts"}
                or change.get("scenario_id") not in allowed or change["scenario_id"] in seen
                or not isinstance(change.get("reason"), str) or not change["reason"].strip()):
            raise GenerationError("Decompose each reviewed scenario at most once with a reason")
        sid = change["scenario_id"]
        seen.add(sid)
        scene = scenes[sid]
        if (scene.get("integer_boundary") or scene.get("variants", [{"id": "base", "bindings": {}}]) != [{"id": "base", "bindings": {}}]
                or scene.get("continuation") or scene.get("decomposition")):
            raise GenerationError("Decomposition currently supports base-only paths without prior continuations")
        located = {rid for step in scene["steps"] for rid in step.get("relation_ids", [])}
        if located != set(scene.get("relation_ids", [])):
            raise GenerationError("Decomposition requires every relation to retain its actual step location")
        if any(row.get("status") == "designed" and sid in row.get("scenario_ids", [])
               for row in original.get("source_branch_dispositions", [])):
            raise GenerationError("A designed source branch must remain continuous; decomposition is not supported for that scope")
        parts = change["parts"]
        if not isinstance(parts, list) or len(parts) < 2:
            raise GenerationError("A decomposition needs at least two contiguous parts")
        cursor, built, previous = 0, [], None
        for index, part in enumerate(parts):
            if (not isinstance(part, dict) or set(part) - {"id", "start", "stop", "title", "objective", "handoff", "case_focus"}
                    or any(not isinstance(part.get(k), str) or not part[k].strip() for k in ("id", "title", "objective"))
                    or type(part.get("start")) is not int or type(part.get("stop")) is not int
                    or part["start"] != cursor or not cursor < part["stop"] <= len(scene["steps"])):
                raise GenerationError("Parts must partition every original compact step once, without deletion, duplication or reordering")
            pid = part["id"]
            if (index == 0 and pid != sid) or (index > 0 and (not pid.startswith(sid + "--") or pid in used)):
                raise GenerationError("Keep the original ID for the first part; new IDs must be unique descendants")
            used.add(pid)
            new = deepcopy(scene)
            new.update(id=pid, title=part["title"], objective=part["objective"],
                       steps=deepcopy(scene["steps"][cursor:part["stop"]]))
            if "relation_ids" in scene:
                local_relations = {rid for step in new["steps"] for rid in step.get("relation_ids", [])}
                new["relation_ids"] = [rid for rid in scene["relation_ids"] if rid in local_relations]
            if "case_focus_policy" in request:
                if "case_focus" not in part:
                    raise GenerationError("Each decomposed part must supply its own case_focus")
                new["case_focus"] = deepcopy(part["case_focus"])
            elif "case_focus" in part:
                raise GenerationError("Do not implicitly migrate a legacy task's focus policy")
            if index:
                handoff = part.get("handoff")
                if not isinstance(handoff, str) or not handoff.strip():
                    raise GenerationError("A later part requires explicit same-object/state/history handoff")
                prep_id = "continuation:" + pid
                if prep_id in {p["id"] for p in result["preparations"] + added_preps}:
                    raise GenerationError("Continuation preparation ID collision")
                predecessor = case_id(request["case_namespace"], previous)
                prior_result = scene["steps"][cursor - 1].get("expected")
                # A public method has no literal compact result; do not guess
                # which method step establishes the handoff state.
                if not isinstance(prior_result, str) or not prior_result.strip():
                    raise GenerationError("A split boundary needs an explicit prior result; cannot cut after a method placeholder")
                refs = scene["steps"][cursor - 1].get("claim_ids", scene.get("claim_ids", []))
                setup = f"先完成前驱用例 {predecessor}（{built[-1]['title']}）；确认其末步结果：{prior_result}。{handoff} 不重新执行原初始准备，不重置对象或历史。"
                added_preps.append({"id": prep_id, "state": prior_result, "setup": setup, "claim_ids": deepcopy(refs)})
                new["preparation_ids"] = [prep_id]
                new["continuation"] = {"scenario_id": previous, "case_id": predecessor,
                                       "handoff": handoff, "predecessor_expected": prior_result}
            elif part.get("handoff"):
                raise GenerationError("The first part retains original preparations, without an invented predecessor")
            new["decomposition"] = {"policy": POLICY, "original_scenario_id": sid,
                "start": cursor, "stop": part["stop"], "reason": change["reason"]}
            for old_index in range(cursor, part["stop"]):
                remap[sid, old_index] = (pid, old_index - cursor)
            built.append(new)
            previous, cursor = pid, part["stop"]
        if cursor != len(scene["steps"]):
            raise GenerationError("Decomposition omitted original steps")
        parts_by_scene[sid] = built
    result["preparations"].extend(added_preps)
    result["scenarios"] = [part for scene in original["scenarios"]
                           for part in parts_by_scene.get(scene["id"], [deepcopy(scene)])]

    def coordinate(ref):
        key = (ref.get("scenario_id"), ref.get("step_index"))
        if key in remap:
            ref["scenario_id"], ref["step_index"] = remap[key]

    def ids(values):
        return list(dict.fromkeys(part["id"] for sid in values
            for part in parts_by_scene.get(sid, [{"id": sid}])))

    for goal in result.get("usage_goals", []):
        for check in goal["effect_checks"]:
            coordinate(check)
        goal["scenario_ids"] = (list(dict.fromkeys(c["scenario_id"] for c in goal["effect_checks"]))
                                if goal["evidence_status"] == "confirmed" else ids(goal["scenario_ids"]))
    for journey in result.get("usage_journeys", []):
        for change in journey["changes"]:
            if change.get("step_ref") is not None:
                coordinate(change["step_ref"])
                new_sid = change["step_ref"]["scenario_id"]
                new_scene = next(s for s in result["scenarios"] if s["id"] == new_sid)
                if new_scene.get("continuation"):
                    change["continuity"] += " " + new_scene["continuation"]["handoff"]
    plan = result.get("coverage_plan", {})
    for obligation in plan.get("obligations", []):
        for ref in obligation.get("checks", []):
            coordinate(ref)
    for resource in plan.get("shared_state", {}).get("resources", []):
        for cell in resource.get("cells", []):
            for observation in cell.get("observations", []):
                for ref in observation.get("history", {}).values():
                    coordinate(ref)
    # Step-bound relationships move with the exact original steps. Their
    # definitions, claims and candidate conclusions remain unchanged.
    claims = {c["id"]: c for c in result["claims"]}
    units = {u["id"]: u for u in request["source_units"]}
    new_scenes = {s["id"]: s for s in result["scenarios"]}
    for row in result.get("relationship_dispositions", []):
        expanded_ids = ids(row["scenario_ids"])
        if row["status"] == "effect":
            expanded_ids = [sid for sid in expanded_ids
                            if set(new_scenes[sid].get("relation_ids", [])) & set(row["relation_ids"])]
        row["scenario_ids"] = expanded_ids
    for row in result["source_dispositions"]:
        expanded_ids = ids(row["scenario_ids"])
        rule = units[row["unit_id"]].get("rule_id")
        if row["status"] == "covered" and rule:
            expanded_ids = [sid for sid in expanded_ids if any(
                any(r.get("id") == rule for r in claims.get(cid, {}).get("rule_refs", []))
                for step in new_scenes[sid]["steps"]
                for cid in step.get("claim_ids", new_scenes[sid].get("claim_ids", [])) + step.get("exact_text_claim_ids", []))]
        row["scenario_ids"] = expanded_ids
    result["request_id"] = request["request_id"]
    return result


def validate_continuations(cases, *, included_ids=None):
    """A dependent case is not independently executable after a reset."""
    by_id = {c["id"]: c for c in cases}
    selected = set(by_id) if included_ids is None else set(included_ids)
    for cid in selected:
        seen, current = set(), cid
        while current in by_id:
            if current in seen:
                raise GenerationError("Cyclic execution continuation")
            seen.add(current)
            continuation = by_id[current].get("generation", {}).get("continuation")
            if continuation is not None and (not isinstance(continuation, dict)
                    or set(continuation) not in ({"case_id", "scenario_id", "handoff", "predecessor_expected"},
                        {"case_id", "scenario_id", "handoff", "predecessor_expected", "on_outcome", "required_state"})
                    or any(not isinstance(v, str) or not v.strip() for v in continuation.values())):
                raise GenerationError("Malformed execution continuation")
            predecessor = continuation.get("case_id") if continuation else None
            if predecessor is None:
                break
            if predecessor not in selected or predecessor not in by_id:
                raise GenerationError(f"{cid}: include required predecessor {predecessor}; a reset cannot replace its history")
            preceding_steps = by_id[predecessor].get("steps", [])
            any_outcome = continuation.get("on_outcome") == "any"
            if "on_outcome" in continuation and (not any_outcome or not isinstance(continuation.get("required_state"), str)
                                                  or not continuation["required_state"].strip()):
                raise GenerationError("Outcome-independent continuation needs an explicit actual handoff state")
            required_state = continuation["required_state"] if any_outcome else continuation["predecessor_expected"]
            if (not preceding_steps or preceding_steps[-1].get("expected") != continuation["predecessor_expected"]
                    or not any(p.get("state") == required_state
                               for p in by_id[current].get("preconditions", []))):
                raise GenerationError("Execution continuation no longer matches its predecessor's actual final result/start state")
            current = predecessor
