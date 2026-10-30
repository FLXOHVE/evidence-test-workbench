"""Account for recalled dependencies without turning recall into product truth.

The host still interprets sources.  These checks bind that interpretation to
the search boundary and to ordered, source-backed scenario steps, not just a
bag of relation IDs.  They neither enumerate all scenarios nor prove semantics.
"""
from copy import deepcopy
from .module_generation import GenerationError


def _quote_overlap(left, right):
    """Locator lines may include table indentation absent from exact claims.

    Ignore leading layout only. Keep trailing column delimiters so a field
    named 'Sound' cannot be proved by a different field named 'Sound Volume'.
    Exact source-claim grounding and revision identity are checked separately.
    """
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    left, right = left.lstrip(), right.lstrip()
    return bool(left and right) and (left in right or right in left)

POLICY = "relationship-exploration-v1"
INSTRUCTIONS = """\
relationship_context是独立于确定规则池的资源正文反查，不是新增确定预期。候选一律先视为待查。
逐项或分组返回relationship_dispositions，不得因候选不在固定池而删除，也不能把0命中说成无影响。
effect/no_effect须引用本请求同版本、同hash且覆盖候选原文的确认声明；否则保留unresearched或明确规则/方法缺口。
effect还须关联实际关系与场景。场景按用户任务/情境→准备→触发→实际效果→中断/恢复的适用顺序设计，
在实际检查关系的steps填写relation_ids，并引用该关系的确认声明；只在场景顶层挂关系不算落实。
进入前、使用中变化、解除后的适用性需按来源分析，不机械穷举；没有恢复规则就留缺口，不补造。
完整关系集合不等于完整场景：独立评审须挑战来源范围、可达性、关系组合及时间顺序。
profile.usage_scenarios中的id须保留为usage_goals.id，保留原user_task；changes是有序的使用变化，不得把未查情境删除或当已确认恢复规则。
"""
GUIDE = [{"id": "stable-investigation", "candidate_ids": ["recalled candidate ID"],
          "status": "effect|no_effect|unresearched|gap_rule|gap_method|out_of_scope",
          "claim_ids": [], "relation_ids": [], "scenario_ids": [], "gap_ids": [],
          "reason": "source interpretation, missing reading or explicit scope decision"}]
FIELDS = {"id", "candidate_ids", "status", "claim_ids", "relation_ids", "scenario_ids", "gap_ids", "reason"}
STATUSES = {"effect", "no_effect", "unresearched", "gap_rule", "gap_method", "out_of_scope"}


def _refs(values, label):
    if (not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values)
            or len(set(values)) != len(values)):
        raise GenerationError(label + " requires unique string IDs")
    return set(values)


def validate_step_relations(response, *, required=False):
    """Locate each declared relation on actual compact steps, before expansion."""
    relations = {r["id"]: r for r in response.get("relations", [])}
    for scenario in response.get("scenarios", []):
        declared = _refs(scenario.get("relation_ids", []), "Scenario relation_ids")
        if declared - relations.keys():
            raise GenerationError("Scenario references an unknown relationship")
        located = set()
        for step in scenario.get("steps", []):
            if not isinstance(step, dict):
                raise GenerationError("Scenario steps must be objects")
            refs = _refs(step.get("relation_ids", []), "Step relation_ids")
            if refs - declared:
                raise GenerationError("Step relationship must be declared by its scenario")
            claims = _refs(step.get("claim_ids", scenario.get("claim_ids", [])), "Step claim_ids")
            for rid in refs:
                needed = _refs(relations[rid].get("claim_ids", []), "Relationship claim_ids")
                if not needed or not needed <= claims:
                    raise GenerationError("Relationship step must cite its actual rule claims")
            located.update(refs)
        if required and declared != located:
            raise GenerationError("Relationship is only named, not exercised by any scenario step")


def validate_dispositions(request, response):
    """Recalled text cannot bypass normal fixed-rule/version/evidence checks."""
    context = request.get("relationship_context")
    if context is None:
        if "relationship_dispositions" in response:
            raise GenerationError("Relationship dispositions require a bound exploration context")
        return None
    if context.get("status") != "candidates_recalled":
        raise GenerationError("Refresh stale relationship exploration before generation")
    candidates = {c["id"]: c for c in context["candidates"]}
    rows = response.get("relationship_dispositions")
    if not isinstance(rows, list):
        raise GenerationError("Recalled relationships need explicit dispositions")
    claims = {c["id"]: c for c in response["claims"]}
    relations = {r["id"]: r for r in response.get("relations", [])}
    scenarios = {s["id"]: s for s in response["scenarios"]}
    gaps = {g["id"]: g for g in response["gaps"]}
    sources = {s["source_id"]: s for s in request["sources"]}
    goals = {g["id"]: g for g in response.get("usage_goals", [])}
    for situation in context["profile"]["usage_scenarios"]:
        if situation["id"] not in goals or goals[situation["id"]].get("user_task") != situation["user_task"]:
            raise GenerationError("Original user situation was omitted or silently replaced")
    seen, row_ids = set(), set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != FIELDS
                or not isinstance(row["id"], str) or not row["id"].strip() or row["id"] in row_ids
                or not isinstance(row["status"], str) or row["status"] not in STATUSES
                or not isinstance(row["reason"], str) or not row["reason"].strip()):
            raise GenerationError("Invalid relationship disposition fields, ID, status or reason")
        row_ids.add(row["id"])
        ids = _refs(row["candidate_ids"], "candidate_ids")
        if not ids or ids - candidates.keys() or seen & ids:
            raise GenerationError("Unknown, duplicate or empty relationship candidate disposition")
        seen.update(ids)
        for field, known in (("claim_ids", claims), ("relation_ids", relations),
                             ("scenario_ids", scenarios), ("gap_ids", gaps)):
            if _refs(row[field], field) - known.keys():
                raise GenerationError("Relationship disposition references an unknown design object")
        status = row["status"]
        proofs = {}
        if status in {"effect", "no_effect"}:
            if not row["claim_ids"] or any(claims[c].get("semantic_status") != "confirmed" for c in row["claim_ids"]):
                raise GenerationError("Relationship conclusions need confirmed source claims")
            for cid in ids:
                candidate = candidates[cid]
                source = candidate["source"]
                current = sources.get(source["source_id"], {})
                proofs[cid] = {c for c in row["claim_ids"] if claims[c].get("source_id") == source["source_id"] and
                    _quote_overlap(candidate["quote"], claims[c].get("quote", ""))
                    }
                if any(current.get(k) != source.get(k) for k in ("version", "content_hash")) or not proofs[cid]:
                    raise GenerationError("Candidate conclusion is outside the supplied source revision or quote")
        if status == "effect":
            if not row["relation_ids"] or not row["scenario_ids"]:
                raise GenerationError("Effective relationship needs actual relations and scenarios")
            for rid in row["relation_ids"]:
                if not set(relations[rid].get("claim_ids", [])) & set(row["claim_ids"]) or not any(
                        rid in scenarios[s].get("relation_ids", []) for s in row["scenario_ids"]):
                    raise GenerationError("Candidate effect is not linked to its rule and scenario")
            for proof_ids in proofs.values():
                if not any(set(relations[rid].get("claim_ids", [])) & proof_ids and any(
                        rid in scenarios[s].get("relation_ids", []) for s in row["scenario_ids"])
                        for rid in row["relation_ids"]):
                    raise GenerationError("Grouped candidate has no individual relationship/scenario proof")
        elif status in {"gap_rule", "gap_method"}:
            if not row["gap_ids"] or any(gaps[g].get("status") != status for g in row["gap_ids"]):
                raise GenerationError("Relationship gap must reference a matching actual gap")
        elif status in {"unresearched", "out_of_scope"} and any(row[f] for f in ("claim_ids", "relation_ids", "scenario_ids", "gap_ids")):
            raise GenerationError("Unresearched/excluded candidates cannot claim verified design coverage")
        elif status == "no_effect" and any(row[f] for f in ("relation_ids", "scenario_ids", "gap_ids")):
            raise GenerationError("No-effect conclusion cannot also claim an effect or unresolved gap")
    if seen != candidates.keys():
        raise GenerationError("Recalled relationship candidates were silently omitted")
    record = {"policy": POLICY, "context": deepcopy(context), "dispositions": deepcopy(rows),
              "source_basis": [{k: deepcopy(s.get(k)) for k in ("source_id", "version", "content_hash")} for s in request["sources"]]}
    if "usage_journey_policy" in request:
        record["usage_journey_policy"] = request["usage_journey_policy"]
    return record


def refresh_relationship_coverage(model):
    """Report actual selected paths without dropping pending/deferred discovery."""
    if "relationship_coverage" not in model:
        return
    record = model["relationship_coverage"]
    paths = []
    behaviors = {b["id"]: b for b in model.get("behaviors", [])}
    for obligation in model.get("coverage_obligations", []):
        path = [{"behavior_id": bid, "step_index": behaviors[bid].get("compact_step_index", i),
                 "relation_ids": deepcopy(behaviors[bid].get("relation_ids", []))}
                for i, bid in enumerate(obligation.get("behavior_ids", [])) if bid in behaviors]
        if any(step["relation_ids"] for step in path):
            paths.append({"scenario_id": obligation["id"], "ordered_steps": path,
                "goal_ids": [g["id"] for g in model.get("usage_goals", []) if obligation["id"] in g["scenario_ids"]],
                "case_ids": [c["id"] for c in model.get("cases", []) if obligation["id"] in c.get("obligation_ids", [])]})
    record["paths"] = paths
    record["pending_candidate_ids"] = [cid for row in record["dispositions"]
        if row["status"] in {"unresearched", "gap_rule", "gap_method"} for cid in row["candidate_ids"]]
    record["deferred_scenario_ids"] = sorted({sid for row in record["dispositions"] for sid in row["scenario_ids"]}
        - {o["id"] for o in model.get("coverage_obligations", [])})
    record["semantic_verified"] = False
    record["complete"] = False


def model_relationship_gaps(model):
    """Pending discovery affects completeness, not every unrelated core case."""
    record = model.get("relationship_coverage")
    if record is None:
        return []
    if "usage_journey_policy" in record:
        from .usage_journeys import POLICY as JOURNEY_POLICY
        if record["usage_journey_policy"] != JOURNEY_POLICY or "usage_journeys" not in model:
            raise GenerationError("Stored original usage journey denominator was removed or changed")
    checked = deepcopy(model)
    refresh_relationship_coverage(checked)
    if checked["relationship_coverage"] != record:
        raise GenerationError("Relationship coverage differs from actual ordered behavior paths")
    from .relationship_exploration import fingerprint
    context = record["context"]
    if context["binding"]["target"] != model.get("target"):
        raise GenerationError("Relationship context target differs from the actual design")
    if context.get("fingerprint") != fingerprint({k: v for k, v in context.items() if k != "status"}):
        raise GenerationError("Relationship search context was altered")
    candidates = {c["id"]: c for c in context["candidates"]}
    claims = {c["id"]: c for c in model.get("source_claims", [])}
    sources = {s["source_id"]: s for s in record["source_basis"]}
    seen = set()
    for row in record["dispositions"]:
        ids = _refs(row["candidate_ids"], "Stored candidate_ids")
        if not ids or seen & ids or ids - candidates.keys() or row["status"] not in STATUSES:
            raise GenerationError("Stored relationship dispositions are incomplete or conflicting")
        seen.update(ids)
        if set(row["claim_ids"]) - claims.keys():
            raise GenerationError("Stored relationship conclusion lost its source claims")
        if row["status"] in {"effect", "no_effect"}:
            for cid in ids:
                candidate, supported = candidates[cid], False
                source = candidate["source"]
                if any(sources.get(source["source_id"], {}).get(k) != source.get(k) for k in ("version", "content_hash")):
                    raise GenerationError("Stored relationship source revision was lost")
                for claim_id in row["claim_ids"]:
                    claim = claims[claim_id]
                    supported |= (claim.get("semantic_status") == "confirmed" and claim.get("source_id") == source["source_id"]
                        and _quote_overlap(candidate["quote"], claim.get("quote", "")))
                if not supported:
                    raise GenerationError("Stored relationship conclusion has no matching confirmed evidence")
    if seen != candidates.keys():
        raise GenerationError("Stored relationship candidates were silently omitted")
    gaps = [{"code": "relationship_unresearched", "path": "relationship_coverage",
             "message": "资源反查候选仍待解释/核对，不代表产品没有关联。", "candidate_id": cid,
             "affected_case_ids": [], "affected_obligation_ids": []}
            for cid in record["pending_candidate_ids"]]
    scan = record["context"]["scan"]
    if scan["truncated"] or scan["rejected"] or scan["unmatched_resource_ids"]:
        gaps.append({"code": "relationship_search_boundary", "path": "relationship_coverage.context.scan",
            "message": "部分资源未命中，或存在拒绝/未扫描资料；搜索边界不能解释为无影响。",
            "affected_case_ids": [], "affected_obligation_ids": []})
    expected = {s["id"]: s["user_task"] for s in record["context"]["profile"]["usage_scenarios"]}
    actual = {g["id"]: g.get("user_task") for g in model.get("usage_goals", [])}
    if any(actual.get(gid) != task for gid, task in expected.items()):
        raise GenerationError("Stored original user situation was omitted or silently replaced")
    expected_goals = set(expected)
    for goal in model.get("usage_goals", []):
        if goal["id"] in expected_goals and goal["evidence_status"] != "confirmed":
            gaps.append({"code": "relationship_usage_unresolved", "path": "usage_goals", "goal_id": goal["id"],
                "message": "原用户情境仍未确认或明确排除，不能宣称已完整覆盖。",
                "affected_case_ids": [], "affected_obligation_ids": []})
    if record["deferred_scenario_ids"]:
        gaps.append({"code": "relationship_scenario_deferred", "path": "relationship_coverage.deferred_scenario_ids",
            "message": "关联场景尚未在当前范围生成，不能把已列关系当实际覆盖。",
            "affected_case_ids": [], "affected_obligation_ids": record["deferred_scenario_ids"]})
    for change in model.get("usage_coverage", {}).get("unresolved_journey_changes", []):
        gaps.append({"code": "usage_journey_unresolved", "path": "usage_journeys",
            "journey_id": change["journey_id"], "change_index": change["change_index"],
            "status": change["status"], "message": "原使用路径的该项变化仍未生成，登记缺口或局部交付不构成任务完成。",
            "affected_case_ids": [], "affected_obligation_ids": []})
    return gaps
