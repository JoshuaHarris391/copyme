# 0004 — The JSON profile is the contract; every export is a renderer over it

**Status:** Accepted, 2026-11-01. Implemented by
[spec 02](../specs/02-separation-and-exports.md).

## Context

v1 has one output: a Markdown block to paste as the first message of a chat. v2 needs
at least five — a chat message, a system prompt, a five-line voice card, a SillyTavern
Character Card V2, and a machine-readable object — plus two partial formats for
applications that assemble their own prompt.

Written naively, that is five code paths that each re-derive rules and exemplars from an
analyser, drift apart, and have to be changed together every time the profile gains a
field.

There is also a caching constraint. API consumers cache the stable prefix of a prompt,
so the section order cannot vary between renders of the same profile.

## Decision

`Profile` is a **frozen dataclass** holding features, rules with their bands, exemplars
with their reasons, known failures, and provenance. It serialises to the `json` export
and back, losslessly.

Every other target is a pure renderer: `Profile` in, string out. Nothing downstream of
`Profile` touches `StyleAnalyser`, the spaCy document, or the selector.

A profile built once can be re-rendered at any size and in any format **without
re-parsing**, which is what makes the size radio instant and what lets `copyme render`
work from a saved file with no sample present.

Section order inside the prompt formats is fixed: instruction, rules, exemplars, known
failures, voice card.

Backwards compatibility: `build_profile` called with only its v1 arguments keeps
returning the current dict, and `build_pre_prompt` accepts that dict and produces the
v1 block. The notebooks and the existing tests keep working.

## Alternatives considered

**Render each target from the analyser.** The straightforward extension of v1, where
`build_pre_prompt(results)` takes the analysis dict. Rejected: it ties every export to
a live parse, so `copyme render profile.json` would be impossible, the Score tab would
need the sample in memory, and Maya could not consume a profile at all.

**Make the dict the contract instead of a dataclass.** Rejected. A dict has no schema,
so a renderer cannot tell a missing field from a `None`, and the round-trip test — the
thing that actually keeps the contract honest — has nothing to assert against. A frozen
dataclass also prevents a renderer mutating a profile another renderer then reads.

**Let each export choose its own section order, optimised for its target.** Rejected
for the caching constraint. A varying prefix defeats prompt caching for API consumers,
and the cost of a slightly suboptimal order is much lower than the cost of
re-processing the stable part on every call.

**Version the JSON schema from day one.** Deferred, not rejected. Provenance already
records the copyme version and the baseline version, which is enough to detect a
mismatch. An explicit schema version is worth adding the first time the shape changes
incompatibly.

## Consequences

**Good**

- Adding a sixth export target touches one file and needs no change to selection or
  rendering.
- The JSON is the integration surface for every other application, so copyme does not
  have to anticipate them. Maya, SillyTavern and Claude Projects are all renderers or
  consumers, not special cases — see [../product/integrations.md](../product/integrations.md).
- `score(generated, against=profile)` needs only a profile, so a user can score
  output months later against a saved file.
- Frozen means a profile is safe to cache in `st.session_state` and safe to hand to
  two renderers at once.

**Costly**

- One more layer between the analyser and the prompt, and one more place a field has to
  be added when the feature set grows.
- Any field that the JSON omits is invisible to every consumer, so the round-trip
  equality test is load-bearing rather than cosmetic.
- A profile now contains the author's prose, so a JSON file is not a neutral artifact:
  it carries the sample's passages and must be treated like the sample itself.
