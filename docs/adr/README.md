# Architecture decision records

One decision per record. Each is one page: context, decision, alternatives considered,
consequences.

An accepted ADR is not rewritten. If a decision changes, a new ADR supersedes it and
both link to each other.

| # | Decision | Status |
|---|---|---|
| [0001](0001-exemplars-over-descriptions.md) | Send the author's real passages, not a description of their writing | Accepted |
| [0002](0002-metrics-move-behind-the-scenes.md) | Metrics select, phrase and score; they are not prompt content | Accepted |
| [0003](0003-separate-style-from-content.md) | Filter vocabulary to manner words and mask one-off names | Accepted |
| [0004](0004-profile-json-is-the-contract.md) | The JSON profile is the contract; every export is a renderer over it | Accepted |
| [0005](0005-no-prefill-in-exports.md) | No export emits assistant-message prefill | Accepted |
| [0006](0006-static-contrastive-by-default.md) | The static contrastive tier is the default; the live tier records its model | Accepted |

All six were decided together in the v2 design review on 2026-11-01 and are accepted as
design decisions. The code that implements them is specified in
[../specs/](../specs/) and not yet built; each spec says which ADR it assumes.
