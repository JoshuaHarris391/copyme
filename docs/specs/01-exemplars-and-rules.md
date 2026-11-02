# Spec 01 — Exemplars and rules

| | |
|---|---|
| Status | Ready to ground |
| Depends on | Nothing. First v2 milestone |
| Gate | Rule and exemplar snapshots pass on the golden samples |
| Decisions assumed | [ADR 0001](../adr/0001-exemplars-over-descriptions.md), [ADR 0002](../adr/0002-metrics-move-behind-the-scenes.md) |

## Why

The pre-prompt currently carries a metric dictionary, a block of numbers and an
instruction, and throws the sample away. The evidence says the sample is the part that
works and the numbers are the part a model cannot act on. This milestone makes the
pre-prompt carry the author's real passages and a set of followable rules, and moves
the measurements to the three jobs they are good at.

After this milestone the tool is already better even though nothing else in v2 exists:
a user pastes a sample and gets exemplars plus rules instead of JSON.

## Scope

1. Segment a parsed document into candidate passages.
2. Compute a per-passage and per-document feature vector, including the new features
   that carry idiosyncrasy.
3. Select exemplars to a token budget on typicality, distinctiveness and diversity.
4. Render rules from the features, suppressing anything a model already does.
5. Introduce the `Profile` dataclass and the three size presets.
6. Rebuild the pre-prompt around the new section order.
7. Ship a provisional generic-prose baseline (deviation D1) and the golden-sample
   fixtures (deviation D2).
8. Streamlit: two new progress stages, a size radio, exemplars with their reasons, raw
   metrics collapsed.

## Out of scope

- Style/content filtering of the vocabulary list, and name masking — spec 02.
- Any export target other than `first_message` — spec 02.
- `score()`, the Score tab, the CLI — spec 03.
- The live contrastive tier and the blind protocol — spec 04.
- Changes to `StyleAnalyser.__init__`, the memory budget, or the phrase cache. These
  work and are not touched.

## Design

### Segmentation (`passages.py`)

Split on paragraph boundaries taken from the spaCy `Doc`, then merge adjacent
paragraphs until each passage is **120 to 400 tokens**.

- Dialogue blocks and list blocks stay whole, even if that overshoots 400 tokens.
- Passages shorter than **40 tokens** are dropped as candidates but still count
  towards the author's document-level totals, so a sample full of one-line paragraphs
  is not silently re-measured on a subset of itself.
- The final passage may fall below 120 tokens; nothing else may.
- Each passage keeps its character offsets into the original text, so an exemplar can
  be shown with surrounding context in the UI and masked in spec 02 without re-parsing.

### Feature extraction (`features.py`)

Compute every feature below for the whole document and for each passage. All are
per-1,000-words or per-sentence rates **with quartiles**, so the renderer can state a
frequency rather than a mean.

| Feature | How computed | Rule it produces |
|---|---|---|
| Sentence-length distribution | Quartiles and coefficient of variation of tokens per sentence | "Most sentences 7 to 16 words; one in ten past 25". Low variation flags the uniform-rhythm failure |
| Sentence openers | Distribution of the first token's POS, and the top ten literal openers | "One in five opens with *And*, *But* or *So*" |
| Contraction rate | Contractions over eligible auxiliary pairs | "Always contract" / "Never contract" / a rate |
| Person and address | First-person singular, first-person plural and second-person rates | "Addresses the reader as *you* about twice a paragraph" |
| Questions and exclamations | Per 1,000 words | "Asks a question roughly every 200 words; never exclaims" |
| Dashes, ellipses, parentheticals | Per 1,000 words, recording which dash form is used | "An em dash about once a paragraph; no parentheses" |
| Fragments | Sentences with no finite verb, as a rate | "One sentence in eight is a fragment" |
| Paragraph length | Sentences per paragraph, quartiles | "Paragraphs of two or three sentences; never more than five" |
| Openings and closings | First and last sentence of each passage, clustered by opener type | "Opens with a claim, not a framing sentence; ends on a short line" |
| Capitalisation and emoji habits | Lower-case sentence starts, all-caps words, emoji rate | Mostly relevant for chat and social samples |
| Lexical diversity | **MTLD or MATTR**, replacing raw type-token ratio | Same rule as now, but stable across sample lengths |

The nine existing quantitative metrics stay computed and stay in the JSON profile and
the UI. Two change role:

- `formulaic_density` stays **pinned to 2-4 word sequences** as the current README
  insists, so profiles remain comparable. Its *phrases* feed the signature-idiom list,
  but only after spec 02's content filter.
- `cohesive_harmony` is kept as a descriptor and **produces no rule**. The research
  gave no evidence a model can act on it.

`function_word_frequency` leaves the prompt entirely: it is an authorship-attribution
feature with no generation value. It stays in the JSON profile.

### Exemplar selection (`exemplars.py`)

Standardise each feature by its spread across the document's own passages (z-scores),
so no single metric dominates. Then score every candidate passage on three axes.

| Score | Definition | What it buys |
|---|---|---|
| Typicality | Negative Euclidean distance from the author's centroid in feature space | Passages that sound like the author on an average day, not an outlier |
| Distinctiveness | Distance from the generic-prose baseline vector | Passages that show the habits a model would otherwise not have |
| Diversity | Penalty for closeness to passages already selected (greedy, maximal-marginal-relevance style) | Coverage of the author's registers rather than ten near-copies |

`combined = 0.4 * typicality + 0.4 * distinctiveness + 0.2 * diversity`, selected
greedily until the token budget is full. **The weights are starting points and are
exposed as parameters** — see Open questions.

**Content check.** A passage whose named-entity density is above the author's own 75th
percentile is skipped: it is about something specific and will pull the model towards
that subject. Where the author's writing is almost all topical — an essayist on one
subject — the threshold relaxes, and the pre-prompt says so in one line.

**Reasons.** Each chosen exemplar is emitted with a one-line reason, such as "typical;
strong sentence-length variation; the only conversational passage". It is shown in the
UI and kept in the JSON profile. **It is never sent to the model.**

### The rules renderer (`rules.py`)

```python
@dataclass(frozen=True)
class Rule:
    feature: str          # "sentence_length"
    direction: str        # "shorter" | "longer" | "more" | "fewer" | "never" | "always"
    magnitude: str        # "about 11 words" | "roughly once a paragraph"
    comparison: str       # "a third are under six words"
    prose: str            # the sentence sent to the model
    band: tuple[float, float]  # accept range for the scorer
```

One record per rule, so the same data renders as prose, as a voice-card line, or as a
scorer threshold without being restated.

**A feature within half a standard deviation of the baseline produces no rule.** The
model's default is already right, and every extra line dilutes the ones that matter.

Rendering principles, in priority order:

1. **Behaviour, not metric names.** "Hedge rarely: when something is uncertain, say so
   once and move on", never `modal_hedging_ratio: 0.04`.
2. **A frequency on every rule.** "Open about one sentence in five with *And* or
   *But*", never "opens sentences with conjunctions". The instruction block closes
   with: *match how often each habit occurs, not merely whether it occurs;
   over-performing a quirk is the usual failure.*
3. **Distribution over mean where it matters.** Sentence length renders from quartiles
   — "most sentences 7 to 16 words; one in ten runs past 25" — because a flat mean
   produces the uniform rhythm readers identify as machine-written.
4. **Negative rules are allowed and short.** "No semicolons." "Never *In conclusion*."
   These come from features at or near zero in the author and well above zero in the
   baseline.
5. **Register descriptors stay categorical, but grounded.** Not "conversational" but
   "conversational: 54 discourse markers per 1,000 words, roughly one per sentence".
   The bare adjective is the part the research found weak.

### The profile and the presets (`profile.py`)

`Profile` is a frozen dataclass holding features, rules, exemplars with their reasons,
known failures, the size presets' budgets, and provenance. It serialises to the `json`
export and back, so a profile built once can be re-rendered at any size without
re-parsing.

| Preset | Total budget | Exemplar block budget | Exemplars |
|---|---|---|---|
| Compact | about 2k tokens | about 1,200 | 3 to 5 short |
| Standard | about 8k tokens | about 5,000 | 10 to 15 |
| Full | up to 30k tokens | about 20,000 | 20 to 30 |

### The pre-prompt

Fixed section order, so the stable part can be cached by API consumers:

```
1. instruction
2. rules
3. exemplars
4. known failures      (empty until spec 03)
5. voice card
```

**Dropped from the prompt**, all retained in the JSON profile and the UI: the metric
dictionary, the raw JSON blocks, `function_word_frequency`, and the categorical
assessments as a standalone section.

### Backwards compatibility

`build_profile(analyzer, vocabulary_percentile=..., max_phrase_words=...)` called with
only its current arguments **keeps returning the current dict shape**, so
`analyze_linguistic_style`, the notebooks and `tests/test_vocabulary.py` do not break.
The new behaviour is reached by passing `exemplar_budget`.

## Public API

```python
from copyme import (
    StyleAnalyser, build_profile, build_pre_prompt,   # existing
    Profile, Rule, select_exemplars, render_rules,    # new
)

profile: Profile = build_profile(
    analyser,
    vocabulary_percentile=20,
    exemplar_budget=5_000,        # tokens; None -> preset "standard"
)

text = build_pre_prompt(profile, size="standard", format="first_message")
```

```python
select_exemplars(
    analyser,
    budget_tokens: int,
    min_n: int = 3,
    max_n: int = 30,
    weights: tuple[float, float, float] = (0.4, 0.4, 0.2),
) -> list[Exemplar]

render_rules(profile) -> list[Rule]
```

## Acceptance criteria

Segmentation

- [ ] Every passage is 120 to 400 tokens, except the last, which may be shorter.
- [ ] No passage splits a paragraph.
- [ ] Dialogue blocks and list blocks stay whole.
- [ ] Passages under 40 tokens are not candidates but still count in document totals.

Selection

- [ ] Raising the budget returns a superset of the lower budget's selection, mirroring
      the existing vocabulary-percentile invariant.
- [ ] The content check never selects a passage above the author's named-entity
      threshold, except under the documented relaxation, which sets a flag on the
      profile.
- [ ] A weight of zero disables its axis.
- [ ] Every selected exemplar carries a non-empty reason, and no reason appears in any
      rendered prompt.

Rules

- [ ] A feature within half a standard deviation of the baseline yields no rule.
- [ ] Every emitted rule has a non-empty `magnitude` and a non-empty `prose`.
- [ ] Rendering is deterministic for a fixed profile: two calls produce identical
      output, including order.
- [ ] `cohesive_harmony` produces no rule.

Features

- [ ] MTLD on a 2,000-word slice and a 20,000-word slice of the same golden author
      agree within 10%, where raw type-token ratio does not.
- [ ] Every new feature exposes quartiles, not only a mean.

Pre-prompt

- [ ] The generated pre-prompt contains no metric dictionary and no raw JSON block.
- [ ] Sections appear in the fixed order, with the known-failures section present but
      empty.
- [ ] Each preset's output is within 15% of its stated token budget on the golden
      samples.

Compatibility

- [ ] `build_profile(analyser)` with no new arguments returns the v1 dict shape, and
      the existing test suite passes unchanged.

## Verification

```bash
poetry run python3 -m pytest -q
poetry run python3 -m pytest tests/test_passages.py tests/test_exemplars.py tests/test_rules.py -q
poetry run streamlit run streamlit_app.py   # manual: paste a golden sample, check exemplars and reasons render
```

## Docs to update

In the same commits as the code:

- `README.md` — what the pre-prompt now contains; the 2,000-word floor; the preset
  table. The metric-dictionary description must go.
- `docs/streamlit_app.md` — the two new progress stages, the size radio, the collapsed
  metrics section.
- `docs/linguistic_metrics.md` — add the new features; mark `function_word_frequency`
  and `cohesive_harmony` as profile-only.
- `docs/adr/0002-metrics-move-behind-the-scenes.md` — set status to Accepted when the
  pre-prompt change lands.

## Open questions

| Question | Decided by |
|---|---|
| Are the 0.4 / 0.4 / 0.2 selection weights right? | The golden-sample blind tests in spec 04, not intuition |
| Should Compact include any exemplar at all, or only rules and the voice card? | Measurement in spec 04. The research favours even three short exemplars, so Compact ships with 3 to 5 until shown otherwise |
| MTLD or MATTR? | Whichever is more stable on the three golden samples. Pick one, record it, do not ship both |
| Is the 120-to-400-token passage window right for chat-style samples, where paragraphs are one line? | Flagged during grounding against a real chat export; the 40-token floor may need to drop |

## Assumption on record

The provisional `baseline.json` shipped in this milestone is hand-built from a modest
sample of assistant-style output and is **good enough to suppress rules and rank
distinctiveness, not good enough to publish numbers from**. Spec 03 replaces it with a
scripted, documented regeneration. Any rule phrasing tuned against the provisional
baseline must be re-checked when it is replaced.
