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

All six were decided together in the v2 design review on 2026-11-01. Each is now
**implemented**: the modules are in `src/copyme/` and each spec says which ADR it
assumes.

Implementation did not change any of the six decisions, but it did surface two things
worth recording against them rather than leaving in a commit message:

- **0003** assumes name masking removes one-off names. In practice it removes the ones
  spaCy's small English model recognises, and that model's recall on personal names is
  well short of complete. The decision stands; the limitation is documented on
  `separation.py` and in the app, and masking should not be described as redaction.
- **0006** keeps the static tier as the default because it has no model dependency.
  Implementation added a second reason: the live tier needs passages the selector did
  not choose, and a sample of a few thousand words can be consumed entirely by a
  Standard selection, so the static tier is also the only tier that works on a short
  sample.
