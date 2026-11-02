# Evaluation

One file per release, named `<date>-<version>.md`, with the numbers in a table rather
than in prose.

## Status: not yet run

**There is no evaluation file in this folder.** v2's code is built and tested, and its
design rests on published work about imitation in general — not on any evidence about
copyme in particular. That evidence does not exist yet, and nothing in this repository
should be read as implying it does.

The protocol is specified in
[../specs/04-live-loop-and-evaluation.md](../specs/04-live-loop-and-evaluation.md). It
is unrun for one reason: **step 4 needs three or more human readers per author**, and
that cannot be automated or faked. An LLM judge may be collected alongside it; it
decides nothing.

The machinery to run it does now exist — `copyme.blind` and the app's **Blind test**
page — so what is missing is readers, not tooling. A run with fewer than three readers
is reported as indicative rather than as a result, by design.

## What has been measured

These are the checks the test suite asserts, and they are the only quantitative claims
copyme currently makes about itself. They run on every pull request
(`.github/workflows/tests.yml`), on Python 3.10, 3.12 and 3.13.

| Check | Result | Where |
|---|---|---|
| MATTR is stable across sample lengths where type-token ratio is not | At most 5.7% drift between a 2,000 and a 20,000 word slice, against TTR's 46–61%. MTLD drifted up to 36.9% and was not shipped | `tests/test_features.py` |
| A text scored against its own profile is in band on every rule | 1.00 | `tests/test_scorer.py` |
| Every feature is a rate, so doubling a text does not change it | Within 10% on every feature | `tests/test_features.py` |
| The feature set separates the golden voices | Wilde's median sentence is shorter than James's, with more short sentences | `tests/test_features.py` |
| The exported card validates against the Character Card V2 schema | Passes | `tests/test_exports.py` |
| No export exceeds its size ceiling | Passes on both fixtures at all three sizes | `tests/test_exports.py` |
| The baseline is sampled from real model output | 1,152 passages, 391,398 words of `claude-sonnet-5`, no style instruction | `tests/fixtures/baseline_corpus/` |
| Baseline spread convergence | 21 of 36 features inside the 5% tolerance, including **every** feature driving a substantive rule | `scripts/build_baseline.py --check` |
| Remaining unconverged spreads | 15, all near-zero-frequency (emoji 0.11, exclamations 0.06, ellipses 0.16, semicolons 0.52 per 1,000 words) | `baseline.json`, `stability.unstable_features` |
| `baseline.json` still matches the corpus it claims to describe | Passes on 1,152 passages and all 36 features | `scripts/build_baseline.py --verify` |
| A blind-test packet leaks neither the answer key nor the shuffle seed | Passes, asserted on the serialised file a reader receives | `tests/test_blind.py` |
| A pick rate at the gate with too few judgements is not reported as a pass | Passes: 70% from 30 judgements reaches 84%, and is reported as uncallable | `tests/test_blind.py` |

On the last row: those are rare events whose spread is set by a few outlier passages, so
it stays noisy however large the corpus gets. Suppression on them is robust for any
author who is not sitting exactly on the half-standard-deviation threshold, and the
per-feature numbers are recorded so that can be checked rather than assumed.

The honest headline is now the blind test rather than the baseline.

## What is waiting on the protocol

Each of these shipped as a parameter with an intuited default, so each can be measured
rather than argued about. Until the blind test runs, they are intuitions.

| Parameter | Default shipped | Decided by |
|---|---|---|
| Selection weights | 0.4 typicality, 0.4 distinctiveness, 0.2 diversity | Blind pick rate across weight settings |
| Passages in Compact | 3 to 5 | Pick rate for Compact with and without them |
| Name-masking threshold | 3 occurrences | Whether dialogue-heavy samples lose too much |
| Copying threshold | 12 consecutive words | False-positive rate on quotation-heavy authors |

## Running it

**Step 4 is now one button.** The app's **Blind test** page takes the profile JSON,
generates a passage per round against held-out passages, shows the comparisons one at a
time without revealing anything until the run ends, and tallies the result with the
confidence interval the number is meaningless without — see
[../streamlit_app.md](../streamlit_app.md#the-blind-test-page). Generating the held-out
passages used to be done by hand and pasted in, which is what kept this folder empty.

It still does not supply the readers, which is now the only reason this is unrun. The
protocol asks for three or more per author, and each of them runs their own test. A
finished run offers one self-contained result file; dropping those files into **Tally
the results** pools their counts into one pick rate, one interval and one reader count.
That is the file this folder takes, one per run.

Steps 1 to 3 and step 5 remain scriptable but unscripted.

1. For each golden author, hold out one whole work and profile the rest at Standard.
2. Generate five passages per author on held-out topics, with the v1 pre-prompt and the
   v2 pre-prompt, so the result is a comparison rather than a number.
3. Score every passage: `in_band`, copied spans, and embedding similarity if the
   `embeddings` extra is installed.
4. **Blind pairwise test:** 10 pairs per author, real against v2, three or more readers
   who know the author. Record the pick rate.
5. **Drift:** a 20-turn scripted conversation per author, scored at turns 1, 8, 16 and
   20, with and without re-pasting the voice card at turns 8 and 16.

The release gate is an aggregate blind pick rate of **70% or lower** on Standard
profiles. Publishing a failing number is a valid outcome:
[../product/non-goals.md](../product/non-goals.md) already says copyme does not aim to
fool an expert reader, and a number showing how far short it falls is more useful than
silence.

## A caveat about the fixtures

Three of the four golden samples are long-form literary novelists. The inputs copyme
actually receives are mostly conversational — chat logs, notes, persona files — and the
Wilde fixture exists to keep segmentation honest about short turns, not to be
blind-tested. The blind protocol therefore measures imitation of literary prose, which
is **not** the same as measuring the tool's main use. A conversational author with
readers who know them would be a better test; finding one in the public domain is the
obstacle.
