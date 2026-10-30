# Changelog

## 0.1.0 — local candidate, 2026-10-30

- Extracted the compiler's 13-module standard-library dependency closure, preserving source provenance and hashes.
- Added an offline CLI, synthetic task-list requirements and contract, JSON/Markdown export, packaging metadata, bilingual documentation, and GitHub Actions configuration.
- Added 22 regression tests covering stable identity, unresolved requirements, unsafe placeholders, invalid inputs, explicit expected results, boundaries, and output preservation.
- Reject a malformed model with a domain error.
- Reject text that becomes blank after parameter substitution, so cases cannot acquire empty expectations.
- Reject unknown coverage-obligation states instead of silently losing scope.
- Require behavior outcomes to be a non-empty array of non-blank strings instead of expanding a single string character by character.

Validation performed locally on Windows with Python 3.13: 22 tests passed, and a built wheel installed into a fresh environment ran the synthetic demo outside the source directory. A separate no-site-packages run with network and subprocess audit guards also passed. The configured Linux/Python 3.10 CI matrix has not yet run on GitHub.

The demo produces four unexecuted drafts and one unresolved dependency. These numbers describe the synthetic fixture only. The author confirmed ownership on 2026-10-31; project code is released under MIT.
