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
2. Click **Generate linguistic profile**.
3. Inspect the three raw sections (**Quantitative**, **Qualitative**, **Words**).
4. Scroll to **Copyable Pre-Prompt**, click the copy icon in the top-right of the block, and paste it as the first message of a fresh ChatGPT / Claude / Gemini chat.
5. Then ask the LLM to write whatever you need — it will use the profile as a target style guide.

More UI-specific notes are in [`docs/streamlit_app.md`](docs/streamlit_app.md).

## Programmatic use

```python
from copyme import analyze_linguistic_style, build_pre_prompt

sample = open("my_writing.txt").read()
results = analyze_linguistic_style(sample)
pre_prompt = build_pre_prompt(results)
print(pre_prompt)
```

`analyze_linguistic_style` returns `{"quantitative": {...}, "qualitative": {...}, "words": {...}}`. `build_pre_prompt` composes the Markdown block (dictionary + metrics + instructions) ready to paste into an LLM.

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
