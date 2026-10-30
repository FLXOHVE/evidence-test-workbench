"""Source-first branch accounting, not automatic natural-language inference.

The independent coverage catalog owns the branch denominator. Full *already
read* bodies are analysis-only: they never enlarge a fixed rule pool. Checks
locate each branch's trigger/state/result/recovery in real compact steps;
semantic equivalence and the completeness of the inventory remain human work.
"""
from copy import deepcopy
import hashlib
import json
import re
import unicodedata

from .module_generation import GenerationError


POLICY = "source-branches-v1"
INSTRUCTIONS = """\
analysis_only_source_context保留已读来源的完整正文及读取边界，不是新增确定规则。
独立coverage_catalog.source_branch_inventory先从这些正文推导同一结果的不同触发、状态变化与恢复分支，不能只复用profile或已选规则清单。
source_branch_dispositions逐分支保留目录ID。designed须把trigger/result及目录列出的每个state/recovery组件定位到实际紧凑步骤；通用消费步骤不代表不同触发已覆盖。
固定池外分支只能列精确gap_rule待整理，不可从分析正文直接生成确定预期。未研究分支须有其专属缺口，不可全部并入泛背景。
独立目录未提供时仍可生成无关core，但来源分支分析明确未完成，不得称全范围完成。文字引用与结构校验不证明解释正确或分支目录完整。
"""
GUIDE = [{"branch_id": "independent branch ID", "status": "designed|no_effect|unresearched|gap_rule|gap_method|out_of_scope",
          "claim_ids": [], "scenario_ids": [], "gap_ids": [], "checks": [
              {"component": "trigger|result|state:0|recovery:0", "scenario_id": "actual scenario ID",
               "step_index": 0, "field": "action|expected", "quote": "verbatim compact step substring"}],
          "reason": "specific source interpretation or missing work"}]
_SOURCE_FIELDS = ("source_id", "source_type", "version", "content_hash", "url", "raw_ref", "fetched_at",
                  "source_updated_at", "read_scope", "reading_boundary", "applicability", "status",
                  "comments_complete", "applicability_scope", "evidence_tier", "draft_only", "draft_scope",
                  "archive_provenance")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _normal_action(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value).casefold())


def _refs(value, label):
    if not isinstance(value, list) or any(not _text(v) for v in value) or len(value) != len(set(value)):
        raise GenerationError(label + " requires unique string IDs")
    return set(value)


def source_context(source, *, origin):
    """Keep the whole sealed body, including non-matching neighbouring branches."""
    body = source.get("body")
    if not isinstance(body, str) or not body.strip():
        raise GenerationError("Source branch context requires an actually read body")
    identity = [source.get(k) for k in ("source_id", "version", "content_hash")]
    if not _text(identity[0]) or not _text(identity[2]):
        raise GenerationError("Source branch context requires a bound source identity")
    return {"id": "SC-" + fingerprint(identity)[:24],
            "source": {k: deepcopy(source.get(k)) for k in _SOURCE_FIELDS},
            "body": body, "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(), "origin": origin}


def build_context(run):
    rows = {}
    for source in run.get("baseline", {}).get("sources", []):
        row = source_context(source, origin="pinned_baseline")
        rows[row["id"]] = row
    # Only newly recorded recall has these integrity-bound bodies. Historical
    # line-only records are not silently augmented from arbitrary disk paths.
    recalled = run.get("relationship_exploration") or {}
    if recalled.get("source_contexts"):
        from .relationship_exploration import context_for_run
        if context_for_run(run, recalled.get("profile", {}).get("module"))["status"] != "candidates_recalled":
            raise GenerationError("Full recalled source bodies require a current integrity-bound exploration")
    for row in recalled.get("source_contexts", []):
        if row["id"] not in rows:
            rows[row["id"]] = deepcopy(row)
    context = {"policy": POLICY, "target": deepcopy(run["target"]), "user_request": deepcopy(run.get("query", "")),
        "sources": sorted(rows.values(), key=lambda row: row["id"]),
        "latest_verified": False, "semantic_verified": False}
    context["fingerprint"] = fingerprint(context)
    validate_context(context)
    return context


def validate_context(context):
    if (not isinstance(context, dict) or context.get("policy") != POLICY
            or context.get("fingerprint") != fingerprint({k: v for k, v in context.items() if k != "fingerprint"})
            or context.get("latest_verified") is not False or context.get("semantic_verified") is not False
            or not isinstance(context.get("sources"), list) or not context["sources"]):
        raise GenerationError("Source branch analysis context is missing or changed")
    ids = set()
    for row in context["sources"]:
        if not isinstance(row, dict) or row.get("id") in ids:
            raise GenerationError("Duplicate source branch context")
        rebuilt = source_context({**row.get("source", {}), "body": row.get("body")}, origin=row.get("origin"))
        if row != rebuilt or row.get("origin") not in {"pinned_baseline", "recalled_source"}:
            raise GenerationError("Source branch body/identity binding was changed")
        ids.add(row["id"])
    return {row["id"]: row for row in context["sources"]}


def validate_inventory(inventory, context, *, produced_by="requirement-model-adapter", catalog=None):
    sources = validate_context(context)
    if (not isinstance(inventory, dict)
            or set(inventory) != {"policy", "context_fingerprint", "reviewer_id", "source_reviews", "branches"}
            or inventory["policy"] != POLICY or inventory["context_fingerprint"] != context["fingerprint"]
            or not _text(inventory["reviewer_id"]) or inventory["reviewer_id"] == produced_by
            or (catalog is not None and inventory["reviewer_id"] != catalog.get("reviewer_id"))):
        raise GenerationError("Source branch inventory needs an independent, current source binding")
    if not isinstance(inventory["branches"], list) or not isinstance(inventory["source_reviews"], list):
        raise GenerationError("Source branch inventory requires branch/source arrays")
    branches = {}
    for row in inventory["branches"]:
        if (not isinstance(row, dict) or set(row) != {"id", "result", "trigger", "state_changes", "recovery", "source_refs", "rule_ids"}
                or not all(_text(row[k]) for k in ("id", "result", "trigger")) or row["id"] in branches):
            raise GenerationError("Invalid source branch ID or components")
        for field in ("state_changes", "recovery"):
            if not isinstance(row[field], list) or any(not _text(v) for v in row[field]):
                raise GenerationError("Source branch components must be ordered text arrays")
        _refs(row["rule_ids"], "Source branch rule_ids")
        if not isinstance(row["source_refs"], list) or not row["source_refs"]:
            raise GenerationError("Each source branch needs exact source evidence")
        for ref in row["source_refs"]:
            if (not isinstance(ref, dict) or set(ref) != {"context_id", "quote"}
                    or ref["context_id"] not in sources or not _text(ref["quote"])
                    or ref["quote"] not in sources[ref["context_id"]]["body"]):
                raise GenerationError("Source branch quote is not in the bound full body")
        branches[row["id"]] = row
    seen = set()
    for row in inventory["source_reviews"]:
        if (not isinstance(row, dict) or set(row) != {"context_id", "status", "branch_ids", "reason"}
                or row["context_id"] not in sources or row["context_id"] in seen
                or row["status"] not in {"reviewed", "unresearched", "out_of_scope"} or not _text(row["reason"])):
            raise GenerationError("Source branch review must account for each source separately")
        seen.add(row["context_id"])
        refs = _refs(row["branch_ids"], "Source review branch_ids")
        expected = {bid for bid, branch in branches.items()
                    if any(ref["context_id"] == row["context_id"] for ref in branch["source_refs"])}
        if refs != expected or (refs and row["status"] != "reviewed"):
            raise GenerationError("Source review branch denominator differs from its actual evidence")
    if seen != sources.keys():
        raise GenerationError("A full analysis source was silently omitted from independent review")
    return branches


def _components(branch):
    return {"trigger", "result"} | {"state:" + str(i) for i in range(len(branch["state_changes"]))} | {
        "recovery:" + str(i) for i in range(len(branch["recovery"]))}


def _ordered_components(branch):
    return ["trigger"] + ["state:" + str(i) for i in range(len(branch["state_changes"]))] + ["result"] + [
        "recovery:" + str(i) for i in range(len(branch["recovery"]))]


def _scenario_layout(scenarios):
    layout = {}
    for sid, scene in scenarios.items():
        continuation = scene.get("continuation")
        parent = None
        if continuation is not None:
            if (not isinstance(continuation, dict) or continuation.get("scenario_id") not in scenarios
                    or not _text(continuation.get("handoff")) or not _text(continuation.get("predecessor_expected"))):
                raise GenerationError("Source branch continuation needs an explicit existing predecessor and handoff")
            parent = continuation["scenario_id"]
        layout[sid] = {"parent": parent, "steps": len(scene["steps"])}
    return layout


def _check_order(branch, checks, *, state_history=False, layout=None):
    # Cross-case handoff is already supported by usage journeys, but this
    # narrow branch witness protocol does not claim to verify that handoff.
    # Require one continuous scenario until explicit handoff binding is added.
    if len({check["scenario_id"] for check in checks}) > 1:
        if not state_history or not layout:
            raise GenerationError("Source branch checks require one continuous scenario, not unbound cross-case fragments")
        chains = []
        for sid in {c["scenario_id"] for c in checks}:
            chain, current = [], sid
            while current is not None:
                if current not in layout or current in chain:
                    raise GenerationError("Source branch continuation is missing or cyclic")
                chain.append(current)
                current = layout[current]["parent"]
            chains.append(list(reversed(chain)))
        chain = max(chains, key=len)
        if not {c["scenario_id"] for c in checks} <= set(chain):
            raise GenerationError("Source branch checks are unbound cross-case fragments")
        offsets, size = {}, 0
        for sid in chain:
            offsets[sid] = size
            size += layout[sid]["steps"]
        checks = [{**c, "scenario_id": "bound-history", "step_index": offsets[c["scenario_id"]] + c["step_index"]} for c in checks]
    by_component = {check["component"]: check for check in checks}
    if state_history:
        # A source-only reader describes history without internal rule IDs or
        # an assumption that every state change happens after the event under
        # test. A configuration write can precede sleep/power-off. Keep the
        # declared state order and event/result/recovery causality intact.
        trigger = by_component["trigger"]["step_index"]
        result = by_component["result"]["step_index"]
        states = [by_component["state:" + str(i)]["step_index"] for i in range(len(branch["state_changes"]))]
        recovery = [by_component["recovery:" + str(i)]["step_index"] for i in range(len(branch["recovery"]))]
        if (trigger > result or states != sorted(states)
                or recovery != sorted(recovery) or any(i < trigger for i in recovery)):
            raise GenerationError("Source branch state/result/recovery precedes its triggering history")
        return
    last_by_scenario = {}
    for component in _ordered_components(branch):
        check = by_component[component]
        previous = last_by_scenario.get(check["scenario_id"], -1)
        if check["step_index"] < previous:
            raise GenerationError("Source branch state/result/recovery precedes its triggering history")
        last_by_scenario[check["scenario_id"]] = check["step_index"]


def validate_response(request, response):
    if "source_branch_policy" not in request:
        if "source_branch_dispositions" in response:
            raise GenerationError("Source branch dispositions require an explicit policy")
        return None
    if request["source_branch_policy"] != POLICY:
        raise GenerationError("Unknown source branch policy")
    context = request["analysis_only_source_context"]
    validate_context(context)
    catalog = request.get("coverage_catalog") or {}
    inventory = catalog.get("source_branch_inventory")
    rows = response.get("source_branch_dispositions", [])
    if not isinstance(rows, list):
        raise GenerationError("Source branch dispositions must be an array")
    record = {"policy": POLICY, "context": deepcopy(context), "inventory": deepcopy(inventory), "trigger_actions": {},
              "dispositions": deepcopy(rows), "fixed_rule_ids": None,
              "source_basis": [{k: deepcopy(s.get(k)) for k in ("source_id", "version", "content_hash")} for s in request["sources"]]}
    audit_request = (catalog.get("source_audit") or {}).get("request", {})
    resolutions = (catalog.get("source_audit") or {}).get("source_resolutions", {})
    superseded = {r["branch_id"] for r in resolutions.get("branch_resolutions", [])}
    if superseded:
        record["definition_resolutions"] = deepcopy(resolutions)
    if audit_request.get("source_branch_policy") == POLICY:
        record["source_only_bindings"] = True
    if request.get("requirement_basis"):
        record["fixed_rule_ids"] = deepcopy(request["requirement_scope"]["included_rule_ids"])
    if inventory is None:
        if rows:
            raise GenerationError("Branches cannot be self-inventoried by the design response")
        return record
    branches = validate_inventory(inventory, context, catalog=catalog)
    claims = {c["id"]: c for c in response["claims"]}
    scenarios = {s["id"]: s for s in response["scenarios"]}
    if record.get("source_only_bindings"):
        record["scenario_layout"] = _scenario_layout(scenarios)
    gaps = {g["id"]: g for g in response["gaps"]}
    seen, gap_owners, triggers = set(), {}, {}
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"branch_id", "status", "claim_ids", "scenario_ids", "gap_ids", "checks", "reason"}
                or row["branch_id"] not in branches or row["branch_id"] in seen or not _text(row["reason"])
                or row["status"] not in {"designed", "no_effect", "unresearched", "gap_rule", "gap_method", "out_of_scope", "superseded"}):
            raise GenerationError("Source branches require individual valid dispositions")
        seen.add(row["branch_id"])
        branch = branches[row["branch_id"]]
        for field, known in (("claim_ids", claims), ("scenario_ids", scenarios), ("gap_ids", gaps)):
            if _refs(row[field], field) - known.keys():
                raise GenerationError("Source branch references an unknown design object")
        if not isinstance(row["checks"], list):
            raise GenerationError("Source branch checks must be an array")
        status = row["status"]
        if status == "superseded" and (row["branch_id"] not in superseded or any(
                row[f] for f in ("claim_ids", "scenario_ids", "gap_ids", "checks"))):
            raise GenerationError("Only independently mapped historical branches can be superseded, never counted as designed")
        if status in {"designed", "no_effect"}:
            _validate_claims(branch, row, claims, context, record)
        if status == "designed":
            if row["gap_ids"] or not row["scenario_ids"]:
                raise GenerationError("Designed source branch needs actual scenarios without unresolved gaps")
            components, checked_scenarios = set(), set()
            for check in row["checks"]:
                if (not isinstance(check, dict) or set(check) != {"component", "scenario_id", "step_index", "field", "quote"}
                        or check["component"] not in _components(branch) or check["component"] in components
                        or check["scenario_id"] not in row["scenario_ids"]
                        or type(check["step_index"]) is not int or check["step_index"] < 0
                        or check["field"] not in {"action", "expected"} or not _text(check["quote"])):
                    raise GenerationError("Source branch check has an invalid component or actual step")
                steps = scenarios[check["scenario_id"]].get("steps", [])
                if check["step_index"] >= len(steps) or check["quote"] not in steps[check["step_index"]].get(check["field"], ""):
                    raise GenerationError("Source branch witness is not in its actual compact step")
                step_claims = set(steps[check["step_index"]].get("claim_ids", scenarios[check["scenario_id"]].get("claim_ids", [])))
                if not step_claims & set(row["claim_ids"]):
                    raise GenerationError("Source branch step does not cite its actual rule claims")
                if check["component"] == "trigger":
                    if check["field"] != "action":
                        raise GenerationError("Branch trigger needs an action witness, not a generic result")
                    actual_action = steps[check["step_index"]]["action"]
                    record["trigger_actions"][row["branch_id"]] = actual_action
                    key = (branch["result"], _normal_action(actual_action))
                    prior = triggers.get(key)
                    if prior is not None and prior != branch["trigger"]:
                        raise GenerationError("Different triggers cannot reuse the same generic consumer witness")
                    triggers[key] = branch["trigger"]
                elif check["component"] == "result" and check["field"] != "expected":
                    raise GenerationError("Branch result needs an observable expected witness")
                components.add(check["component"])
                checked_scenarios.add(check["scenario_id"])
            if components != _components(branch) or checked_scenarios != set(row["scenario_ids"]):
                raise GenerationError("Source branch trigger/state/result/recovery was only partly located")
            _check_order(branch, row["checks"], state_history=record.get("source_only_bindings", False), layout=record.get("scenario_layout"))
        elif row["checks"] or row["scenario_ids"]:
            raise GenerationError("Unresolved or excluded branches cannot claim designed step coverage")
        if status in {"unresearched", "gap_rule", "gap_method"}:
            if not row["gap_ids"]:
                raise GenerationError("Unresolved source branch needs a precise, branch-specific gap")
            for gid in row["gap_ids"]:
                if gid in gap_owners and gap_owners[gid] != row["branch_id"]:
                    raise GenerationError("Different source branches cannot share a generic unresolved gap")
                gap_owners[gid] = row["branch_id"]
                wanted = "gap_rule" if status == "unresearched" else status
                if gaps[gid].get("status") != wanted:
                    raise GenerationError("Source branch gap classification differs from the actual gap")
        elif row["gap_ids"]:
            raise GenerationError("Settled/excluded source branch cannot also claim unresolved gaps")
    if seen != branches.keys():
        raise GenerationError("Independent source branch was omitted even if absent from profile/selected rules")
    return record


def _validate_claims(branch, row, claims, context, record):
    if not row["claim_ids"] or any(claims[c].get("semantic_status") != "confirmed" for c in row["claim_ids"]):
        raise GenerationError("Settled source branches require confirmed source claims")
    if record["fixed_rule_ids"] is not None:
        if ((not branch["rule_ids"] and not record.get("source_only_bindings"))
                or set(branch["rule_ids"]) - set(record["fixed_rule_ids"])):
            raise GenerationError("Analysis-only branch outside the fixed pool must remain a precise rule gap")
        bound = {ref.get("id") for cid in row["claim_ids"] for ref in claims[cid].get("rule_refs", [])}
        if not set(branch["rule_ids"]) <= bound:
            raise GenerationError("Source branch claims do not bind its actual fixed rules")
    sources = {s["id"]: s for s in context["sources"]}
    basis = {s["source_id"]: s for s in record["source_basis"]}
    for ref in branch["source_refs"]:
        source = sources[ref["context_id"]]["source"]
        if any(basis.get(source["source_id"], {}).get(k) != source.get(k) for k in ("version", "content_hash")):
            raise GenerationError("Recalled branch is not in the current source revision")
        if not any(claims[c].get("source_id") == source["source_id"] and _text(claims[c].get("quote"))
                   and (ref["quote"] in claims[c]["quote"] or
                        (record.get("source_only_bindings") and claims[c]["quote"] in ref["quote"])) for c in row["claim_ids"]):
            raise GenerationError("Source branch conclusion lacks its individual quoted evidence")
        if record.get("source_only_bindings") and record["fixed_rule_ids"] is not None:
            matched = [claims[c] for c in row["claim_ids"] if claims[c].get("source_id") == source["source_id"]
                       and _text(claims[c].get("quote")) and
                       (ref["quote"] in claims[c]["quote"] or claims[c]["quote"] in ref["quote"])]
            if not any(c.get("rule_refs") and {r.get("id") for r in c["rule_refs"]} <= set(record["fixed_rule_ids"]) for c in matched):
                raise GenerationError("Analysis-only branch outside the fixed pool must remain a precise rule gap")


def refresh_source_branch_coverage(model):
    record = model.get("source_branch_coverage")
    if record is None:
        return
    selected_case_ids = {c["id"] for c in model.get("cases", [])}
    record["case_bindings"] = [b for b in record.get("case_bindings", []) if b["case_id"] in selected_case_ids]
    paths = []
    for row in record["dispositions"]:
        cases = [c["id"] for c in model.get("cases", []) if set(c.get("obligation_ids", [])) & set(row["scenario_ids"])]
        paths.append({"branch_id": row["branch_id"], "status": row["status"], "case_ids": sorted(cases),
                      "scenario_ids": deepcopy(row["scenario_ids"]), "gap_ids": deepcopy(row["gap_ids"])})
    record["paths"] = paths
    record["pending_branch_ids"] = [row["branch_id"] for row in paths
        if row["status"] in {"unresearched", "gap_rule", "gap_method"} or (row["status"] == "designed" and not row["case_ids"])]
    record["semantic_verified"] = False
    record["complete"] = False


def model_source_branch_gaps(model):
    record = model.get("source_branch_coverage")
    if record is None:
        return []
    if record.get("policy") != POLICY or record["context"]["target"] != model.get("target"):
        raise GenerationError("Stored source branch target/policy changed")
    validate_context(record["context"])
    expected_source_only = model.get("independent_source_inventory", {}).get("request", {}).get("source_branch_policy") == POLICY
    resolutions = model.get("independent_source_inventory", {}).get("source_resolutions", {})
    superseded = {r["branch_id"] for r in resolutions.get("branch_resolutions", [])}
    if (record.get("definition_resolutions") or {}) != (resolutions if superseded else {}):
        raise GenerationError("Stored source branch definition resolutions changed")
    if bool(record.get("source_only_bindings")) != expected_source_only:
        raise GenerationError("Source branch mapping policy differs from its frozen independent request")
    checked = deepcopy(model)
    refresh_source_branch_coverage(checked)
    if checked["source_branch_coverage"] != record:
        raise GenerationError("Stored source branch paths differ from actual generated cases")
    def gap(code, message, **extra):
        return {"code": code, "path": "source_branch_coverage", "message": message,
                "affected_case_ids": [], "affected_obligation_ids": [], **extra}
    inventory = record["inventory"]
    if inventory is None:
        if record["dispositions"]:
            raise GenerationError("Stored source branches lost their independent denominator")
        return [gap("source_branch_inventory_missing", "尚无从完整已读来源独立推导的触发/状态/恢复分支目录；局部草稿不代表任务完整。")]
    branches = validate_inventory(inventory, record["context"], produced_by=model.get("produced_by"))
    if (len(record["dispositions"]) != len(branches)
            or {r["branch_id"] for r in record["dispositions"]} != branches.keys()):
        raise GenerationError("Stored source branch denominator changed")
    claims = {c["id"]: c for c in model.get("source_claims", [])}
    obligations = {o["id"]: o for o in model.get("coverage_obligations", [])}
    behaviors = {b["id"]: b for b in model.get("behaviors", [])}
    cases = {c["id"]: c for c in model.get("cases", [])}
    if record.get("source_only_bindings"):
        from .case_decomposition import validate_continuations
        validate_continuations(list(cases.values()))
        for sid, layout in record["scenario_layout"].items():
            selected = [c for c in cases.values() if sid in c.get("obligation_ids", [])]
            if not selected:
                continue
            indices = [behaviors[b].get("compact_step_index", -1) for b in obligations[sid]["behavior_ids"] if b in behaviors]
            if max(indices, default=-1) + 1 != layout["steps"]:
                raise GenerationError("Stored branch continuation layout differs from the actual steps")
            for case in selected:
                if case.get("generation", {}).get("continuation", {}).get("scenario_id") != layout["parent"]:
                    raise GenerationError("Stored branch continuation differs from the actual predecessor")
    bindings = {b["case_id"]: b for b in record.get("case_bindings", [])}
    if len(bindings) != len(record.get("case_bindings", [])) or bindings.keys() != cases.keys():
        raise GenerationError("Source branch actual case render bindings were omitted or duplicated")
    trigger_witnesses = {}
    unresolved_gap_owners = {}
    for row in record["dispositions"]:
        if row["status"] not in {"designed", "no_effect", "unresearched", "gap_rule", "gap_method", "out_of_scope", "superseded"}:
            raise GenerationError("Stored branch disposition has an unknown status")
        branch = branches[row["branch_id"]]
        if row["status"] == "superseded" and (row["branch_id"] not in superseded or any(
                row[f] for f in ("claim_ids", "scenario_ids", "gap_ids", "checks"))):
            raise GenerationError("Stored superseded branch lost its independent mapping or claimed designed coverage")
        if row["status"] in {"unresearched", "gap_rule", "gap_method"}:
            if not row["gap_ids"] or row["checks"] or row["scenario_ids"]:
                raise GenerationError("Stored unresolved source branch lost its precise gap")
            for gid in row["gap_ids"]:
                prior = unresolved_gap_owners.get(gid)
                if prior is not None and prior != row["branch_id"]:
                    raise GenerationError("Stored source branches merged into a generic gap")
                unresolved_gap_owners[gid] = row["branch_id"]
                # Absent coupling obligations stay pending in a core projection.
                if gid in obligations and obligations[gid].get("status") != ("gap_rule" if row["status"] == "unresearched" else row["status"]):
                    raise GenerationError("Stored source branch gap no longer matches its classification")
        if row["status"] not in {"designed", "no_effect"}:
            continue
        if set(row["claim_ids"]) - claims.keys():
            raise GenerationError("Stored branch conclusion lost its confirmed evidence")
        _validate_claims(branch, row, claims, record["context"], record)
        if row["status"] == "designed":
            if len(row["checks"]) != len(_components(branch)) or {c["component"] for c in row["checks"]} != _components(branch):
                raise GenerationError("Stored designed source branch lost a path component")
            _check_order(branch, row["checks"], state_history=record.get("source_only_bindings", False), layout=record.get("scenario_layout"))
        for check in row["checks"]:
            if check["component"] == "trigger":
                actual_action = record["trigger_actions"][row["branch_id"]]
                key = (branch["result"], _normal_action(actual_action))
                prior = trigger_witnesses.get(key)
                if prior is not None and prior != branch["trigger"]:
                    raise GenerationError("Stored different triggers reuse the same consumer witness")
                trigger_witnesses[key] = branch["trigger"]
            obligation = obligations.get(check["scenario_id"])
            if obligation is None:  # deferred coupling or an explicit local projection
                continue
            found = [behaviors[bid] for bid in obligation["behavior_ids"] if bid in behaviors
                     and behaviors[bid].get("compact_step_index") == check["step_index"]]
            texts = [b.get("trigger", "") if check["field"] == "action" else "\n".join(b.get("outcomes", [])) for b in found]
            if not any(check["quote"] in text for text in texts):
                raise GenerationError("Stored branch witness is no longer in the actual behavior path")
            if check["component"] == "trigger" and actual_action not in texts:
                raise GenerationError("Stored source branch trigger action differs from the actual path")
            from .module_generation import _render
            for case in cases.values():
                if check["scenario_id"] not in case.get("obligation_ids", []):
                    continue
                binding = bindings[case["id"]]
                if binding.get("obligation_id") != check["scenario_id"]:
                    raise GenerationError("Branch actual case binding differs from its scenario")
                matched = False
                for behavior in found:
                    if behavior["id"] not in binding["path"]:
                        continue
                    index = binding["path"].index(behavior["id"])
                    if index >= len(case.get("steps", [])):
                        continue
                    template = behavior.get("trigger", "") if check["field"] == "action" else "\n".join(behavior.get("outcomes", []))
                    rendered = _render(template, binding.get("bindings", {}))
                    matched |= case["steps"][index].get(check["field"]) == rendered
                if not matched:
                    raise GenerationError("Source branch actual case step differs from its rendered behavior witness")
    gaps = [gap("source_branch_unresolved", "独立来源分支尚未落实为当前范围实际用例，不能被泛背景或同结果其他触发替代。", branch_id=bid)
            for bid in record["pending_branch_ids"]]
    gaps.extend(gap("source_branch_source_unread", "完整已读正文尚未完成独立分支分析，不能解释为没有分支。", context_id=r["context_id"])
                for r in inventory["source_reviews"] if r["status"] == "unresearched")
    return gaps


def catalog_source_branch_gaps(model, catalog):
    """A later independent denominator cannot silently replace the applied one.

    Attaching/changing a catalog does not rewrite a frozen design. New branches
    therefore remain explicit task-level work until normal generation applies
    that exact inventory. Unrelated local draft cases remain exportable.
    """
    if not isinstance(catalog, dict) or "source_branch_inventory" not in catalog:
        return []
    inventory = catalog["source_branch_inventory"]
    applied = model.get("source_branch_coverage", {}).get("inventory")
    if isinstance(inventory, dict) and applied == inventory:
        return []
    branch_ids = [b.get("id") for b in inventory.get("branches", []) if isinstance(b, dict) and _text(b.get("id"))] if isinstance(inventory, dict) else []
    return [{"code": "source_branch_inventory_unapplied", "path": "coverage_catalog.source_branch_inventory",
             "message": "独立来源分支目录尚未应用到当前设计；后补或变更目录不能让旧分母自证完整。",
             "branch_ids": branch_ids, "affected_case_ids": [], "affected_obligation_ids": []}]
