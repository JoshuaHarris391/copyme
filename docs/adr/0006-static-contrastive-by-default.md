# 0006 — The static contrastive tier is the default; the live tier records its model

**Status:** Accepted, 2026-11-01. Implemented by
[spec 03](../specs/03-scorer-and-contrast.md) (static) and
[spec 04](../specs/04-live-loop-and-evaluation.md) (live).

## Context

The one prompting technique with direct evidence on Claude is contrastive: show the
model an off-voice attempt beside the real passage with a one-line explanation of the
gap (Cho et al., TICL, arXiv 2502.08972, 2025). In that work **the explanations carried
most of the gain**, not the examples of failure.

There are two ways to get such a pair.

**Statically**, from the delta between the author's feature vector and the generic-prose
baseline. That delta already says where a model will drift. It costs no API call, no
key and no network.

**Live**, by holding out passages, asking the target model to write on their subjects,
scoring the drafts, and turning the scorer's summary into a note. More accurate,
because it observes the actual drift rather than predicting it.

Two findings from the same body of work constrain the live route. Corrections built
against one model **transfer poorly to another**. And smaller models sometimes **imitate
the bad example rather than avoid it**.

## Decision

**The static tier is the default.** `contrastive="static"` requires no key, no network
and no configuration, and it produces at most three known-failure notes, ranked by
delta size.

**The live tier is opt-in** (`contrastive="live"`), runs once at profile time, and is
cached in the JSON so no later render costs an API call. It **records the model it ran
against**, and the UI and CLI warn when a profile is rendered for a different model.

**The Compact preset carries only correction text, never a failed draft**, at both
tiers, because of the imitate-the-bad-example finding.

With no key present, `contrastive="live"` degrades to `"static"` with a stated reason
rather than failing.

## Alternatives considered

**Live tier as the default.** Rejected. It would make an API key a prerequisite for the
tool's main output, put a network call in the middle of a flow that is otherwise
instant and offline, and bake a per-model correction into every profile — including
profiles that will be pasted somewhere else entirely.

**Static tier only; drop the live tier.** Considered. It is a real option: the static
tier captures the technique's main ingredient, which is the explanation. Rejected
because the live tier is the only mechanism that observes drift rather than predicting
it, and it is what lets an application like Maya harvest its own failures against the
model it actually uses.

**Always include the failed draft, at every size.** Rejected on the imitation finding.
At Standard and Full the draft earns its tokens; at Compact the risk of a small model
copying it outweighs the benefit.

**Generate notes with a model rather than from the delta.** Rejected: model-written
style descriptions were measured as worse than random (Kim and Jurgens, arXiv
2606.05716, 2026), and the static tier's whole value is that it is derived from
measurement.

## Consequences

**Good**

- The default path stays pure: no key, no network, deterministic output, and a profile
  that is reproducible from the sample alone.
- The contrastive block is present for every user, not only those with an API key.
- A live-tier profile is honest about its model dependency instead of silently
  misleading when pasted elsewhere.

**Costly**

- Static notes predict drift rather than observing it, so some will be wrong. Capping
  at three limits the damage; the scorer is what catches a note that was aimed at the
  wrong habit.
- Two tiers means two code paths producing the same field, and the warning logic is
  one more piece of state the UI carries.
- The static tier inherits the baseline's accuracy. A stale baseline produces
  confidently wrong drift notes, which is why the baseline is versioned in every
  profile and refreshed from a script — see
  [../specs/03-scorer-and-contrast.md](../specs/03-scorer-and-contrast.md).
