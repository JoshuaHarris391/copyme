# What success looks like

The test that matters is a blind one.

A reader who knows the author is shown a real passage and a model passage **on a topic
the sample never covered**, and asked which is which. Today's copyme has never been
measured this way.

**Target for v2: readers pick correctly no better than 70% of the time on Standard
profiles**, down from the near-certainty the research reports for description-only
prompts. Expert readers will still usually tell. The goal is "recognisably them", not
undetectable — see [non-goals.md](non-goals.md).

## Three cheaper checks

These run on every release and are automatable. They do not replace the blind test;
they catch regressions between blind tests.

| Check | How | Pass |
|---|---|---|
| Scorer agreement | Profile the model's output against the author's | No rule drifts by more than one band — for example, sentence length stays within the author's quartile range |
| Drift | A 20-turn scripted chat, scored at turns 1, 8, 16 and 20 | Scores at turn 20 within 10% of turn 1, when the voice card is re-pasted at turns 8 and 16 |
| Copying | Longest common substring between output and sample | No run of 12 or more consecutive words shared with the sample |

## What the scorer does not claim

`score()` measures the habits copyme can measure. A passage can pass every band and
still not sound right, and the research is clear that classifier-style agreement can
coexist with prose far more predictable than the human's. Every report carries that
caveat in its footer, and the blind test stays the arbiter.

An optional extra, `copyme[embeddings]`, adds a content-independent style embedding and
reports cosine similarity to the author's centroid. It is a second opinion, not the
score. It stays optional because it is the only part of copyme that downloads a model.

## The evaluation protocol

Run before each release; results recorded in `docs/evals/`.

1. For each golden author, hold out one whole work. Profile the rest at Standard.
2. Generate five passages per author on held-out topics with the target model, using
   the v1 pre-prompt and the v2 pre-prompt.
3. Score every passage. Record `in_band`, copied spans, and embedding similarity if
   the extra is installed.
4. Blind pairwise test: 10 pairs per author (real against v2), 3 or more readers who
   know the author. Record the pick rate. Target 70% or lower.
5. Drift: a 20-turn scripted conversation per author, scored at turns 1, 8, 16 and 20,
   with and without voice-card re-pasting at 8 and 16.

The protocol deliberately uses **whole held-out works and unfamiliar topics**, so that
recalling the sample cannot pass as imitating its style. Running v1 and v2 side by side
in step 2 is what makes the result a comparison rather than a number.

LLM-judge scores may be collected but **do not gate a release**: the research reviewed
found judges favour model text.

## Golden samples

Three public-domain authors with distinct voices, checked into `tests/fixtures/`, each
20,000 words or more. The rules and chosen exemplars for each are snapshotted, so a
change to either is a reviewed diff rather than silent drift.

Proposed authors, all long out of copyright in both the UK and the US:

| Voice | Author | Why |
|---|---|---|
| Spare and plain | Jack London | Short declaratives, concrete nouns, little hedging |
| Ornate | Henry James | Long subordinated sentences, heavy parenthesis |
| Conversational | Mark Twain | First person, idiomatic, fragments and asides |

This selection is a proposal, not a decision; it is confirmed in milestone 4. See
[../specs/04-live-loop-and-evaluation.md](../specs/04-live-loop-and-evaluation.md).

## If the gate fails

The blind test can fail. If it does, what gets revisited is the **selection weights and
the rules renderer**, not the architecture. The four-part profile and the exemplars-over-
descriptions decision rest on published work, not on this project's own numbers; the
weights and phrasings rest on nothing but intuition until the golden-sample tests
report. See [../adr/0001-exemplars-over-descriptions.md](../adr/0001-exemplars-over-descriptions.md).
