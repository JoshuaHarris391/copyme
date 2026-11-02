# 0002 — Metrics select, phrase and score; they are not prompt content

**Status:** Accepted, 2026-11-01. Implemented by
[spec 01](../specs/01-exemplars-and-rules.md).

## Context

[ADR 0001](0001-exemplars-over-descriptions.md) makes exemplars the core of the prompt.
That leaves an open question: what happens to the nine quantitative metrics, the
thirteen qualitative assessments and the metric dictionary that currently make up the
whole pre-prompt?

Two observations decide it.

**A model cannot aim at a number.** "Type-token ratio 0.42" and "punctuation density
127 per 1,000 words" are instruments built for authorship attribution. A model writing
a paragraph has no way to check its output against them mid-sentence.

**The dictionary teaches the model things it knows.** `LINGUISTIC_STYLE_METRICS` is
serialised into every v1 pre-prompt to explain what Flesch Reading Ease is. Those
tokens could carry the author's sentences instead.

## Decision

The measurements keep running on every sample and take three jobs:

1. **Choosing exemplars** — the per-passage feature vectors and the three selection
   scores.
2. **Writing rules** — each measurement becomes a short, observable instruction with a
   frequency, and only where the author departs from generic prose.
3. **Scoring output** — `Rule.band` is the accept range the scorer compares against.

They stay visible in the app, in a collapsed section, and in the JSON profile.

**Dropped from the prompt:** the metric dictionary, the raw JSON blocks,
`function_word_frequency`, and the categorical assessments as a standalone section.

Two metrics change role rather than disappear:

- `formulaic_density` stays pinned to 2-4 word sequences, as v1's README insists, so
  profiles stay comparable. Its phrases feed the signature-idiom list.
- `cohesive_harmony` is kept as a descriptor and **produces no rule**: the research
  gave no evidence a model can act on it.

A rule is emitted only when the author's feature is more than **half a standard
deviation** from the generic-prose baseline. Where the model's default is already
right, a rule is noise that dilutes the rules that matter.

## Alternatives considered

**Keep the numbers, drop only the dictionary.** Tempting, because it is a smaller
change and the numbers are cheap. Rejected: the numbers are the part the model cannot
act on. Removing the explanation while keeping the unusable payload is the worst of
both.

**Render every measurement as a rule.** Rejected. A profile would emit twenty-odd
rules, most of them describing behaviour the model already exhibits, and the three that
matter would be buried. The half-standard-deviation threshold exists for exactly this.

**Render rules from means.** Rejected for sentence length and paragraph length. A flat
mean produces the uniform rhythm readers identify as machine-written, so those render
from quartiles — "most sentences 7 to 16 words; one in ten runs past 25".

**Drop `function_word_frequency` entirely.** Rejected. It has no generation value, but
it is genuinely diagnostic for attribution and costs nothing to keep in the JSON
profile. It leaves the prompt, not the tool.

## Consequences

**Good**

- The prompt is spent on signal. Roughly the whole metric dictionary's token cost
  becomes available for exemplars.
- `Rule` is one record rendering three ways — prose, voice-card line, scorer threshold
  — so a rule and the band it is scored against cannot drift apart.
- Suppressing near-baseline features means a profile's rule list is short and every
  line is there for a reason.

**Costly**

- A generic-prose baseline becomes load-bearing: distinctiveness scoring and rule
  suppression both need it. It ships as numbers in the package and must be regenerated
  as assistant prose changes.
- Rule phrasing becomes a maintained asset. A reworded rule changes the prompt, so the
  golden-sample snapshots exist to make that a reviewed diff.
- Users who liked reading the metrics must now expand a section to find them. They are
  not removed, and `analyze_linguistic_style` keeps returning them.
