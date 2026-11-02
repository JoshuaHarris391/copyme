# 0001 — Send the author's real passages, not a description of their writing

**Status:** Accepted, 2026-11-01. Implemented by
[spec 01](../specs/01-exemplars-and-rules.md).

## Context

copyme v1 computes a statistical description of a writing sample — type-token ratio,
mean sentence length, punctuation density, hedging, readability — pastes it into a
pre-prompt alongside a dictionary defining each metric, and discards the sample.

The research reviewed for v2 is consistent and points the other way:

- A dozen real passages of an author's writing produced more faithful imitation than
  any description of that writing (Wang et al., EMNLP 2025 Findings; Agarwal et al.,
  NeurIPS 2024).
- Model-written style descriptions did **worse than random** at recovering a style
  embedding (Kim and Jurgens, arXiv 2606.05716, 2026).
- Explicit style analysis underperformed plain few-shot prompting on Claude 3 Sonnet
  (Cho et al., TICL, arXiv 2502.08972, 2025).
- Descriptor-plus-paraphrase prompting never got "towards target" above 0.16 (Patel et
  al., STYLL, AAAI 2024).

v1 sends only the description. It is sending the weak signal and discarding the strong
one.

## Decision

The profile sends **5 to 30 passages of the author's real writing**, selected on
typicality, distinctiveness from generic prose, and diversity of register. Exemplars
are the core of the prompt.

Measurements remain, in a changed role (see
[ADR 0002](0002-metrics-move-behind-the-scenes.md)).

## Alternatives considered

**Keep the description and add exemplars.** Rejected as the default. The prompt budget
is finite and the research shows the description can actively mislead; keeping both
would spend tokens on the weaker half and make it impossible to tell which half worked.
The measurements remain available in the UI and the JSON profile for anyone who wants
them.

**Fine-tune on the author instead.** This is the approach the strongest human study
found convincing to expert readers (Chakrabarty et al., arXiv 2510.13939v4, 2026: odds
ratio 8.16 for fine-tuned against 0.16 for in-context). Rejected because it needs
roughly 50k tokens of an author's work, a GPU, per-author training time and a hosting
story, and because copyme's premise is that a person can paste a sample and get a
prompt back in seconds. Permanently out of scope, recorded in
[../product/non-goals.md](../product/non-goals.md).

**Have a model write the style description.** This is precisely what Kim and Jurgens
measured as worse than random.

**Send the whole sample.** Rejected: it blows any context budget on long samples,
it drags the sample's subject into every output, and it offers no way to trade size
against fidelity. Selection is what makes the three size presets possible.

## Consequences

**Good**

- The part of the prompt doing the work is the part the evidence supports.
- Size presets become meaningful: more budget means more exemplars, which means more
  signal, rather than more definitions.
- The sample must be kept through profiling, which is what makes `score()`'s copying
  check and the held-out passages of the live tier possible at all.

**Costly**

- A minimum sample size appears. Below about 2,000 words there is nothing to select
  between, so the tool must say so instead of producing a confident profile.
- The sample's subject can leak into output, which forces the filtering and masking of
  [ADR 0003](0003-separate-style-from-content.md).
- A copying risk appears: the model may reproduce exemplar sentences. Mitigated by an
  explicit instruction and enforced by the scorer's 12-word check.
- Profiles get larger, and a profile now contains the author's actual prose, which
  makes provenance and attribution a real concern rather than a theoretical one.

**Reversal condition**

If the blind pairwise test in [spec 04](../specs/04-live-loop-and-evaluation.md) fails
after the selection weights and the rule phrasings have both been revisited, this ADR
is reopened with the numbers attached. Nothing short of that justifies reverting to a
description-only prompt.
