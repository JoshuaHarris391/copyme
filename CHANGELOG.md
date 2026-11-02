# Changelog

Notable changes per release. Versions follow [semantic versioning](https://semver.org),
and the entries are grouped the way [Conventional Commits](https://www.conventionalcommits.org)
types already group the history.

## Unreleased

### Added

- **The blind pairwise test, in the app** (`copyme.blind`, `copyme.generate`,
  `pages/1_Blind_test.py`). This is the test that settles copyme's actual claim, which
  the scorer cannot: scoring checks whether a draft hits the 36 measurements copyme
  itself chose, so grading copyme against them is circular.

  The whole run happens in the app. Copy the profile JSON out of the profiler's **For
  the blind test** block without reading it, paste it on the Blind test page, and press
  Generate and start: the app renders the prompt, writes one passage per round, pairs
  each with a real passage, and shows the comparisons one at a time. Previously the
  generated side was produced by hand in a separate chat and pasted back, sixty round
  trips for a full three-author run, which is why `docs/evals/` had never held a run.

  Four properties are deliberate. The real side of every comparison is a passage the
  prompt **left out**, because a model asked to write on the subject of a passage in its
  own instructions is being tested on recall. **Nothing is revealed until the run
  ends**, since feedback per card would teach a reader the imitation's tells and inflate
  the rest of the run. The packet and the answer key are **separate files**, and the
  packet carries neither the answers nor the shuffle seed that would reconstruct them.
  And every result carries a **Wilson confidence interval**, with the release gate
  judged on the whole interval: 30 judgements at a 70% pick rate reaches to roughly 84%,
  so a thin run is reported as too thin to call rather than as a pass.

  Generation reads `COPYME_ANTHROPIC_API_KEY` from the environment — deliberately not
  the SDK's own `ANTHROPIC_API_KEY`, which the CLI still uses: a key set in the shell
  for another tool is not consent for the app to spend it. No key reaches a profile, a
  packet, a result or a log line; the result records the model's name only.

  It supplies everything except the readers, so the evaluation remains unrun.

### Changed

- The Blind test page's **Build a packet** and **Rate a packet** modes are replaced by a
  single **Run a blind test** mode, which generates and judges in one session.
  **Tally the results** is unchanged, and still pools several readers' ballots against
  one packet. Reaching the protocol's three readers now means three people each running
  their own test and the pick rates being pooled across runs, since every run generates
  its own passages.

## 2.0.0

The pre-prompt is inverted. The author's real passages became the payload, and the
measurements moved behind the scenes where they choose exemplars, phrase followable
rules and score what comes back. The metric dictionary and the raw JSON blocks left the
prompt entirely, on the evidence that a model cannot act on them; every number is still
available in the profile and in the app.

This is a major version because the generated prompt is a different artefact and the
Streamlit app's controls changed. The **library API is backwards compatible**:
`build_profile(analyser)` with no v2 arguments still returns the v1 dictionary,
`build_pre_prompt` still renders the v1 block from it, and the original 77 tests pass
unchanged.

### Added

- Passage segmentation, with the hard-wrapped versus chat-shaped newline decision
  (`passages.py`).
- A 36-scalar, length-invariant feature set, per document and per passage
  (`features.py`).
- A generic-prose baseline measured from **1,152 passages, 391,398 words** of
  `claude-sonnet-5` answering plain questions with no style instruction. It is the null
  hypothesis every rule is tested against: a feature within half a standard deviation of
  it produces no rule (`baseline.py`, `data/baseline.json`,
  `scripts/generate_baseline_corpus.py`).
- Exemplar selection on typicality, distinctiveness and diversity, with prefix
  truncation of a fixed ranking so a smaller budget is always a subset of a larger one
  (`exemplars.py`).
- 24 per-feature rule renderers, suppression against the baseline, and bands set from
  the author's own passage-to-passage spread rather than a flat percentage
  (`rules.py`).
- Style/content separation and best-effort name masking (`separation.py`).
- A frozen `Profile` as the single contract, three size presets, and a lossless JSON
  round trip that re-renders at any size with no re-parse (`profile.py`).
- Five export targets and two partials, including a Character Card V2 PNG validated
  against the published schema, provenance footers, and dual GPT/Claude token estimates
  (`exports.py`).
- A scorer reporting per-rule drift and copied spans (`scorer.py`).
- Static and live contrastive known-failure notes, the live tier behind an injected
  model call so tests need no network (`contrastive.py`).
- A CLI: `copyme profile`, `render`, `score`, `card`. No subcommand needs an API key.
- Four golden-sample fixtures from Project Gutenberg, each with provenance.
- CI running the suite on Python 3.10, 3.12 and 3.13, and verifying `baseline.json`
  still matches the corpus it describes.

### Changed

- MATTR replaces type-token ratio, chosen by measurement rather than intuition: at most
  5.7% drift across sample lengths against TTR's 46–61%. MTLD drifted up to 36.9% and is
  kept only so the comparison can be re-run.
- The Streamlit app gained Profile and Score tabs, a size selector, a name-masking
  toggle and a format selector. The vocabulary percentile and phrase-length sliders
  remain, but they now shape only the profile and the metrics on display: neither
  changes the generated prompt, because the word and phrase lists are no longer in it.

### Known limitations

- **The blind evaluation has not been run.** It needs three or more human readers per
  author. Four shipped parameters are therefore defaults rather than findings: the
  0.4/0.4/0.2 selection weights, whether Compact carries passages, the three-occurrence
  masking threshold and the twelve-word copying threshold. See `docs/evals/`.
- **15 of 36 baseline spreads have not converged.** Every feature driving a substantive
  rule has; the rest are near-zero-frequency features whose spread is set by a handful
  of outlier passages. They are named per feature in `baseline.json`.
- Eight places where the specs proved unbuildable as written are recorded in
  `docs/specs/README.md`.

## 1.0.0

Version bump only.

## 0.3.0

- Configurable phrase length.
- A vocabulary percentile slider and a pre-prompt token indicator.
- Bounded spaCy input by a memory budget, and reported analysis progress.

## 0.2.0

- A copyable LLM pre-prompt generated from the style profile.
- A Streamlit UI for profile generation, with documentation.
