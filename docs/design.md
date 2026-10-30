# Design and boundaries

## Why a compiler

Natural-language interpretation and deterministic expansion have different failure modes. An upstream author identifies source claims, observable behaviors, preparations, and explicit variants. This package expands that contract and preserves the unresolved work.

The compiler can check structural consistency. It cannot establish that a cited claim is true, that a quotation is the right interpretation, or that the selected scenarios cover every important product risk. Those are review responsibilities.

## Data flow

1. The contract identifies its module and case namespace.
2. Source claims describe the evidence supporting expected behavior.
3. Coverage obligations identify what the design needs to check.
4. Recipes reference behavior paths and preparations; explicit variants bind their parameters.
5. The compiler emits draft cases, scoped model data, tasks, and deferred obligations.
6. The CLI exports readable Markdown and JSON without invoking a test runner or external system.

## Identity and change

Case identity is based on namespace, recipe ID, and variant ID. It is intentionally independent of presentation titles. Stable identity helps downstream tools relate revisions; it does not justify carrying a previous execution result across a behavior change. That execution-history policy belongs to the full workbench and is outside this package.

## Honest result handling

Missing product behavior must remain a rule gap. Missing preparation or observation methods are implementation gaps. Mandatory prerequisites must not be hidden in a deferred phase. Draft cases are unexecuted, and compilation cannot confer independent approval.

The synthetic example is an installation and contract demonstration. It is not a benchmark for LLM quality, real-world coverage, throughput, or defect discovery.

## Extraction tradeoff

The existing compiler depends on several contract-validation modules. Keeping that dependency closure preserves behavior better than rewriting its rules into a smaller, incompatible example. Some advanced validators are included even though the small demo does not exercise every policy. Integration code and real product datasets remain excluded.

The CLI and presentation layer are new. The provenance manifest records which upstream files were copied and their hashes. An open-source license must be selected by someone authorized to license those files.

## Next useful work

- Add a versioned JSON Schema and concise contract-authoring guide.
- Add a second synthetic example exercising integer boundaries and requirement changes.
- Build an optional model adapter that returns a reviewable contract, with measured hallucination and omission checks.
- Preserve independent human review before any real execution or publication.

These are follow-up ideas, not implemented features of this candidate.
