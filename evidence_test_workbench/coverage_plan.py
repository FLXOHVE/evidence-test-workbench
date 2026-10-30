"""Source-first obligations and shared-state change/consumer coverage.

The host interprets requirements. This module checks the declared obligations,
source accounting, matrix completeness and actual ordered history witnesses.
It cannot discover omitted consumers or prove natural-language equivalence.
"""
from copy import deepcopy

from .module_generation import GenerationError

POLICY = "source-coverage-plan-v1"
INSTRUCTIONS = """
先从已读需求建立coverage_plan，再设计scenarios；不能从已有用例反推完整覆盖。
按实际适用性考虑使用情境、条件分支、边界、状态变化、失败、取消、恢复、保存及耦合，不为凑数强套所有维度。
每个obligation写一个主要目的、适用条件、来源、状态和判定；planned必须绑定实际检查步骤，未知按gap_rule/gap_method/unresearched保留，不用普通错误值或配置显示代替特定历史与实际效果。
共享数据/配置/权限/记录/资源须从来源盘点changes与consumers，逐变化×消费方留一项cell。消费方包括进入、使用中、退出及恢复操作中实际读取该资源的地方；不只列本模块已写过的场景。
同组布尔/枚举也逐保存/恢复触发反查。保存前态与默认/回退可区分，重置先设非默认；事件后先消费而非重新选值。开关读回不代表受其限制的操作资格或真实输出已验证。规则和方法均已知却未写检查属于生成工作，不能以unresearched或产品gap结束；未知只用于真实未查/未定的局部。
change.observation_ids由来源语义决定，例如旧值拒绝/新值接受，或新状态保持；不是所有资源都套同样观察。每个planned cell逐观察绑定obligation和history。
history必须指出真实change_ref与consumer_ref。变更步骤须引用该change的确认声明，消费检查须引用该consumer的确认声明；同场景先变更后消费，跨场景必须沿显式continuation交接同一对象/数据/历史。直接准备一个默认状态的普通错误用例不算变更后覆盖。
无影响必须有确认来源；未知/不适用说明具体依据和范围，不能因缺方法删除消费者。消费者目录本身仍需独立从完整来源挑战，程序矩阵齐全不等于语义完整。
coverage_plan.obligations[].checks和history引用方法展开前的紧凑step_index（零基）；公共方法中的检查另给method_step_index。quote可省略，由程序复制实际expected；不自动判断引用语义。
新用例每个场景至少有一个planned义务的实际检查。已引用规则不等于所有分支已覆盖，已有旧用例全部保留也不等于新范围完整。不预设最终条数。
"""
GUIDE = {
    "obligations": [{"id": "source-derived-goal", "purpose": "one purpose", "condition": "relevant context/history",
        "kind": "normal|rejection|boundary|transition|recovery|persistence|interaction|effect",
        "claim_ids": ["confirmed claim IDs, including source support"],
        "status": "planned|gap_rule|gap_method|unresearched|not_applicable",
        "checks": [{"scenario_id": "actual scenario", "step_index": 0}], "gap_ids": [], "reason": "why required or unresolved"}],
    "shared_state": {"reason": "source-based inventory or why no shared state is relevant", "resources": [{
        "id": "resource", "claim_ids": ["source IDs defining sharing"],
        "changes": [{"id": "mutation", "claim_ids": ["specific mutation rule"], "observation_ids": ["source-defined observation"]}],
        "consumers": [{"id": "consumer operation", "claim_ids": ["specific consumer rule"]}],
        "cells": [{"change_id": "mutation", "consumer_id": "consumer operation", "status": "planned|no_effect|gap_rule|gap_method|unresearched|not_applicable",
            "claim_ids": [], "reason": "source-based applicability", "observations": [{"id": "source-defined observation", "obligation_id": "source-derived-goal",
                "history": {"change_ref": {"scenario_id": "producer", "step_index": 0},
                            "consumer_ref": {"scenario_id": "consumer", "step_index": 1}}}]}]}]}
}
STATUSES = {"planned", "gap_rule", "gap_method", "unresearched", "not_applicable"}
KINDS = {"normal", "rejection", "boundary", "transition", "recovery", "persistence", "interaction", "effect"}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _index(values, label):
    if not isinstance(values, list) or any(not isinstance(x, dict) or not _text(x.get("id")) for x in values):
        raise GenerationError(label + " requires named objects")
    indexed = {x["id"]: x for x in values}
    if len(indexed) != len(values):
        raise GenerationError("Duplicate " + label)
    return indexed


def _refs(refs, known, label, *, required=True):
    if (not isinstance(refs, list) or (required and not refs) or any(not isinstance(x, str) or x not in known for x in refs)
            or len(set(refs)) != len(refs)):
        raise GenerationError("Invalid " + label)
    return set(refs)


def validate(request, original, expanded):
    if "coverage_plan_policy" not in request:
        if "coverage_plan" in original:
            raise GenerationError("Coverage plan requires its prepared policy; do not migrate frozen inputs implicitly")
        return None
    if request["coverage_plan_policy"] != POLICY:
        raise GenerationError("Unsupported coverage plan policy")
    plan = deepcopy(original.get("coverage_plan"))
    if not isinstance(plan, dict) or set(plan) != {"obligations", "shared_state"}:
        raise GenerationError("A source-first coverage_plan is required before case coverage can be claimed")
    claims = {c["id"] for c in expanded["claims"] if c.get("semantic_status") == "confirmed"}
    scenes = _index(original["scenarios"], "scenarios")
    lowered = _index(expanded["scenarios"], "expanded scenarios")
    gaps = _index(original["gaps"], "gaps")
    obligations = _index(plan["obligations"], "planned obligations")
    if not obligations:
        raise GenerationError("Coverage plan must retain source-derived obligations, including unresolved ones")

    def bind(ref):
        if not isinstance(ref, dict) or set(ref) - {"scenario_id", "step_index", "method_step_index", "quote"}:
            raise GenerationError("Invalid coverage-plan step reference")
        sid, index = ref.get("scenario_id"), ref.get("step_index")
        if not _text(sid) or sid not in scenes or type(index) is not int or not 0 <= index < len(scenes[sid]["steps"]):
            raise GenerationError("Coverage plan references an unknown compact step")
        candidates = [(i, s) for i, s in enumerate(lowered[sid]["steps"]) if s["_compact_step_index"] == index]
        if "method_id" in scenes[sid]["steps"][index]:
            at = ref.get("method_step_index")
            if type(at) is not int or not 0 <= at < len(candidates):
                raise GenerationError("Coverage check in a method needs method_step_index")
        else:
            if "method_step_index" in ref:
                raise GenerationError("method_step_index is only for a method call")
            at = 0
        position, step = candidates[at]
        quote = ref.get("quote", step.get("expected"))
        if not _text(quote) or not _text(step.get("expected")) or quote not in step["expected"]:
            raise GenerationError("Coverage check must bind an actual observable result")
        return {**deepcopy(ref), "quote": quote, "expanded_step_index": position,
                "action": step.get("action"), "expected": step.get("expected")}, step

    planned_scenes, plan_claims = set(), set()
    for obligation in obligations.values():
        fields = {"id", "purpose", "condition", "kind", "claim_ids", "status", "checks", "gap_ids", "reason"}
        if request.get("coverage_closure_policy"):
            if "verification" in obligation:
                fields.add("verification")
            if obligation.get("status") == "planned":
                from .coverage_closure import validate_probe
                validate_probe(obligation.get("verification"))
            elif obligation.get("verification") is not None:
                raise GenerationError("Unresolved obligations cannot claim verification probes")
        if (set(obligation) != fields
                or not all(_text(obligation.get(k)) for k in ("purpose", "condition", "reason"))
                or not _text(obligation.get("status")) or obligation["status"] not in STATUSES
                or not _text(obligation.get("kind")) or obligation["kind"] not in KINDS):
            raise GenerationError("Invalid source-derived coverage obligation")
        status = obligation["status"]
        plan_claims |= _refs(obligation["claim_ids"], claims, "obligation source claims", required=status in {"planned", "gap_method", "not_applicable"})
        gids = _refs(obligation["gap_ids"], gaps, "obligation gaps", required=status in {"gap_rule", "gap_method"})
        if status in {"planned", "not_applicable"} and gids:
            raise GenerationError("Planned/excluded obligations cannot hide unresolved gaps")
        if status in {"gap_rule", "gap_method"} and any(gaps[g]["status"] != status for g in gids):
            raise GenerationError("Coverage obligation must retain its precise gap classification")
        if not isinstance(obligation["checks"], list) or (status == "planned") != bool(obligation["checks"]):
            raise GenerationError("Planned obligations need actual checks; unresolved obligations cannot claim them")
        normalized = []
        for ref in obligation["checks"]:
            bound, step = bind(ref)
            if not set(step.get("claim_ids", scenes[bound["scenario_id"]].get("claim_ids", []))) & set(obligation["claim_ids"]):
                raise GenerationError("Coverage check lacks the obligation's actual rule evidence")
            normalized.append(bound)
            planned_scenes.add(bound["scenario_id"])
        obligation["checks"] = normalized
    if scenes.keys() - planned_scenes:
        raise GenerationError("Cases without a source-planned check cannot establish complete coverage")
    shared = plan["shared_state"]
    if not isinstance(shared, dict) or set(shared) != {"reason", "resources"} or not _text(shared["reason"]):
        raise GenerationError("Shared-state inventory must be explicitly researched or bounded")

    def ordered(change, consumer):
        a, b = change["scenario_id"], consumer["scenario_id"]
        if a == b:
            return change["expanded_step_index"] < consumer["expanded_step_index"]
        seen = set()
        while b in scenes and b not in seen:
            seen.add(b)
            continuation = scenes[b].get("continuation")
            if not isinstance(continuation, dict):
                return False
            from .case_decomposition import case_id
            predecessor = continuation.get("scenario_id")
            if (not _text(predecessor) or predecessor not in scenes or continuation.get("case_id") != case_id(request["case_namespace"], predecessor)
                    or any(scenes[s].get("variants", [{"id": "base", "bindings": {}}]) != [{"id": "base", "bindings": {}}]
                           or "integer_boundary" in scenes[s] for s in (b, predecessor))):
                raise GenerationError("Cross-case state history needs unambiguous base-case continuation bindings")
            b = predecessor
            if b == a:
                return True
        return False

    for resource in _index(shared["resources"], "shared resources").values():
        if set(resource) != {"id", "claim_ids", "changes", "consumers", "cells"}:
            raise GenerationError("Invalid shared resource fields")
        plan_claims |= _refs(resource["claim_ids"], claims, "shared-resource claims")
        changes = _index(resource["changes"], "resource changes")
        consumers = _index(resource["consumers"], "resource consumers")
        if not changes or not consumers:
            raise GenerationError("A shared resource needs actual changes and consumers from sources")
        for change in changes.values():
            if set(change) != {"id", "claim_ids", "observation_ids"}:
                raise GenerationError("Invalid shared-state change")
            plan_claims |= _refs(change["claim_ids"], claims, "change claims")
            obs = change["observation_ids"]
            if not isinstance(obs, list) or not obs or any(not _text(x) for x in obs) or len(set(obs)) != len(obs):
                raise GenerationError("A change needs source-defined observation IDs")
        for consumer in consumers.values():
            if set(consumer) != {"id", "claim_ids"}:
                raise GenerationError("Invalid resource consumer")
            plan_claims |= _refs(consumer["claim_ids"], claims, "consumer claims")
        seen = set()
        if not isinstance(resource["cells"], list):
            raise GenerationError("Resource coverage cells must be an array")
        for cell in resource["cells"]:
            if (not isinstance(cell, dict) or set(cell) != {"change_id", "consumer_id", "status", "claim_ids", "reason", "observations"}
                    or not _text(cell.get("reason")) or not _text(cell.get("status"))
                    or cell["status"] not in STATUSES | {"no_effect"}
                    or not _text(cell.get("change_id")) or not _text(cell.get("consumer_id"))):
                raise GenerationError("Invalid change-consumer disposition")
            key = (cell["change_id"], cell["consumer_id"])
            if key in seen or key[0] not in changes or key[1] not in consumers:
                raise GenerationError("Unknown or repeated change-consumer pair")
            seen.add(key)
            plan_claims |= _refs(cell["claim_ids"], claims, "cell claims", required=cell["status"] in {"no_effect", "not_applicable"})
            observations = _index(cell["observations"], "consumer observations")
            required = set(changes[key[0]]["observation_ids"])
            if cell["status"] != "planned":
                if observations:
                    raise GenerationError("Unresolved/no-effect pairs cannot claim planned history observations")
                continue
            if observations.keys() != required:
                raise GenerationError("A consumer omitted a required observation of the state change")
            for obs in observations.values():
                if (set(obs) != {"id", "obligation_id", "history"} or not _text(obs.get("obligation_id"))
                        or obs["obligation_id"] not in obligations):
                    raise GenerationError("Consumer observation needs an existing planned obligation")
                obligation = obligations[obs["obligation_id"]]
                history = obs["history"]
                if obligation["status"] != "planned" or not isinstance(history, dict) or set(history) != {"change_ref", "consumer_ref"}:
                    raise GenerationError("Consumer coverage needs actual change and consumption history")
                change_ref, producer_step = bind(history["change_ref"])
                consumer_ref, consumer_step = bind(history["consumer_ref"])
                if (not set(producer_step.get("claim_ids", scenes[change_ref["scenario_id"]].get("claim_ids", []))) & set(changes[key[0]]["claim_ids"])
                        or not set(consumer_step.get("claim_ids", scenes[consumer_ref["scenario_id"]].get("claim_ids", []))) & set(consumers[key[1]]["claim_ids"])):
                    raise GenerationError("A default-state case cannot substitute for the actual change/consumer rule")
                if not ordered(change_ref, consumer_ref):
                    raise GenerationError("State change must precede consumption in the same path or explicit continuation chain")
                if not any(c["scenario_id"] == consumer_ref["scenario_id"] and c["expanded_step_index"] == consumer_ref["expanded_step_index"]
                           for c in obligation["checks"]):
                    raise GenerationError("Consumer history is not the obligation's actual check")
                obs["history"] = {"change_ref": change_ref, "consumer_ref": consumer_ref}
        if seen != {(a, b) for a in changes for b in consumers}:
            raise GenerationError("Shared-state change × consumer coverage has an undisposed pair")
    # Every covered source must also appear in the source-derived analysis.
    # Supporting navigation evidence may accompany a functional obligation.
    claim_records = {c["id"]: c for c in expanded["claims"]}
    for disposition in original["source_dispositions"]:
        if disposition["status"] != "covered":
            continue
        unit = next(u for u in request["source_units"] if u["id"] == disposition["unit_id"])
        if not any(c["source_id"] == unit["source_id"] and (
                any(r.get("id") == unit["rule_id"] for r in c.get("rule_refs", [])) if "rule_id" in unit
                else c["quote"] in unit["text"] or unit["text"] in c["quote"])
                for cid, c in claim_records.items() if cid in plan_claims):
            raise GenerationError("A covered source unit has no source-planned obligation")
    return {"policy": POLICY, "analysis": plan, "claim_ids": sorted(plan_claims),
            "case_bindings": [], "generated_obligations": [], "generated_pairs": [], "unresolved_obligation_ids": [],
            "unresolved_pairs": [], "semantic_verified": False, "complete": False}


def refresh(model, bindings=None):
    if "coverage_plan_policy" not in model:
        return
    plan = model.get("coverage_plan")
    if model["coverage_plan_policy"] != POLICY or not isinstance(plan, dict) or plan.get("policy") != POLICY:
        raise GenerationError("Stored source coverage plan was removed or changed")
    from .module_generation import _render
    cases = {c["id"]: c for c in model.get("cases", [])}
    actual = bindings if bindings is not None else plan["case_bindings"]
    plan["case_bindings"] = [deepcopy(b) for b in actual if b["case_id"] in cases]
    by_case = {b["case_id"]: b for b in plan["case_bindings"]}
    def bound_cases(check):
        ids = []
        for cid, case in cases.items():
            if case.get("generation", {}).get("recipe_id") != check["scenario_id"]:
                continue
            at = check["expanded_step_index"]
            binding = by_case.get(cid)
            if (not binding or not 0 <= at < len(case["steps"])
                    or any(_render(check[field], binding["bindings"]) != case["steps"][at][field]
                           for field in ("action", "expected"))):
                raise GenerationError("Planned check/history no longer matches the actual rendered case")
            ids.append(cid)
        return sorted(ids)
    rows = []
    for obligation in plan["analysis"]["obligations"]:
        observations = []
        for check in obligation["checks"]:
            observations.append({"scenario_id": check["scenario_id"], "case_ids": bound_cases(check)})
        status = obligation["status"]
        if status == "planned":
            status = "planned_unreviewed" if all(x["case_ids"] for x in observations) else "not_generated_in_scope"
        rows.append({"id": obligation["id"], "status": status, "checks": observations})
    plan["generated_obligations"] = rows
    plan["unresolved_obligation_ids"] = [r["id"] for r in rows if r["status"] not in {"planned_unreviewed", "not_applicable"}]
    pairs = []
    for resource in plan["analysis"]["shared_state"]["resources"]:
        for cell in resource["cells"]:
            status = cell["status"]
            if status == "planned":
                histories = [bool(bound_cases(ref)) for obs in cell["observations"]
                             for ref in obs["history"].values()]
                status = "planned_unreviewed" if all(histories) else "not_generated_in_scope"
            pairs.append({"resource_id": resource["id"], "change_id": cell["change_id"],
                          "consumer_id": cell["consumer_id"], "status": status})
    plan["generated_pairs"] = pairs
    plan["unresolved_pairs"] = [row for row in pairs if row["status"] not in {"planned_unreviewed", "no_effect", "not_applicable"}]
    plan["semantic_verified"] = plan["complete"] = False


def model_gaps(model):
    if "coverage_plan_policy" not in model:
        return []
    checked = deepcopy(model)
    refresh(checked)
    if checked["coverage_plan"] != model.get("coverage_plan"):
        raise GenerationError("Source coverage plan differs from actual case bindings")
    plan = checked["coverage_plan"]
    return [{"code": "source_coverage_unresolved", "message": "来源覆盖义务尚未实际生成或仍未闭合。",
             "obligation_id": oid, "affected_case_ids": [], "affected_obligation_ids": []}
            for oid in plan["unresolved_obligation_ids"]] + [
        {"code": "shared_state_coverage_unresolved", "message": "共享状态变化的消费方覆盖尚未闭合。",
         **row, "affected_case_ids": [], "affected_obligation_ids": []} for row in plan["unresolved_pairs"]]


def merge_plans(plans):
    """Transport only: union declarations; never invent missing matrix cells.

    A final parent compile checks cross-chunk pairs/history. Reused IDs must
    have identical definitions; incompatible declarations need author repair.
    """
    result = {"obligations": [], "shared_state": {"reason": "", "resources": []}}
    obligations, resources, reasons = {}, {}, []
    for plan in plans:
        if not isinstance(plan, dict) or set(plan) != {"obligations", "shared_state"}:
            raise GenerationError("Each new-policy chunk needs its source coverage plan")
        for oid, obligation in _index(plan["obligations"], "chunk source obligations").items():
            if oid in obligations and obligations[oid] != obligation:
                raise GenerationError("Conflicting source obligations across chunks")
            obligations[oid] = deepcopy(obligation)
        shared = plan["shared_state"]
        if not isinstance(shared, dict) or set(shared) != {"reason", "resources"} or not _text(shared["reason"]):
            raise GenerationError("Invalid chunk shared-state inventory")
        if shared["reason"] not in reasons:
            reasons.append(shared["reason"])
        for rid, resource in _index(shared["resources"], "chunk resources").items():
            if set(resource) != {"id", "claim_ids", "changes", "consumers", "cells"}:
                raise GenerationError("Invalid chunk resource fields")
            target = resources.setdefault(rid, {"id": rid, "claim_ids": [], "changes": [], "consumers": [], "cells": []})
            if not isinstance(resource["claim_ids"], list) or any(not _text(x) for x in resource["claim_ids"]):
                raise GenerationError("Invalid chunk resource sources")
            target["claim_ids"] = sorted(set(target["claim_ids"]) | set(resource["claim_ids"]))
            for field in ("changes", "consumers"):
                old = _index(target[field], "merged resource " + field)
                for key, value in _index(resource[field], "chunk resource " + field).items():
                    if key in old and old[key] != value:
                        raise GenerationError("Conflicting shared resource definitions across chunks")
                    old[key] = deepcopy(value)
                target[field] = [old[key] for key in sorted(old)]
            old_cells = {(c["change_id"], c["consumer_id"]): c for c in target["cells"]}
            if not isinstance(resource["cells"], list):
                raise GenerationError("Invalid chunk coverage cells")
            seen = set()
            for cell in resource["cells"]:
                if not isinstance(cell, dict) or not _text(cell.get("change_id")) or not _text(cell.get("consumer_id")):
                    raise GenerationError("Invalid chunk coverage cell")
                key = (cell["change_id"], cell["consumer_id"])
                if key in seen or key in old_cells and old_cells[key] != cell:
                    raise GenerationError("Conflicting or repeated coverage cells across chunks")
                seen.add(key)
                old_cells[key] = deepcopy(cell)
            target["cells"] = [old_cells[key] for key in sorted(old_cells)]
    result["obligations"] = [obligations[key] for key in sorted(obligations)]
    result["shared_state"] = {"reason": "\n".join(reasons), "resources": [resources[key] for key in sorted(resources)]}
    return result


def repair_bindings(original, candidate, scenario_ids, *, addition_ids=frozenset(), cell_targets=frozenset()):
    """Only rebind existing observations in the reviewed scenario group.

    Purpose, source, status, matrix, observation count and scope are immutable.
    The ordinary compiler checks every new coordinate and witness afterwards.
    """
    normalized = deepcopy(candidate)
    reviewed_goals = {o["obligation_id"] for r in original["shared_state"]["resources"] for c in r["cells"]
                      if (r["id"], c["change_id"], c["consumer_id"]) in cell_targets for o in c["observations"]}
    # Explicit review additions use the same round and immutable denominator.
    # Only append new planned goals for new scenarios; existing meanings/matrix
    # remain byte-identical after ordinary coordinate rebinding.
    if addition_ids or cell_targets:
        try:
            tail = normalized["obligations"][len(original["obligations"]):]
            known = {r["id"] for r in original["obligations"]}
            allowed_scenes = set(addition_ids) | (set(scenario_ids) if cell_targets else set())
            if ((not tail and addition_ids) or any(not isinstance(r, dict) or r.get("id") in known
                    or r.get("status") != "planned" or r.get("gap_ids") != [] or not r.get("checks")
                    or any(ref.get("scenario_id") not in allowed_scenes for ref in r["checks"]) for r in tail)
                    or not set(addition_ids) <= {ref["scenario_id"] for r in tail for ref in r["checks"]}):
                raise GenerationError("Repair additions must append planned checks for exactly the new scenes")
            target_goals = {o["obligation_id"] for r in normalized["shared_state"]["resources"] for c in r["cells"]
                            if (r["id"], c["change_id"], c["consumer_id"]) in cell_targets for o in c["observations"]}
            if any(r["id"] not in target_goals and not any(ref["scenario_id"] in addition_ids for ref in r["checks"]) for r in tail):
                raise GenerationError("Additional repair goals must serve reviewed cells or new scenarios")
            normalized["obligations"] = normalized["obligations"][:len(original["obligations"])]
        except (KeyError, TypeError, AttributeError) as exc:
            raise GenerationError("Malformed additional repair coverage") from exc
    def references(old_refs, new_refs):
        if not isinstance(new_refs, list) or len(old_refs) != len(new_refs):
            raise GenerationError("Repair cannot add/remove source coverage checks")
        for old, new in zip(old_refs, new_refs):
            if old != new and (not isinstance(new, dict) or old.get("scenario_id") not in scenario_ids
                               or new.get("scenario_id") != old.get("scenario_id")):
                raise GenerationError("Coverage binding repair escaped the reviewed scenario group")
    try:
        if len(original["obligations"]) != len(normalized["obligations"]):
            raise GenerationError("Repair must preserve source obligations")
        for old, new in zip(original["obligations"], normalized["obligations"]):
            if old["id"] in reviewed_goals:
                # A reviewed witness may need more than one discriminating
                # stimulus. Keep the business goal/source/status immutable;
                # revise its test condition and actual probes in the same
                # scenario group, then let the ordinary compiler check them.
                old_sids = {r["scenario_id"] for r in old["checks"]}
                refs = new.get("checks")
                if (not isinstance(refs, list) or not refs
                        or {r.get("scenario_id") for r in refs} != old_sids or not old_sids <= scenario_ids):
                    raise GenerationError("Reviewed cell probes must stay in the same scenario group")
                if "verification" in old:
                    if {k: v for k, v in old["verification"].items() if k != "reason"} != {k: v for k, v in new.get("verification", {}).items() if k != "reason"}:
                        raise GenerationError("Reviewed probe cannot change its verification kind")
                for key in ("condition", "checks", "reason", "verification"):
                    if key in old:
                        new[key] = deepcopy(old[key])
                continue
            references(old["checks"], new["checks"])
            new["checks"] = deepcopy(old["checks"])
        old_resources = original["shared_state"]["resources"]
        new_resources = normalized["shared_state"]["resources"]
        if len(old_resources) != len(new_resources):
            raise GenerationError("Repair must preserve shared resources")
        for old_resource, new_resource in zip(old_resources, new_resources):
            if len(old_resource["cells"]) != len(new_resource["cells"]):
                raise GenerationError("Repair must preserve change-consumer cells")
            for old_cell, new_cell in zip(old_resource["cells"], new_resource["cells"]):
                if (old_resource["id"], old_cell["change_id"], old_cell["consumer_id"]) in cell_targets:
                    if set(new_cell) != set(old_cell) or any(new_cell[k] != old_cell[k] for k in set(old_cell) - {"status", "reason", "observations"}):
                        raise GenerationError("Cell repair must preserve resource/source meaning")
                    for k in ("status", "reason", "observations"):
                        new_cell[k] = deepcopy(old_cell[k])
                    continue
                if len(old_cell["observations"]) != len(new_cell["observations"]):
                    raise GenerationError("Repair must preserve source observations")
                for old_obs, new_obs in zip(old_cell["observations"], new_cell["observations"]):
                    for end in ("change_ref", "consumer_ref"):
                        references([old_obs["history"][end]], [new_obs["history"][end]])
                        new_obs["history"][end] = deepcopy(old_obs["history"][end])
    except (KeyError, TypeError) as exc:
        raise GenerationError("Malformed coverage binding repair") from exc
    if normalized != original:
        raise GenerationError("Repair may only rebind source checks, not change coverage meaning or scope")
    return deepcopy(candidate)


def update_analysis(original, candidate, *, claim_ids, scenario_ids, gap_ids):
    """Source-update transport: preserve declarations outside the impact scope.

    This authorizes edits, never their semantic correctness. The parent source
    compiler and unchanged-case checks still run before atomic publication.
    """
    def related(value):
        if isinstance(value, list):
            return any(related(x) for x in value)
        if not isinstance(value, dict):
            return False
        return (bool(set(value.get("claim_ids", [])) & claim_ids)
                or bool(set(value.get("gap_ids", [])) & gap_ids)
                or value.get("scenario_id") in scenario_ids
                or any(related(x) for x in value.values()))
    def preserve(old_values, new_values, label):
        old, new = _index(old_values, "old " + label), _index(new_values, "new " + label)
        for key in old.keys() | new.keys():
            if old.get(key) != new.get(key) and not (related(old.get(key)) or related(new.get(key))):
                raise GenerationError("Source plan update changes an unaffected " + label)
    try:
        if not isinstance(candidate, dict) or set(candidate) != {"obligations", "shared_state"}:
            raise GenerationError("A source plan update needs the complete replacement analysis")
        preserve(original["obligations"], candidate["obligations"], "obligation")
        shared = candidate["shared_state"]
        if not isinstance(shared, dict) or set(shared) != {"reason", "resources"}:
            raise GenerationError("Malformed updated shared-state analysis")
        preserve(original["shared_state"]["resources"], shared["resources"], "shared resource")
    except (KeyError, TypeError) as exc:
        raise GenerationError("Malformed source coverage update") from exc
    return deepcopy(candidate)
