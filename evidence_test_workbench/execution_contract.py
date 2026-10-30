"""Explicit preparation use and execution wording, without inferring business truth."""
from copy import deepcopy

POLICY = "execution-authoring-v1"
INSTRUCTIONS = """\n执行稿规则：共享准备按单一条件定义，每个场景仅选实际需要的条件；
preparation_uses逐preparation_id给实际紧凑step_indices和具体reason，不复制整个功能族的准备。
声音等比较须保留现场观察能力限制，不能靠新增文字获得精度；不能可靠判定时明确不确定。
expected只写该步可观察要求及必要判定；来源读取/作者推理说明移到review_notes，
执行时不可忽略的限制写observation_limit。公共导航引用原method_id，不删除真实状态历史。
"""


def validate(request, response):
    active = request.get("execution_authoring_policy") or response.get("execution_authoring_policy")
    if not active:
        return None
    if active != POLICY or response.get("execution_authoring_policy") != POLICY:
        raise ValueError("Execution authoring must explicitly retain its policy")
    result = {}
    for scene in response["scenarios"]:
        uses = scene.get("preparation_uses")
        if not isinstance(uses, list) or len(uses) != len(scene["preparation_ids"]):
            raise ValueError("Every selected preparation needs its own actual-use link")
        seen = set()
        for row in uses:
            if (not isinstance(row, dict) or set(row) != {"preparation_id", "step_indices", "reason"}
                    or row["preparation_id"] not in scene["preparation_ids"] or row["preparation_id"] in seen
                    or not isinstance(row["reason"], str) or not row["reason"].strip()
                    or not isinstance(row["step_indices"], list) or not row["step_indices"]
                    or any(type(i) is not int or not 0 <= i < len(scene["steps"]) for i in row["step_indices"])
                    or len(set(row["step_indices"])) != len(row["step_indices"])):
                raise ValueError("Preparation use must name unique real steps and a specific reason")
            seen.add(row["preparation_id"])
        for step in scene["steps"]:
            if "method_id" in step:
                continue
            notes = step.get("review_notes", [])
            if not isinstance(notes, list) or any(not isinstance(s, str) or not s.strip() for s in notes):
                raise ValueError("Review notes must remain explicit nonempty strings")
            limit = step.get("observation_limit")
            if limit is not None and (not isinstance(limit, str) or not limit.strip()):
                raise ValueError("Observation limits must be explicit execution instructions")
        result[scene["id"]] = deepcopy(uses)
    return result


def annotate_case(case, recipe, behaviors, bindings=None):
    """Keep complete executable rows; grouping is a readable navigation view only."""
    if "preparation_uses" not in recipe:
        return
    case["generation"]["execution_authoring_policy"] = POLICY
    case["generation"]["preparation_uses"] = [{
        "precondition_index": recipe["preparation_ids"].index(use["preparation_id"]),
        "preparation_id": use["preparation_id"],
        "step_indices": [i for i, bid in enumerate(recipe["path"])
                         if behaviors[bid].get("compact_step_index") in use["step_indices"]],
        "reason": use["reason"]} for use in recipe["preparation_uses"]]
    notes, groups = [], []
    from .module_generation import _render
    for i, bid in enumerate(recipe["path"]):
        behavior = behaviors[bid]
        for note in behavior.get("review_notes", []):
            note = _render(note, bindings or {})
            if note not in notes:
                notes.append(note)
        if behavior.get("navigation_method"):
            mid = behavior["navigation_method"]
            compact = behavior["compact_step_index"]
            if not groups or groups[-1]["compact_step_index"] != compact:
                groups.append({"method_id": mid, "name": behavior.get("navigation_name", mid),
                               "compact_step_index": compact, "step_indices": []})
            groups[-1]["step_indices"].append(i)
    if notes:
        case["review_notes"] = notes
    case["generation"]["navigation_groups"] = groups


def validate_case(case):
    if case.get("generation", {}).get("execution_authoring_policy") != POLICY:
        return
    uses = case["generation"].get("preparation_uses", [])
    if {r["precondition_index"] for r in uses} != set(range(len(case["preconditions"]))):
        raise ValueError("Stored preparation use lost a selected condition")
    for row in uses:
        if not row["step_indices"] or any(type(i) is not int or not 0 <= i < len(case["steps"]) for i in row["step_indices"]):
            raise ValueError("Stored preparation use does not reach real steps")
    seen = set()
    for group in case["generation"].get("navigation_groups", []):
        indices = group["step_indices"]
        if (not indices or indices != list(range(indices[0], indices[-1] + 1))
                or seen.intersection(indices) or any(i >= len(case["steps"]) or i < 0 for i in indices)):
            raise ValueError("Navigation grouping cannot hide, overlap or reorder steps")
        seen.update(indices)


def rebind_execution_quotes(original, revised):
    """Re-anchor literal citations to the same action after prose relocation.

    This does not decide whether an assertion was wrongly moved to a note.
    The full old/new text remains available to the independent reviewer.
    """
    from difflib import SequenceMatcher
    before = {s["id"]: s for s in original["scenarios"]}
    after = {s["id"]: s for s in revised["scenarios"]}
    if before.keys() != after.keys() or any([s.get("action", s.get("method_id")) for s in before[k]["steps"]]
            != [s.get("action", s.get("method_id")) for s in after[k]["steps"]] for k in before):
        raise ValueError("Wording rebind must retain all actual actions and their order")
    result, ledger = deepcopy(revised), []
    after = {s["id"]: s for s in result["scenarios"]}
    preparations = {p["id"]: p for p in result["preparations"]}
    for sid, scene in after.items():
        continuation = scene.get("continuation")
        if not continuation:
            continue
        parent = after[continuation["scenario_id"]]["steps"][-1]
        if "method_id" in parent:
            continue  # The frozen shared method's actual result did not change.
        expected = parent["expected"]
        if parent.get("observation_limit") and parent["observation_limit"] not in expected:
            expected += "\n判定边界：" + parent["observation_limit"]
        previous = continuation["predecessor_expected"]
        if expected != previous:
            continuation["predecessor_expected"] = expected
            ledger.append({"kind": "continuation_literal", "scenario_id": sid,
                           "old_quote": previous, "new_quote": expected, "semantic_equivalence_proved": False})
            if continuation.get("on_outcome") != "any":
                for pid in scene["preparation_ids"]:
                    if preparations[pid]["state"] == previous:
                        preparations[pid]["state"] = expected
    def visit(value, path):
        if isinstance(value, list):
            for i, row in enumerate(value):
                visit(row, path + [i])
        elif isinstance(value, dict):
            sid, at = value.get("scenario_id"), value.get("step_index")
            if sid in after and type(at) is int:
                old, new = before[sid]["steps"][at], after[sid]["steps"][at]
                if "method_id" not in old:
                    expected = new["expected"]
                    if new.get("observation_limit") and new["observation_limit"] not in expected:
                        expected += "\n判定边界：" + new["observation_limit"]
                    for key in ("expected_quote", "quote"):
                        quote = value.get(key)
                        if not isinstance(quote, str) or quote in expected or quote in new["action"]:
                            continue
                        if quote not in old["expected"]:
                            raise ValueError("Cannot rebind a quote that was not in its original actual step")
                        match = SequenceMatcher(None, quote, expected, autojunk=False).find_longest_match()
                        anchor = quote[match.a:match.a + match.size].strip()
                        if not anchor or not any(c.isalnum() for c in anchor):
                            raise ValueError("Wording change lost its literal observable anchor; needs semantic review")
                        value[key] = anchor
                        ledger.append({"path": path + [key], "scenario_id": sid, "step_index": at,
                                       "old_quote": quote, "new_quote": anchor,
                                       "semantic_equivalence_proved": False})
            for key, row in value.items():
                visit(row, path + [key])
    for field in ("coverage_plan", "usage_goals", "usage_journeys", "source_branch_dispositions"):
        if field in result:
            visit(result[field], [field])
    return result, ledger
