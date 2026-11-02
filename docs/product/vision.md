# Vision

copyme exists so that a person can hand a language model a sample of writing and get
back text that sounds like it.

v1 measures the sample and throws the sample away. v2 keeps the sample, chooses the
passages that carry the voice, and uses the measurements for the three jobs they are
actually good at: choosing those passages, writing rules a model can follow, and
scoring the output afterwards.

## What is wrong with v1

v1 computes sentence length, vocabulary diversity, hedging, punctuation density and
readability, then pastes those numbers into a prompt alongside a dictionary that
explains each one. Three things are wrong with that.

**It keeps the weak signal and discards the strong one.** Across the studies reviewed
for this design, a dozen real passages of an author's writing produced more faithful
imitation than any description of that writing. One 2026 study found model-written
style descriptions did *worse than random* at recovering a style. v1 sends only the
description.

**A model cannot aim at a number.** "Type-token ratio 0.42" and "punctuation density
127 per 1,000 words" are measurement instruments built for identifying authors, not
instructions a writer can follow. The model has no way to check its output against
them while writing.

**Most of the prompt is spent on definitions.** The metric dictionary teaches the model
what Flesch Reading Ease is. It already knows. Those tokens could carry the author's
actual sentences.

The engineering around the core is sound and stays: the memory budget, the cached parse
behind the sliders, progress reporting, the test suite. What changes is what goes into
the prompt.

## The core change

A copyme profile becomes four things instead of one.

| Part of the profile | What it is | Why it is there |
|---|---|---|
| **Exemplars** | 5 to 30 passages of the author's real writing, picked because they are typical of the author and unlike generic prose | This is what the model learns the voice from. The evidence says it is the part that works. |
| **Voice rules** | Short, observable instructions derived from the measurements: "sentences average 11 words and a third are under six", "a dash about once a paragraph, semicolons almost never" | A model can follow a habit stated as behaviour. It cannot follow a ratio. |
| **Known failures** | Two or three "this is how a model drifts on this author" notes, each with the correction | The one prompting technique with direct evidence on Claude: show the model its own mistake and why it is wrong. |
| **Voice card** | Five lines that compress the rules, for re-pasting mid-conversation | Prompted voices measurably decay after about eight turns. The card re-anchors them. |

The measurements still run on every sample and stay visible in the app for anyone who
wants them. They stop being the prompt.

## Two principles that follow

**Style, not subject.** The vocabulary and phrase lists are filtered to *how* the
author writes (connectives, openers, hedges, idioms) rather than *what* they wrote
about, so the model does not keep returning to the sample's topic. One-off names in
exemplars are replaced with role placeholders. The instruction block says it outright:
the examples show how this person writes, not what they know or believe.

**Frequency, not presence.** Every rule carries a frequency — "about once a paragraph",
"one sentence in five" — because the most common failure of a prompted voice is
performing every quirk in every sentence. The instruction block closes on the same
point.

## What gets measured, and what it is for

| Job | Who does it |
|---|---|
| Choose which passages the model sees | The per-passage feature vectors and the three selection scores |
| Turn a measurement into an instruction | The rules renderer, which suppresses anything a model already does by default |
| Tell the user whether it worked | `score()`, comparing the model's output with the author's bands |

See [../specs/README.md](../specs/README.md) for how these fit together in code, and
[../adr/](../adr/) for the decisions behind them.
