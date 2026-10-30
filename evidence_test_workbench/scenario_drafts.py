"""Preserve known scenario chains without promoting missing methods to cases."""
from copy import deepcopy

RULE_EVIDENCE_POLICY = "confirmed-method-gap-design-only-v1"


def scenario_draft_obligations(model):
    rows = list(model.get("coverage_obligations", []))
    if model.get("design_rule_evidence_policy") == RULE_EVIDENCE_POLICY:
        rows.extend(model.get("deferred_scenario_designs", []))
    # A controlled projection keeps pending designs outside selected case
    # obligations. Do not mistake retained design evidence for case evidence,
    # or allow a normal model to gain this exception from an arbitrary field.
    if model.get("delivery_status") == "draft_unapproved":
        rows.extend(model.get("unresolved_coverage", []))
    return rows


def design_only_claim_ids(model):
    """Claims used solely in unresolved paths, never executable consumers."""
    pending = scenario_draft_claim_ids(model)
    executable = {cid for field in ("behaviors", "dependency_relations", "cases")
                  for item in model.get(field, [])
                  for name in ("claim_ids", "exact_text_claim_ids") for cid in item.get(name, [])}
    executable.update(cid for goal in model.get("usage_goals", [])
                      if goal.get("evidence_status") == "confirmed" for cid in goal.get("claim_ids", []))
    return pending - executable


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def validate_scenario_drafts(model):
    """Validate design-only paths. They never satisfy executable coverage.

    Confirmed expected results need confirmed claims. Unknown product results
    must be null, with a precise rule question; unknown methods are separate.
    Like the case compiler, this checks provenance/structure, not entailment.
    """
    claims = {c["id"]: c for c in model.get("source_claims", [])}
    seen = set()
    for obligation in scenario_draft_obligations(model):
        if "scenario_drafts" not in obligation:
            continue
        oid = obligation["id"]
        if obligation.get("status") not in {"gap_method", "gap_rule"}:
            raise ValueError(f"{oid}: scenario_drafts belong only to unresolved obligations")
        drafts = obligation["scenario_drafts"]
        if not isinstance(drafts, list) or not drafts:
            raise ValueError(f"{oid}: scenario_drafts must be a nonempty array")
        for draft in drafts:
            if not isinstance(draft, dict) or set(draft) != {"id", "title", "preconditions", "steps"}:
                raise ValueError(f"{oid}: invalid scenario draft fields")
            if not _text(draft["id"]) or draft["id"] in seen or not _text(draft["title"]):
                raise ValueError(f"{oid}: draft IDs must be unique and titles nonempty")
            seen.add(draft["id"])
            preconditions = draft["preconditions"]
            if not isinstance(preconditions, list) or not preconditions or any(
                not isinstance(p, dict) or set(p) != {"state", "setup"}
                or not _text(p["state"]) or not _text(p["setup"]) for p in preconditions
            ):
                raise ValueError(f"{oid}: draft needs starting state and setup")
            if not isinstance(draft["steps"], list) or not draft["steps"]:
                raise ValueError(f"{oid}: draft needs an ordered scenario chain")
            step_ids, has_gap = set(), False
            for step in draft["steps"]:
                if not isinstance(step, dict) or set(step) != {
                    "id", "action", "expected", "claim_ids", "method_gap", "rule_gap"
                }:
                    raise ValueError(f"{oid}: invalid draft step fields")
                if not _text(step["id"]) or step["id"] in step_ids or not _text(step["action"]):
                    raise ValueError(f"{oid}: draft step needs a unique ID and action")
                step_ids.add(step["id"])
                for field in ("method_gap", "rule_gap"):
                    if step[field] is not None and not _text(step[field]):
                        raise ValueError(f"{oid}: {field} must be null or a precise missing item")
                refs = step["claim_ids"]
                if not isinstance(refs, list) or any(
                    not isinstance(cid, str) or cid not in claims
                    or claims[cid].get("semantic_status") != "confirmed" for cid in refs
                ):
                    raise ValueError(f"{oid}: draft claims must be confirmed model claims")
                if step["rule_gap"] is not None:
                    if obligation["status"] != "gap_rule" or step["expected"] is not None:
                        raise ValueError(f"{oid}: unknown rule cannot contain a definite expected result")
                elif not _text(step["expected"]) or not refs:
                    raise ValueError(f"{oid}: definite draft result needs text and confirmed claims")
                has_gap |= step["method_gap"] is not None or step["rule_gap"] is not None
            if not has_gap:
                raise ValueError(f"{oid}: complete scenarios must use the normal case compiler")


def scenario_draft_claim_ids(model):
    return {cid for o in scenario_draft_obligations(model)
            for draft in o.get("scenario_drafts", []) for step in draft["steps"] for cid in step["claim_ids"]}


def _cell(value):
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def render_design_details(payload):
    """One readable delivery: existing cases AND complete pending designs.

    This is an unapproved review view, not a case projection or an execution
    workbook. In particular pending rows cannot enter case counts/adoption.
    """
    model = deepcopy(payload["design"])
    validate_scenario_drafts(model)
    lines = ["# 模块用例与完整场景设计（未审批）", "",
        f"任务：{payload['run_id']}；修订：{payload['run_revision']}", "",
        f"目标：{model.get('target', {})}", "",
        "这是设计评审稿，不是执行结果或覆盖完整证明。下列待补设计不计作已覆盖、可执行用例或冒烟。",
        "已生成用例也需结合原独立评审及各条备注，不能由本视图推定可执行或已通过复核。", "",
        "## 已生成用例", ""]
    navigation_library, preparation_library = [], []
    for case in model.get("cases", []):
        lines.extend([f"### {case['id']}｜{case['title']}", "",
            f"优先级：{case['priority']}（{case['priority_reason']}）", ""])
        for p in case["preconditions"]:
            if case.get("generation", {}).get("execution_authoring_policy"):
                if p not in preparation_library:
                    preparation_library.append(p)
                label = "P" + str(preparation_library.index(p) + 1)
                lines.extend([f"准备 {label}：{p['state']}（建立方法见文末公共准备）", ""])
            else:
                lines.extend([f"准备状态：{p['state']}", "", f"准备方法：{p['setup']}", ""])
        lines.extend(["| 步骤 | 操作 | 预期 |", "|---:|---|---|"])
        groups = {g["step_indices"][0]: g for g in case.get("generation", {}).get("navigation_groups", [])}
        index = 0
        while index < len(case["steps"]):
            group = groups.get(index)
            if group is not None:
                from .execution_contract import validate_case
                validate_case(case)
                actual = [case["steps"][i] for i in group["step_indices"]]
                entry = {"name": group["name"], "steps": actual}
                if entry not in navigation_library:
                    navigation_library.append(entry)
                label = "M" + str(navigation_library.index(entry) + 1)
                lines.append(f"| {index + 1}—{group['step_indices'][-1] + 1} | 公共操作 {label}：{_cell(group['name'])}（见文末全文） | {_cell(actual[-1]['expected'])} |")
                index = group["step_indices"][-1] + 1
            else:
                step = case["steps"][index]
                lines.append(f"| {index + 1} | {_cell(step['action'])} | {_cell(step['expected'])} |")
                index += 1
        if case.get("review_notes"):
            lines.extend(["", "<details><summary>依据与设计说明（不作额外验收要求）</summary>", ""])
            lines.extend("- " + note for note in case["review_notes"])
            lines.extend(["", "</details>"])
        lines.extend(["", f"边界/待补：{case.get('notes', '无额外说明')}", ""])
    if model.get("suite_cleanup"):
        cleanup = model["suite_cleanup"]
        lines.extend(["## 模块统一收尾与基线", "", f"状态：{cleanup['status']}；{cleanup['reason']}", ""])
        if cleanup.get("capture"):
            lines.extend(["原状态记录：" + cleanup["capture"]["state"], "", "记录方法：" + cleanup["capture"]["setup"], ""])
        for index, step in enumerate(cleanup["steps"], 1):
            lines.extend([f"{index}. {step['action']} 预期：{step['expected'] or '待确认，不作确定断言'}", ""])
            for key in ("method_gap", "rule_gap"):
                if step.get(key):
                    lines.extend([f"待补：{step[key]}", ""])
    lines.extend(["## 完整场景设计：只在具体步骤保留缺口", "",
        "以下路径保留同车身份、操作顺序与跨端历史，不用重置后的状态替代前序操作。",
        "“方法待补”表示结果已有依据但操作/观察尚不能落实；“规则待定”不含任何确定验收预期。", ""])
    for obligation in scenario_draft_obligations(model):
        for draft in obligation.get("scenario_drafts", []):
            lines.extend([f"### {draft['id']}｜{draft['title']}", "",
                f"状态：设计待补；关联缺口：{obligation['id']}；不计已覆盖。", ""])
            for p in draft["preconditions"]:
                lines.extend([f"准备状态：{p['state']}", "", f"准备方法：{p['setup']}", ""])
            lines.extend(["| 步骤 | 操作 | 已知预期 | 仅该步待补 | 来源声明 |",
                          "|---:|---|---|---|---|"])
            for index, step in enumerate(draft["steps"], 1):
                missing = []
                if step["method_gap"]:
                    missing.append("方法待补：" + step["method_gap"])
                if step["rule_gap"]:
                    missing.append("规则待定：" + step["rule_gap"])
                values = [index, step["action"], step["expected"] or "未规定，不作确定断言",
                          "；".join(missing) or "无", ", ".join(step["claim_ids"])]
                lines.append("| " + " | ".join(_cell(v) for v in values) + " |")
            lines.append("")
    lines.extend(["## 仍未展开的规则/方法及范围边界", ""])
    for obligation in scenario_draft_obligations(model):
        if obligation.get("status") in {"gap_rule", "gap_method"}:
            lines.extend([f"- {obligation['id']}：{obligation['objective']}。{obligation['rationale']}", ""])
            if obligation.get("diagnosis"):
                d = obligation["diagnosis"]
                lines.extend([f"归属：{d['cause']}；已知依据：{', '.join(d['known_claim_ids']) or '无确认声明'}；缺少：{d['missing_fact']}", ""])
    if preparation_library:
        lines.extend(["## 公共准备", "", "各用例仅引用其需要的条件；建立方法在此完整列出，未引用的条件不构成该用例门槛。", ""])
        for n, entry in enumerate(preparation_library, 1):
            lines.extend([f"### P{n}", "", f"状态：{entry['state']}", "", f"建立方法：{entry['setup']}", ""])
    if navigation_library:
        lines.extend(["## 公共操作全文", "", "公共导航只在主表合并显示；以下动作及结果仍全部保留，实际操作数未减少。", ""])
        for n, entry in enumerate(navigation_library, 1):
            lines.extend([f"### M{n}｜{entry['name']}", "", "| 顺序 | 操作 | 预期 |", "|---:|---|---|"])
            for i, step in enumerate(entry["steps"], 1):
                lines.append(f"| {i} | {_cell(step['action'])} | {_cell(step['expected'])} |")
            lines.append("")
    lines.extend(["## 依据与读取边界", ""])
    for claim in model.get("source_claims", []):
        lines.extend([f"- {claim['id']}｜{claim['source_id']}｜原文：{claim['quote']}；解释：{claim['statement']}", ""])
    lines.extend([f"证据清单：{payload.get('baseline_ref', '未提供')}", "",
        "本稿未增加来源适用性、产品默认行为或实测结论；未改变审批、执行、独立评审与正式导出的门禁。", ""])
    return "\n".join(lines)
