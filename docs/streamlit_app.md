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
1. Paste or type text into the **Text to analyze** input.
2. Click **Generate linguistic profile**.
3. Review the three output sections:
   - **Quantitative Metrics**
   - **Qualitative Assessments**
   - **Words Data**
4. Scroll to **Copyable Pre-Prompt** at the bottom and click the copy icon.

## What you get
The **Copyable Pre-Prompt** bundles three things into a single Markdown block:

1. The full metric **data dictionary** (definitions, data types, typical ranges, allowed values).
2. The **computed metrics** for the text you analysed (quantitative, qualitative, vocabulary).
3. A closing **instruction** telling a downstream LLM to write in the author's voice — matching their lexical diversity, sentence cadence, rhetorical intent, signature phrases, and idiosyncrasies.

Paste the block into ChatGPT / Claude / any LLM as the first message of a chat, then ask it to draft text on your behalf.

## Notes
- The app uses the existing `copyme.analyze_linguistic_style` implementation plus `copyme.build_pre_prompt`.
- If Streamlit is not available in your environment yet, run `poetry install` again.
