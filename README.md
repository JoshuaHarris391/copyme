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
3. Inspect the three raw sections (**Quantitative**, **Qualitative**, **Words**).
4. Scroll to **Copyable Pre-Prompt**, click the copy icon in the top-right of the block, and paste it as the first message of a fresh ChatGPT / Claude / Gemini chat.
5. Then ask the LLM to write whatever you need — it will use the profile as a target style guide.

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

## Programmatic use

```python
from copyme import analyze_linguistic_style, build_pre_prompt

sample = open("my_writing.txt").read()


def on_progress(label, percent):
    print(f"{percent:5.1f}%  {label}")

# Optional: raise the temporary-memory budget for very long samples.
# ~1 GB per 100,000 characters; 25 GB -> 2,500,000 characters.
results = analyze_linguistic_style(sample, memory_gb=25, on_progress=on_progress)
pre_prompt = build_pre_prompt(results)
print(pre_prompt)
```

`analyze_linguistic_style` returns `{"quantitative": {...}, "qualitative": {...}, "words": {...}, "limits": {...}}`.
`limits` reports the analysed `text_length`, the configured `max_length`, and
the `memory_budget_gb` behind it. `build_pre_prompt` composes the Markdown block
(dictionary + metrics + instructions) ready to paste into an LLM.

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
