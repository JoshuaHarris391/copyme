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

## Notes
- The app uses the existing `copyme.analyze_linguistic_style` implementation.
- If Streamlit is not available in your environment yet, run `poetry install` again.
