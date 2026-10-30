# 可选契约编译器

本仓库包含 evidence_test_workbench Python 包。Skill 的自然语言分析由调用它的编码代理完成；本工具不是一个独立 LLM 服务。

自包含的虚构示例见 [需求](../assets/requirements.md) 和 [契约](../assets/task-list.contract.json)。所有 ID、行为和数据都只用于示例，不是实际业务资料。

契约中的 model 保存来源声明、行为与覆盖义务；preparations 声明如何建立状态；recipes 关联义务、行为路径、准备和明确的变体。以示例的实际字段为准，不把不同项目的需求硬改成待办事项领域。

source_claims 的 semantic_status=confirmed 表示作者认为该声明有充分来源依据，编译器并不验证其真实性。未确认内容不要改成 confirmed 来消除报错。结果始终保持未执行、待独立审核。

在仓库根目录，使用新输出目录：

```sh
python -m evidence_test_workbench compile skills/evidence-case-design/assets/task-list.contract.json --output build/skill-example
```

自己的契约：

```sh
python -m evidence_test_workbench compile contract.json --output build/cases --phase core
```

core 阶段保留未决耦合为 backlog；coupling 阶段检查对应缺口。必须属于核心的前提不可强行延期。产物 cases.md 供人阅读，cases.json 和 summary.json 供后续程序核对。退出码为 0 只说明编译和导出完成，不表示无缺口或需求已通过测试。已有目录不会被覆盖。
