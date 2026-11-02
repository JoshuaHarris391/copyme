# copyme

Build a writing-voice profile from a sample of someone's writing, then render it
wherever a voice is needed: a chat, a system prompt, a character card, or your own
application.

## Why

Asking ChatGPT or Claude to "write in my voice" usually fails. The obvious fix is to
describe the voice in numbers, which is what copyme 1.0 did — and it does not work
either, because a model cannot act on `modal_hedging_ratio: 0.04`.

What does work is showing the model the writing. So v2 inverts the prompt:

1. An NLP pass over the sample (spaCy + Empath + textstat), run once.
2. The sample is split into passages, and each is measured. The measurements choose
   which passages to send — the ones typical of the author and unlike generic model
   prose — and turn the author's habits into **rules a model can follow**, with a
   frequency on each.
3. The prompt carries the author's **real passages** and those rules. The numbers stay
   behind the scenes, where they also tell you which habits a generated draft got
   wrong.

The measurements did not go away. They changed job: they select, they phrase, and they
score. They are no longer the payload.

## What the prompt contains

In a fixed order, so an API consumer can cache the stable prefix:

| Section | What it is |
|---|---|
| **Instructions** | Write as this person; take the manner, not the subjects; match how often each habit occurs |
| **Voice rules** | Followable instructions with a frequency on each — *"Keep most sentences between 10 and 26 words… one in ten runs past 35"* |
| **Passages** | The author's own writing, selected and with one-off names masked |
| **Where this usually goes wrong** | Up to three predicted drifts, from the gap between the author and generic prose |
| **Voice card** | Up to five lines to re-paste when a long chat starts to drift |

**No metric dictionary and no JSON.** Both were in the v1 prompt and both are gone from
it. Every number is still available to you, in the UI's collapsed *Raw metrics* section
and in the `json` export.

## What gets measured

| Layer | Examples |
|---|---|
| **The v2 feature set** | Sentence-length quartiles and variation, sentence openers, contraction rate, person and address, questions and exclamations, dashes and ellipses, fragments, paragraph length, opening and closing sentences, capitalisation and emoji, vocabulary range (MATTR), hedging |
| **Quantitative (v1, retained)** | Type-Token Ratio, Mean Sentence Length, Punctuation Density, Discourse Marker Density, Hapax Legomena Ratio, Formulaic Density, Modal Hedging Ratio, Flesch Reading Ease, Function Word Frequency |
| **Qualitative (v1, retained)** | Lexical Sophistication, Syntactic Variety, Cohesive Harmony, Rhetorical Intent, Genre Alignment |
| **Style vocabulary** | The author's connectives and qualifiers, and their repeated idioms — filtered to manner rather than subject, so *"I mean"* survives and *"the quarterly report"* does not |

Three measured features deliberately produce **no rule**: `cohesive_harmony` (no
evidence a model can act on it), `function_word_frequency` (an authorship-attribution
feature with no generation value) and named-entity density (it describes subject
matter, which the prompt explicitly tells the model not to import). All three stay in
the profile.

Definitions of the v1 metrics live in
[`src/copyme/metrics_dictionary.py`](src/copyme/metrics_dictionary.py); the v2 features
are in [`src/copyme/features.py`](src/copyme/features.py). Neither is embedded in a
prompt any more.

## Profile sizes

| Preset | Ceiling | Passages | For |
|---|---|---|---|
| **Compact** | 2,000 tokens | 3–5 | A system-prompt field |
| **Standard** | 8,000 tokens | 8–15 | Pasting into a chat |
| **Full** | 30,000 tokens | 15–30 | Long-context models, Claude Projects |

The token figure is a **ceiling, not a target**: a prompt that overflows the field it
was sized for is a broken prompt, so exemplars are dropped until it fits. Full
typically lands well under its ceiling, because 30 passages capped at 400 tokens each
cannot fill 30,000 tokens.

## How much writing you need

**About 2,000 words gives a recognisable voice; 10,000 or more gives a reliable one.**
Selection needs passages to choose between, and under 2,000 words there are not enough
of them for distinctiveness or diversity to mean much. Below that floor copyme says so,
in the app and in the prompt itself, rather than producing a confident profile from
thin evidence.

## Streamlit app

The primary way to use `copyme` is the Streamlit UI. Paste in a writing sample, click one button, and you get back the raw analysis plus a copyable pre-prompt.

### Prerequisites
- Python `>=3.10,<3.14`
- [Poetry](https://python-poetry.org/) installed

### Setup
From the project root:

```bash
poetry install
```

This installs SpaCy, textstat, Empath, NLTK, Streamlit, and downloads the `en_core_web_sm` SpaCy model.

### Run
```bash
poetry run streamlit run streamlit_app.py
```

Streamlit will open the app at <http://localhost:8501>.

### Use
1. Paste a sample of the author's writing into **Text to analyze**. Aim for 2,000 words
   or more; 10,000 is better.
2. Pick a **Profile size** in the sidebar, and decide whether to **mask one-off names**.
3. Click **Generate linguistic profile**. A status container shows which stage is
   running (**Parsing text with spaCy**, then semantic analysis, metrics, **Choosing
   exemplars**, **Writing voice rules**), a progress bar, and elapsed time.
4. Read **the passages it chose, and why**. Each carries a one-line reason — *"typical
   of the author; semicolons well above generic prose"* — and its three scores. The
   reason is for you and is **never sent to the model**.
5. Read the **voice rules** and, if present, **where this usually goes wrong**.
6. Choose a **format** and copy it. The size indicator reports two token figures, one
   per model family, because the tokenisers differ.
7. Paste it where it is going, and ask the model to write.
8. Paste the result into the **Score a draft** tab to see which habits drifted and
   whether anything was copied outright.

Everything except step 3 re-derives from the cached parse, so changing size, masking or
format is instant.

More UI-specific notes are in [`docs/streamlit_app.md`](docs/streamlit_app.md).

### The Blind test page

A second page in the sidebar runs the blind pairwise test: show a reader a real passage
and a generated one, don't say which is which, and count how often they pick correctly.
It builds the packets, collects ballots and tallies the result.

It exists because **the scorer cannot settle copyme's claim.** Scoring checks whether a
draft hits the 36 measurements copyme itself chose, so grading copyme against them is
circular — it confirms the plumbing, not the voice. Only readers can judge the voice.

Two properties worth knowing before trusting a number out of it:

- **The packet and the answer key are separate files.** What a reader receives contains
  no record of which side is real, nor the shuffle seed that would let them reconstruct
  it. Blindness is structural, not a matter of the reader's discipline.
- **A point estimate under the gate is not a pass.** 30 judgements at a 70% pick rate
  has a 95% interval of roughly 52% to 84%, so the gate is judged on the whole interval
  and a thin run is reported as too thin to call.

A lower pick rate is better: 50% is a coin flip and the ceiling of imitation. The page
supplies everything except the readers, which is why the evaluation is still unrun.

### Text length and the memory budget

SpaCy's parser and NER models need roughly **1 GB of temporary memory per
100,000 characters** of input, so a document's maximum length is a direct
function of how much temporary memory you are willing to allocate. `copyme`
turns that into an explicit, configurable budget:

- The sidebar's **Temporary memory budget (GB)** control shows the resulting
  **Maximum text length** in characters.
- Set the `COPYME_MEMORY_GB` environment variable to change the default budget
  (2 GB → 200,000 characters; deliberately below SpaCy's own 1,000,000-character
  default).
- If the pasted text is longer than the budget allows, the app reports the
  length it needs and tells you which budget to raise it to.

To analyse a 2,253,363-character sample you need a budget of about 23 GB. Be
aware that this is real memory: a document that large needs tens of gigabytes
available at parse time, so prefer trimming the sample or splitting it.

### Vocabulary percentile

The **Keep the most frequent (%)** slider controls how much of the author's
vocabulary is captured. Words and phrases are ranked by frequency and trimmed to
the most frequent share of *distinct terms*, with words and phrases truncated
independently. The default is 20%.

The knob is **proportional, not absolute**: 20% of a short text is a handful of
terms, 20% of a long text is a large one. On a 675-distinct-word corpus, 20%
keeps 135 terms (everything appearing three or more times). At least one term is
always kept, and raising the slider always returns a superset of the lower
setting.

The selection drives both the displayed tables and the vocabulary section of the
pre-prompt, so lowering it produces a shorter, sharper style guide.

### Phrase length

The **Longest phrase (words)** slider sets how long a phrase may be, from 2 to
6 words, defaulting to 4. Phrases are word sequences that repeat: at 2 the
profile captures pairs like *of the*, and at 5 it can capture *in the end of
the*. Longer sequences repeat far less often, so raising the slider mostly
reshuffles the shorter candidates rather than adding long ones.

**Formulaic Density is deliberately not affected.** That metric measures the
proportion of the text made of repeated 2-4 word sequences and is scored against
fixed bands, so letting a slider move it would make two profiles incomparable.
The phrase list is configurable; the metric stays pinned to 2-4 words. The
active length is recorded in `results["limits"]["max_phrase_words"]`, so a
profile can always be reproduced.

## Command line

```bash
copyme profile sample.txt --out profile.json [--size standard] [--budget 5000]
copyme render profile.json --size compact --format system_prompt
copyme score generated.txt --against profile.json [--json]
copyme card profile.json --out author.png          # Character Card V2 PNG
```

`render`, `score` and `card` work entirely from the JSON file — no sample, no re-parse.
**No subcommand needs an API key.** `--contrastive live` is the only path that can use
one, and without a key it falls back to the static tier and says why.

Progress and warnings go to stderr, so `copyme score --json` emits JSON on stdout and
nothing else.

## Programmatic use

```python
from copyme import StyleAnalyser, build_pre_prompt, build_profile, score

sample = open("my_writing.txt").read()

analyser = StyleAnalyser(sample)                      # expensive: runs spaCy once
profile = build_profile(analyser, size="standard")    # cheap: a Profile

print(f"{len(profile.exemplars)} passages, {len(profile.rules)} rules")
for rule in profile.rules:
    print("-", rule.prose)

prompt = build_pre_prompt(profile, format="first_message")

# ...paste `prompt` into a model, then check what came back:
report = score(model_output, against=profile)
print(report.summary)
```

`Profile` is the only thing the exports and the scorer know about. It serialises both
ways, so a profile built once can be re-rendered at any size with no parse:

```python
from copyme import Profile

open("profile.json", "w").write(profile.to_json())

later = Profile.from_json(open("profile.json").read())
compact = build_pre_prompt(later, size="compact", format="voice_card")
```

### Backwards compatibility

`build_profile(analyser)` with no v2 arguments **returns the v1 dictionary, unchanged**,
and `build_pre_prompt` given that dictionary produces the v1 block, metric dictionary
and all. The v1 test suite passes untouched. Opting into v2 is a choice, not a
migration — and a v2 profile still carries the v1 metrics under `profile.metrics`.

```python
from copyme import analyze_linguistic_style, build_pre_prompt

def on_progress(label, percent):
    print(f"{percent:5.1f}%  {label}")

# Optional: raise the temporary-memory budget for very long samples.
# ~1 GB per 100,000 characters; 25 GB -> 2,500,000 characters.
results = analyze_linguistic_style(
    sample, memory_gb=25, on_progress=on_progress, vocabulary_percentile=20
)
pre_prompt = build_pre_prompt(results)   # the v1 block
```

### Export targets

| Target | Shape |
|---|---|
| `first_message` | Markdown, for the first message of a chat |
| `system_prompt` | The same content as standing instructions, no chat framing |
| `voice_card` | Up to five lines, for re-pasting mid-conversation |
| `sillytavern_card` | Character Card V2 JSON (`copyme card` writes the PNG) |
| `json` | The whole profile: features, rules with bands, passages with reasons, provenance |
| `exemplars` / `rules` | Either block alone, for an application that assembles its own prompt |

Every prose export ends with a provenance footer naming the copyme version, the profile
hash, the sample's word count and the baseline version — and naming no path, host or
key.

Parsing is the expensive half of the analysis, so the two halves are exposed
separately. Parse once, then re-derive as often as you like — this is what lets the UI
respond to every slider without re-parsing:

```python
analyzer = StyleAnalyser(sample)                              # expensive: runs SpaCy
profile = build_profile(analyzer, vocabulary_percentile=20)   # cheap (v1 dict)
slimmer = build_profile(analyzer, vocabulary_percentile=5)    # also cheap
longer_phrases = build_profile(analyzer, max_phrase_words=6)  # up to 6-word phrases
v2 = build_profile(analyzer, size="full")                     # cheap (Profile)
```

`analyze_linguistic_style` returns `{"quantitative": {...}, "qualitative": {...}, "words": {...}, "limits": {...}}`.
`limits` reports the analysed `text_length`, the configured `max_length`, and
the `memory_budget_gb` behind it. Passing `vocabulary_percentile=None` restores
the legacy behaviour of the top ten words and phrases.

### Measuring the size

A single token count misleads, because the two major tokenisers genuinely differ, so
`token_estimates` reports both:

```python
from copyme import build_pre_prompt, token_estimates

counts = token_estimates(build_pre_prompt(profile))
# {'gpt': 3689, 'gpt_exact': True, 'claude': 4796, 'claude_exact': False,
#  'multiplier': 1.3}
```

The GPT figure uses `cl100k_base` and is exact when `tiktoken` is installed — accurate
for the GPT-3.5/GPT-4 family. Without it the count is an estimate calibrated against
the same encoding: 99% of the true count for a generated prompt, within roughly 10% for
prose, JSON and source code. (`tiktoken` downloads its merge table on first use, so it
needs network access once.)

**The Claude figure is always an estimate**, computed as the GPT figure times
`CLAUDE_TOKEN_MULTIPLIER` (1.3). Claude Sonnet 5's tokeniser produces roughly 30% more
tokens for the same English text than its predecessor, and there is no offline Claude
tokeniser to measure it with. When one exists, that constant and the code paths using
it should be deleted rather than kept alongside it.

`count_tokens` is still available and unchanged, returning `(count, exact)` for the GPT
family alone.

The helpers behind the budget are public too:

```python
from copyme import (
    configure_memory_budget,   # set nlp.max_length from a budget, returns it
    get_max_length,            # current character limit
    max_length_for_memory,     # budget (GB) -> characters
    memory_for_length,         # characters -> budget (GB)
)

configure_memory_budget(25)        # 2,500,000 characters
max_length_for_memory(25)         # 2_500_000
memory_for_length(2_253_363)      # 22.53
```

If text exceeds the limit, `StyleAnalyser` / `analyze_linguistic_style` raise
`TextTooLongError` (a subclass of `ValueError`) with a message naming the limit,
the budget behind it, and the budget the text would need.

## Status reporting

Long inputs take time — SpaCy parsing dominates — so both `StyleAnalyser` and
`analyze_linguistic_style` accept an optional `on_progress` callback, invoked as
`on_progress(label, percent)` as each stage completes. The percent is monotonic
from 0 to 100 and the labels come from `ANALYSIS_STAGES`:

```python
from copyme import ANALYSIS_STAGES, ProgressReporter

[(key, label) for key, label, _ in ANALYSIS_STAGES]
# [('parse', 'Parsing text with spaCy'), ('extract', 'Extracting tokens and sentences'), ...]
```

`ProgressReporter` is the adapter used internally if you want to map stage keys
to percentages yourself. The callback is never required: omit it and the calls
are no-ops.

## Documentation

[`docs/`](docs/) is the entry point. In short:

| If you want to know | Read |
|---|---|
| What each metric means and how it is scored | [`docs/linguistic_metrics.md`](docs/linguistic_metrics.md) |
| How the Streamlit app behaves | [`docs/streamlit_app.md`](docs/streamlit_app.md) |
| What copyme is for and where it is going | [`docs/product/`](docs/product/) |
| How v2 is specified and built | [`docs/specs/`](docs/specs/) |
| Why the design is the way it is | [`docs/adr/`](docs/adr/) |

## What is measured, and what is not

v2's code is built and tested. Two things about its *evidence* need stating plainly,
because both affect how much weight the output can carry.

**The generic-prose baseline is measured, with a named caveat.** Every rule copyme emits
is a rule the model does not already follow, and the baseline is how "already" is
defined. It is sampled from **1,152 generated passages, 391,398 words** of
`claude-sonnet-5` answering plain questions with no style instruction
(`scripts/generate_baseline_corpus.py`).

21 of 36 feature spreads have converged, including **every feature that drives a
substantive rule** — sentence length and its variation, paragraph length, contraction
rate, conjunction openers, commas, fragments, discourse markers, closing sentences. The
15 that have not are the near-zero-frequency features: emoji at 0.11 per 1,000 words,
exclamations at 0.06, ellipses at 0.16, semicolons at 0.52. Those are rare events whose
spread is set by a few outlier passages, so it stays noisy however large the corpus
gets; suppression on them is robust except for an author sitting right at the threshold.
The per-feature figures are in `baseline.json` under `stability.unstable_features`.

This replaced a hand-written 4,000-word corpus, and the replacement corrected a real
error rather than merely adding precision: the old passages were single paragraphs,
which gave paragraph length a large false salience for every author. The refresh
procedure is [`docs/how-to/refresh-the-baseline.md`](docs/how-to/refresh-the-baseline.md).

**The blind evaluation has not been run.** v2 rests on published work about imitation in
general, not on evidence about copyme in particular. The protocol that would produce
that evidence needs three or more readers per author and is specified in
[`docs/specs/04-live-loop-and-evaluation.md`](docs/specs/04-live-loop-and-evaluation.md);
[`docs/evals/`](docs/evals/) says what is outstanding. Until it runs, these remain
intuitions with defaults attached rather than findings: the 0.4 / 0.4 / 0.2 selection
weights, whether Compact should carry passages at all, the three-occurrence name-masking
threshold, and the twelve-word copying threshold. Each is a parameter, so each can be
measured rather than argued about.

What *is* measured: MATTR replaced type-token ratio on the evidence of a stability test
across sample lengths (at most 5.7% drift against TTR's 46–61%); a text scored against
its own profile is in band on every rule; and the baseline above is sampled from real
model output rather than assumed.

The reasoning behind the design is in
[`docs/product/vision.md`](docs/product/vision.md); progress is in
[`docs/work/LEDGER.md`](docs/work/LEDGER.md).

## A note on provenance

copyme v2 keeps the sample and puts real passages of it into the prompt, so what you
profile matters. Profiling a published author's text for your own use and publishing a
model that imitates them are different positions, in law and in ethics, and copyme does
not resolve that for you. Every export carries a footer naming the sample's size and the
profile hash, and no feature strips a sample of its attribution. See
[`docs/product/non-goals.md`](docs/product/non-goals.md).

## Project layout

```
src/copyme/
  analyser.py            # StyleAnalyser + analyze_linguistic_style + build_profile
  passages.py            # Segmentation into candidate passages
  features.py            # The v2 feature set, per document and per passage
  baseline.py            # The generic-prose baseline: z-scores and distance
  data/baseline.json     # Feature means and spreads. Numbers only, no text
  exemplars.py           # select_exemplars: typicality, distinctiveness, diversity
  rules.py               # Rule + render_rules: measurements -> instructions
  separation.py          # Style/content filters and name masking
  profile.py             # The frozen Profile, the size presets, serialisation
  exports.py             # The five export targets and the two partials
  scorer.py              # Drift, ScoreReport, score
  blind.py               # The blind pairwise test: packets, ballots, the tally
  contrastive.py         # Static and live known-failure notes
  cli.py                 # copyme profile / render / score / card
  metrics_dictionary.py  # v1 metric definitions (profile-only; not prompt content)
  pre_prompt.py          # build_pre_prompt, and the retained v1 renderer
streamlit_app.py         # Streamlit UI
pages/
  1_Blind_test.py        # The blind test: build a packet, rate one, tally
scripts/
  generate_baseline_corpus.py  # Generates the baseline corpus from a model
  build_baseline.py      # Regenerates baseline.json; --verify checks it matches
  fetch_fixtures.py      # Downloads the golden samples, with provenance
.github/workflows/       # Tests on 3.10/3.12/3.13, and the baseline check
tests/fixtures/          # Golden samples, the baseline corpus, the card schema
notebooks/               # Prototype notebooks (prototype.ipynb, prototype_v2.ipynb)
docs/                    # Entry point; see docs/README.md
  product/               # What copyme is for, roadmap, non-goals, integrations
  specs/                 # v2 specs, one per milestone
  adr/                   # Decision records
  how-to/                # Maintenance procedures
  evals/                 # Evaluation runs, and what is outstanding
  work/                  # Ledger and in-flight spec working files
```
