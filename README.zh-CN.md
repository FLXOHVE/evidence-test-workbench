# Evidence Test Workbench：AI 用例设计 Skill 与离线编译器

从需求设计有来源依据的用例草稿，保留歧义与覆盖缺口；可选编译器再把**明确的行为契约**展开成可评审的测试用例。

这是从已有测试工作台提取的独立核心，适合作为测试开发、质量工程或 AI 工程作品集。只需要 Python 3.10+，不需要车辆、公司账号、API Key 或第三方运行依赖。

可以先看[实际生成的演示结果](docs/example-output.md)。

## 使用 AI 用例设计 Skill

把 [skills/evidence-case-design/](skills/evidence-case-design/SKILL.md) 整个目录安装到编码代理支持的技能目录，提供需求材料与范围。Skill 指导代理分析需求、边界、状态与可观察预期，不依赖 STRUTT 业务平台；仅安装 Skill 也可以输出 Markdown 用例。模型由使用者的代理提供。

```sh
python tools/package_skill.py --output dist/evidence-case-design.zip
```

打包包含技能、虚构样例和许可证，使用新的输出路径。下面的离线演示验证编译器，不代替对 AI 用例设计质量的独立评测。

## 一分钟运行编译器

在仓库目录执行：

```sh
python -m evidence_test_workbench demo --output demo-output
python -m unittest discover -s tests -v
```

打开 `demo-output/cases.md` 查看用例草稿，`summary.json` 查看编译结果。`contract.json` 是本次使用的虚构输入，可修改后重新编译：

```sh
python -m evidence_test_workbench compile demo-output/contract.json --output build/my-cases --phase core
```

示例是虚构任务清单：筛选全部、进行中和已完成任务，以及归档任务。外部同步规则故意留空，用来展示系统怎样报告未知，而不是替产品猜规则。每次使用新的输出目录。

## 展示的工程能力

- 用例关联需求声明与覆盖义务，方便回查“这个预期从哪里来”。
- 行为路径与参数变体批量展开，保留稳定用例 ID。
- 缺失预期、未确认声明、缺少准备方法均显式处理。
- 模块核心能力与跨模块耦合分别管理，必要前置不能随意推迟。
- 生成、评审和执行分开：生成结果始终是草稿，执行状态是“未执行”。

Python 编译器接受结构化契约，**不直接把自然语言自动理解为正确需求**。契约需要人或上游 AI 阅读来源后编写；引用存在也不代表语义正确，还需要独立评审。

## 范围

包含通用用例设计 Skill、编译核心、虚构案例、CLI、JSON/Markdown 导出、离线测试和 CI 配置。

原系统的需求池、来源采集、审批失效、执行历史保护、Excel、Jira、网页平台及整车执行没有包含在本次提取包中。演示通过不证明这些能力已完成本机验收，也不证明任何真实产品通过测试。

设计说明见 [docs/design.md](docs/design.md)，发布前事项见 [docs/publication.md](docs/publication.md)。作者已确认自有代码；本项目采用 [MIT 许可证](LICENSE)。
