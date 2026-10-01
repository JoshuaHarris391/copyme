# Streamlit App: Linguistic Profile Generator

This app provides a simple UI for running `analyze_linguistic_style` on arbitrary input text.

## Prerequisites
- Python `>=3.10,<3.14`
- Poetry installed

## Setup
From the project root:

```bash
poetry install
```

## Run the app
From the project root:

```bash
poetry run streamlit run streamlit_app.py
```

## Use the app
1. Optionally set the **Temporary memory budget (GB)** in the sidebar. The sidebar shows the resulting **Maximum text length** in characters and the length of the current input.
2. Paste or type text into the **Text to analyze** input.
3. Click **Generate linguistic profile**.
4. Review the three output sections:
   - **Quantitative Metrics**
   - **Qualitative Assessments**
   - **Words Data**
5. Scroll to **Copyable Pre-Prompt** at the bottom and click the copy icon.

## Status indicator
While the analysis runs, the app shows a status container that reports the current stage, a progress bar, and the elapsed time. Stages are reported by the analyser through the same `on_progress` callback the library exposes, so the UI and any notebook or script see identical progress values. When the run finishes the container collapses to *Analysis complete in Ns*; if the input is rejected for being too long it turns into an error state instead.

## Text length and the memory budget
SpaCy's parser and NER models need roughly 1 GB of temporary memory per 100,000 characters, so the memory budget determines how long an input can be. The default is 2 GB (200,000 characters) — deliberately below SpaCy's own 1,000,000-character default, since even that can ask for a lot of memory. Override it with the `COPYME_MEMORY_GB` environment variable or the sidebar control.

If the input is longer than the budget allows, the app reports the length it needs and the budget to raise it to instead of failing inside SpaCy. The same values are returned in the analysis result's `limits` section (`text_length`, `max_length`, `memory_budget_gb`).

## What you get
The **Copyable Pre-Prompt** bundles three things into a single Markdown block:

1. The full metric **data dictionary** (definitions, data types, typical ranges, allowed values).
2. The **computed metrics** for the text you analysed (quantitative, qualitative, vocabulary).
3. A closing **instruction** telling a downstream LLM to write in the author's voice — matching their lexical diversity, sentence cadence, rhetorical intent, signature phrases, and idiosyncrasies.

Paste the block into ChatGPT / Claude / any LLM as the first message of a chat, then ask it to draft text on your behalf.

## Notes
- The app uses the existing `copyme.analyze_linguistic_style` implementation plus `copyme.build_pre_prompt`.
- If Streamlit is not available in your environment yet, run `poetry install` again.
