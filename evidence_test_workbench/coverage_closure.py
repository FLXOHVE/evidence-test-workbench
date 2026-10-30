"""Shared discovery/probe/cleanup contract; declarations are not semantic proof."""
from copy import deepcopy

from .module_generation import GenerationError

POLICY = "coverage-closure-v1"
KINDS = {"sample", "domain", "minimum_change", "effective_state", "transition", "effect", "scope"}
STIMULI = {"observe", "select_target", "single_adjustment", "enumerate_domain", "state_event", "consumer_action"}
OBSERVATIONS = {"editor_value", "available_values", "effective_readback", "state_and_readback", "functional_output"}
SOURCE_INSTRUCTIONS = """
先按资源反查整份已读来源：除本功能直接修改，还找谁会替换、重置、保存、恢复或导入同一配置/数据；不要只逐本模块参数行。原文仅给操作名而作用范围未知，也列有逐字依据的待查关联，不自动推定影响或扩大成该操作所属模块全回归。
条件不仅检查进入前：按可达性分析操作已进入/正在编辑/即将完成时，资格或依赖条件改变，再继续操作的历史；不存在的中间态不编造，待查与有依据不适用分别保留。
数值的端点显示、端点附近的有序变化、最小调节单位、完整可选域、实际生效是不同目标。按需要考虑两端到达/反向离开；不要以到达端点代表相邻迁移，也不按数据点凑条数。
每项verification_kind从sample/domain/minimum_change/effective_state/transition/effect/scope选择；它只是独立读者声明的所需检查强度。未知预期仍为null，已读事实未整理入内部规则池不等于产品没有定义，reason分开记录已知事实、整理/适用性和真实未知。
保存/恢复逐资源及触发分析，包含同组布尔/枚举。保存用可区分默认回退的合法前态，恢复默认前先设非默认；前后碰巧同默认不能排除未保存或未重置。实际消费保留事件前参照、事件后未重写的首次使用，不能只看开关/数值或重选后的输出；无法可靠判读保留精确方法限制。
资源profile的terms使用具体资源/能力名称和有意义别名；通用入口名、布尔值、数值范围记号不单独当资源词铺满召回。原文中的可疑配置操作即使未含本模块词，也须语义审查其作用范围。
核对原始结构中的删除线、被替代说明、表头和列归属；纯文本仍出现的已划除操作不能与未划除规则同级采纳，方法待查中也要保持这一区别。
按来源实际定义的可观察契约列义务，区分配置选择、跨页显示保持、睡眠/电源后保持和实际消费者效果。不要把原文未要求的内部独立存储通道当需求；内部缓存反例可挑战功能效果，但若满足界面契约，不能据此否定界面检查。默认值明确时保留默认设计，未完成现场基线交接属于执行准备，不是默认需求未知。
"""
AUTHOR_INSTRUCTIONS = """
coverage-closure-v1：沿冻结资源义务覆盖所有可能改写/替换/恢复/保存同一状态的操作；未定作用先保留准确查证，不因未入内部规则池把已读事实抹成产品未知。按实际可达性分析操作中途资格改变，不能用关闭后重新进入代替已进入后条件失效。
每个planned coverage_plan.obligation增加verification={claim_scope,stimulus,observation,reason}。claim_scope为sample/domain/minimum_change/effective_state/transition/effect；stimulus为observe/select_target/single_adjustment/enumerate_domain/state_event/consumer_action；observation为editor_value/available_values/effective_readback/state_and_readback/functional_output。
选两个目标值的差不等于系统最小变化；editor_value不等于有效配置。最小变化须真实一次最小操作及前后观察，或有依据的完整可选域观察；方法未知则保留完整待补路径，不伪标single_adjustment。声明标签不证明实际文字做到，独立复核将提出错误实现反例。
重入页面只认领来源规定的界面配置与显示保持，不自动证明真实消费者生效；若来源还要求外部持久状态或消费者效果，须用该目标对应的观察。不要仅换“有效值”字眼，也不把内部结构假设强加给UI契约。
按检查目标限定反例：UI选择/重入保持可直接用用户界面判定，不要求证明内部结构；实际声音/动作仍须独立消费检查。默认检查安排在任何修改前，准备使用未配置供测对象及交接记录，不编Reset语义；未执行准备不等于不能形成有明确预期的设计。查到明确入口/动作须先整理入固定规则再使用，不无限留在source_work。
所有gap含diagnosis={cause,known_claim_ids,missing_fact}：cause为product_rule/source_work/operation_method/execution_setup。product_rule只用于查后仍缺业务结果，operation_method和execution_setup须为gap_method并引用已知确认声明。流程目录/适配器/设计未完成不能冒充产品gap，先修流程。部分步骤未知只影响该步及依赖，不吞掉无关已知检查。
准备只能建立输入、身份、权限和外部环境，不把被测保存已成功、目标音量已生效或扬声器工作正常写成前提；这些是待检结果。已修改后读取时不能先重写目标值破坏历史。
逐资源（包括布尔/枚举）反查保存和恢复触发。保存选与已知默认/回退可区分的合法前态，恢复默认先设非默认；实际消费者保留事件前真实参照，事件后不重设先消费。只读回开关不能认领其控制的编辑资格或真实功能已继续有效。已有来源/方法但尚未设计的cell属于生成工作，补实际检查，不填unresearched或造产品gap收尾。定性不能可靠区分时必须保留不确定，不发明量化阈值或内部API。
验证修改/禁止修改时，单一目标可能碰巧等于当前值，不能以没有可见变化证明成功修改或禁止修改。先建立有依据、可观察且不同的前值；前值不可读时可尝试两个不同合法目标，并观察控件操作/接受/拒绝的可见反馈。不得假设能读隐藏值或重开不影响旧值；观察能力不足则记录不确定，不把无变化自动判通过。
对有不可逆数据副作用的操作，使用明确的隔离供测对象和结束状态，不用普通配置收尾承诺恢复被删除数据；该路径的准备不无差别阻断无关配置场景。
端点值与端点前后历史按风险分别处理，可用数据变体保留两端进入/反向退出和可区分方向；不为穷举或条数机械拆例。已知完整源义务可由同源具体gap保留，局部UI检查只认领sample，不冒充完整义务覆盖。
必须给suite_cleanup，模块级记录原状态/数据，steps用role=restore与role=observe分别安排恢复及随后读回（每步一动作），未定操作和默认基线分别保留。不要每条重复长收尾，不把手动设成默认数字当未修改基线，也不发明复位入口。cleanup中的缺方法/规则引用真实gap，不能静默省略。
收尾以本次实际执行路径会触及的资源为范围，不把尚未执行的待补路径或全模块潜在资源强加给已就绪场景；不为收尾新增无关配置修改。待补路径将来执行时的捕获/恢复要求仍保留在其路径中，未知只阻断有关范围。
"""
PROBE_GUIDE = {"claim_scope": "sample|domain|minimum_change|effective_state|transition|effect",
               "stimulus": "observe|select_target|single_adjustment|enumerate_domain|state_event|consumer_action",
               "observation": "editor_value|available_values|effective_readback|state_and_readback|functional_output",
               "reason": "actual observation surface and supported semantics that discriminate a violating implementation; page reentry alone does not establish independent effective state"}
CLEANUP_GUIDE = {"status": "planned|gap_rule|gap_method|not_applicable", "scenario_ids": ["mutating scenario IDs"],
    "capture": {"state": "original identity/config/data to preserve", "setup": "how to record before changes"},
    "steps": [{"role": "restore", "action": "restore original state using supported method", "expected": "known result or null",
               "claim_ids": [], "method_gap": None, "rule_gap": None},
              {"role": "observe", "action": "read back without resetting state", "expected": "original state or null",
               "claim_ids": [], "method_gap": None, "rule_gap": None}],
    "gap_ids": [], "reason": "shared cleanup and baseline limits; not execution evidence"}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def validate_probe(value):
    if (not isinstance(value, dict) or set(value) != {"claim_scope", "stimulus", "observation", "reason"}
            or value.get("claim_scope") not in KINDS - {"scope"} or value.get("stimulus") not in STIMULI
            or value.get("observation") not in OBSERVATIONS or not _text(value.get("reason"))):
        raise GenerationError("A planned obligation needs an explicit verification probe")
    goal, action, observation = (value[k] for k in ("claim_scope", "stimulus", "observation"))
    if goal == "minimum_change" and action not in {"single_adjustment", "enumerate_domain"}:
        raise GenerationError("Target selection does not prove minimum change")
    if action == "enumerate_domain" and observation != "available_values":
        raise GenerationError("Domain enumeration requires observing available values, not one editor value")
    if goal == "minimum_change" and observation == "functional_output":
        raise GenerationError("A functional output alone does not measure a minimum numeric change")
    if goal == "domain" and (action != "enumerate_domain" or observation != "available_values"):
        raise GenerationError("Sampled target values do not prove the complete allowed domain")
    if goal == "effective_state" and observation not in {"effective_readback", "state_and_readback"}:
        raise GenerationError("Editor display does not prove effective configuration")
    if goal == "transition" and (action != "state_event" or observation not in {"state_and_readback", "functional_output"}):
        raise GenerationError("A point observation does not prove a state transition history")
    if goal == "effect" and (action != "consumer_action" or observation != "functional_output"):
        raise GenerationError("Configuration display does not prove functional output")
    return value


def validate_gap_diagnoses(policy, gaps, claims):
    if policy:
        if policy != "gap-cause-v1":
            raise GenerationError("Unsupported gap resolution policy")
        confirmed = {c["id"] for c in claims if c.get("semantic_status") == "confirmed"}
        for gap in gaps:
            d = gap.get("diagnosis")
            if (not isinstance(d, dict) or set(d) != {"cause", "known_claim_ids", "missing_fact"}
                    or d.get("cause") not in {"product_rule", "source_work", "operation_method", "execution_setup"}
                    or not _text(d.get("missing_fact")) or not isinstance(d.get("known_claim_ids"), list)
                    or any(not _text(c) or c not in confirmed for c in d["known_claim_ids"])):
                raise GenerationError("A gap needs a concrete product/source/method/setup diagnosis; process work is not a product gap")
            if d["cause"] in {"operation_method", "execution_setup"} and (gap["status"] != "gap_method" or not d["known_claim_ids"]):
                raise GenerationError("Known-rule preparation or method work cannot be classified as an unknown product rule")
            if d["cause"] == "product_rule" and gap["status"] != "gap_rule":
                raise GenerationError("An undefined product outcome requires a rule gap")


def validate(request, response, plan):
    if "coverage_closure_policy" not in request:
        if "suite_cleanup" in response:
            raise GenerationError("Cleanup requires its prepared closure policy")
        return None
    if request["coverage_closure_policy"] != POLICY or not plan:
        raise GenerationError("Unsupported or missing coverage closure plan")
    scenes = {s["id"]: s for s in response["scenarios"]}
    gaps = {g["id"]: g for g in response["gaps"]}
    validate_gap_diagnoses(request.get("gap_resolution_policy"), gaps.values(), response["claims"])
    probes = {}
    active = set()
    for row in plan["analysis"]["obligations"]:
        if row["status"] == "planned":
            probe = validate_probe(row.get("verification"))
            for check in row["checks"]:
                sid = check["scenario_id"]
                probes.setdefault(sid, set()).add((probe["claim_scope"], probe["observation"]))
                if probe["stimulus"] in {"select_target", "single_adjustment", "state_event"}:
                    active.add(sid)
    # Independent goals cannot be silently downgraded to sample-only checks.
    audit = (request.get("coverage_catalog") or {}).get("source_audit", {})
    for item in audit.get("inventory", {}).get("items", []):
        kind = item.get("verification_kind", "scope")
        ref = "SA:" + item["id"]
        sids = {sid for sid, s in scenes.items() if ref in s.get("catalog_refs", [])}
        has_gap = any(ref in g.get("catalog_refs", []) for g in gaps.values())
        if kind == "scope" or item["status"] != "defined" or not sids or has_gap:
            continue
        accepted = {kind} | ({"domain"} if kind == "minimum_change" else set())
        compatible = any(scope in accepted or (kind == "effective_state" and scope == "transition"
                         and observation == "state_and_readback")
                         for sid in sids for scope, observation in probes.get(sid, set()))
        if kind != "sample" and not compatible:
            raise GenerationError("Independent verification scope was reduced to a sample: " + ref)
    value = deepcopy(response.get("suite_cleanup"))
    if (not isinstance(value, dict) or set(value) != {"status", "scenario_ids", "capture", "steps", "gap_ids", "reason"}
            or value.get("status") not in {"planned", "gap_rule", "gap_method", "not_applicable"}
            or not _text(value.get("reason")) or not isinstance(value.get("scenario_ids"), list)
            or any(not _text(s) or s not in scenes for s in value["scenario_ids"])
            or len(set(value["scenario_ids"])) != len(value["scenario_ids"])
            or not isinstance(value.get("gap_ids"), list) or any(not _text(g) or g not in gaps for g in value["gap_ids"])
            or not isinstance(value.get("steps"), list)):
        raise GenerationError("A bound shared suite_cleanup is required")
    if not active <= set(value["scenario_ids"]):
        raise GenerationError("Cleanup omitted scenarios with declared state-changing stimuli")
    status = value["status"]
    if status == "not_applicable":
        if active or value["scenario_ids"] or value["capture"] is not None or value["steps"] or value["gap_ids"]:
            raise GenerationError("State-changing designs cannot waive cleanup as not applicable")
        return value
    capture = value["capture"]
    if (not isinstance(capture, dict) or set(capture) != {"state", "setup"}
            or not all(_text(v) for v in capture.values()) or not value["steps"]):
        raise GenerationError("Cleanup needs original-state capture, restoration and observation")
    if (status == "planned" and value["gap_ids"]) or (status != "planned" and not value["gap_ids"]):
        raise GenerationError("Unready cleanup must retain an actual gap")
    claims = {c["id"] for c in response["claims"] if c.get("semantic_status") == "confirmed"}
    roles = [step.get("role") for step in value["steps"] if isinstance(step, dict)]
    if "restore" not in roles or "observe" not in roles or roles.index("restore") >= roles.index("observe"):
        raise GenerationError("Cleanup needs restoration followed by a separate observation")
    for step in value["steps"]:
        if (not isinstance(step, dict) or set(step) != {"role", "action", "expected", "claim_ids", "method_gap", "rule_gap"}
                or step.get("role") not in {"restore", "observe"}
                or not _text(step.get("action")) or not isinstance(step.get("claim_ids"), list)
                or any(not _text(c) or c not in claims for c in step["claim_ids"])
                or any(step[k] is not None and not _text(step[k]) for k in ("method_gap", "rule_gap"))
                or (step["rule_gap"] is None and (not _text(step["expected"]) or not step["claim_ids"]))
                or (step["rule_gap"] is not None and step["expected"] is not None)
                or (status == "planned" and (step["method_gap"] or step["rule_gap"]))):
            raise GenerationError("Cleanup actions need source-backed results or explicit unknowns")
    return value
