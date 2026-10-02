# copyme

Tools for generating a linguistic style profile from a sample of someone's writing, then turning that profile into a copy-paste-ready pre-prompt that an LLM can use to write in their voice.

## Why

Asking ChatGPT or Claude to "write in my voice" usually fails — the model has no measurable description of what your voice actually is. `copyme` solves that by:

1. Running an NLP pass over a sample of the author's writing (SpaCy + Empath + textstat).
2. Computing a structured profile of their linguistic fingerprint: lexical diversity, sentence cadence, punctuation density, hedging, rhetorical intent, signature phrases, and more.
3. Bundling the metric **definitions** + the author's **computed values** + an **instruction** into a single Markdown block you can paste straight into any LLM as the first message of a chat.

The output is intentionally LLM-readable rather than human-readable — the goal is to give a downstream model enough structured context to mimic the author's style consistently.

## What gets profiled

| Layer | Examples |
|---|---|
| **Quantitative** | Type-Token Ratio, Mean Sentence Length, Punctuation Density, Discourse Marker Density, Hapax Legomena Ratio, Formulaic Density, Modal Hedging Ratio, Flesch Reading Ease, Function Word Frequency |
| **Qualitative** | Lexical Sophistication, Syntactic Variety, Cohesive Harmony, Rhetorical Intent, Genre Alignment, plus a categorical assessment for every quantitative metric |
| **Vocabulary** | Top 10 most-used words, top 10 repeated 2-4 word phrases (signature collocations) |

Full definitions live in [`src/copyme/metrics_dictionary.py`](src/copyme/metrics_dictionary.py) and are also embedded inside every generated pre-prompt.

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
1. Paste a sample of the author's writing into **Text to analyze** (a few paragraphs is enough; longer is better).
2. Click **Generate linguistic profile**. A status container shows which stage is running (**Parsing text with spaCy**, then semantic analysis, metrics, and so on), a progress bar, and elapsed time; it collapses to *Analysis complete in Ns* when done.
3. Inspect the three raw sections (**Quantitative**, **Qualitative**, **Vocabulary & Phrases**).
4. Adjust **Keep the most frequent (%)** and **Longest phrase (words)** in the sidebar to control how much vocabulary is captured (see below). Both re-derive from the cached parse, so they update instantly rather than re-parsing the text.
5. Scroll to **Copyable Pre-Prompt**. A size indicator reports its character and token count, so you can check it fits the model's context window before pasting. Click the copy icon in the top-right of the block, and paste it as the first message of a fresh ChatGPT / Claude / Gemini chat.
6. Then ask the LLM to write whatever you need — it will use the profile as a target style guide.

More UI-specific notes are in [`docs/streamlit_app.md`](docs/streamlit_app.md).

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

## Programmatic use

```python
from copyme import StyleAnalyser, analyze_linguistic_style, build_pre_prompt, build_profile

sample = open("my_writing.txt").read()


def on_progress(label, percent):
    print(f"{percent:5.1f}%  {label}")

# Optional: raise the temporary-memory budget for very long samples.
# ~1 GB per 100,000 characters; 25 GB -> 2,500,000 characters.
results = analyze_linguistic_style(
    sample, memory_gb=25, on_progress=on_progress, vocabulary_percentile=20
)
pre_prompt = build_pre_prompt(results)
print(pre_prompt)
```

Parsing is the expensive half of the analysis, so the two halves are exposed
separately. Parse once, then re-derive the profile as often as you like — this is
what lets the UI respond to the vocabulary slider without re-parsing:

```python
analyzer = StyleAnalyser(sample)          # expensive: runs SpaCy
profile = build_profile(analyzer, vocabulary_percentile=20)   # cheap
slimmer = build_profile(analyzer, vocabulary_percentile=5)    # also cheap
longer_phrases = build_profile(analyzer, max_phrase_words=6)  # up to 6-word phrases
```

`analyze_linguistic_style` returns `{"quantitative": {...}, "qualitative": {...}, "words": {...}, "limits": {...}}`.
`limits` reports the analysed `text_length`, the configured `max_length`, and
the `memory_budget_gb` behind it. Passing `vocabulary_percentile=None` restores
the legacy behaviour of the top ten words and phrases. `build_pre_prompt`
composes the Markdown block (dictionary + metrics + instructions) ready to paste
into an LLM.

To check that the pre-prompt fits a context window, measure it with
`count_tokens`, which returns the count and whether it is exact:

```python
from copyme import build_pre_prompt, count_tokens

pre_prompt = build_pre_prompt(results)
tokens, exact = count_tokens(pre_prompt)
print(f"{tokens:,} tokens" + ("" if exact else " (estimated)"))
```

If `tiktoken` is installed, `count_tokens` uses its `cl100k_base` encoding and
returns an exact count — accurate for the GPT-3.5/GPT-4 family and a close guide
for other vendors. Without it (the default, no extra dependency and no network
access) the count is an estimate calibrated against `cl100k_base`: 99% of the
true count for a generated pre-prompt, and within roughly 10% for prose, JSON
and source code. Note that `tiktoken` downloads its merge table on first use, so
it needs network access once.

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

## Project layout

```
src/copyme/
  analyser.py            # StyleAnalyser + analyze_linguistic_style
  metrics_dictionary.py  # Definitions for every metric + the LLM instruction
  pre_prompt.py          # build_pre_prompt(results) -> Markdown string
streamlit_app.py         # Streamlit UI
notebooks/               # Prototype notebooks (prototype.ipynb, prototype_v2.ipynb)
docs/                    # User-facing docs
```
