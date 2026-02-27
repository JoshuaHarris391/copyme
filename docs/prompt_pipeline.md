# Prompt Pipeline: AI Scribe with Linguistic Style Mirroring

This module provides a LangChain-based prompt pipeline that takes a linguistic
profile (from `analyze_linguistic_style`) and generates content in the user's
unique writing style using Anthropic's Claude. It includes intensity-calibrated
prescriptive rules, a self-evaluation refinement loop, and dynamic model
selection.

## Architecture

```
Example Text
     │
     ▼
analyze_linguistic_style()  ──►  Linguistic Profile (dict)
                                       │
                                       ▼
                              build_system_prompt(profile)
                              ┌─ Intensity-calibrated analysis
                              ├─ Mandatory style rules
                              ├─ Style exemplar
                              ├─ Anti-pattern warnings
                              └─ Vocabulary mandates
                                       │
                                       ▼
                              ChatPromptTemplate
                              ┌─ system: system_prompt
                              ├─ chat_history (multi-turn)
                              └─ human: user_input
                                       │
                                       ▼
                              ChatAnthropic (configurable model)
                                       │
                                       ▼
                              generate_with_refinement()
                              ┌─ Generate draft
                              ├─ Reviewer compares to profile
                              ├─ If FAIL → revise (max 3×)
                              └─ Return final draft + iterations
```

## Setup

### 1. Install dependencies

```bash
poetry install
```

### 2. Set your Anthropic API key

Copy the example env file and add your key:

```bash
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

The `.env` file is gitignored. Alternatively, enter the key in the Streamlit
sidebar.

## Usage

### Programmatic (one-shot)

```python
from copyme import analyze_linguistic_style, generate_styled_content

profile = analyze_linguistic_style("Your example writing goes here...")

response = generate_styled_content(
    profile=profile,
    user_prompt="Write a blog post about morning routines",
)
print(response)
```

### With refinement loop (recommended)

```python
from copyme import analyze_linguistic_style, generate_with_refinement

profile = analyze_linguistic_style("Your example writing goes here...")

result = generate_with_refinement(
    profile=profile,
    user_prompt="Write a blog post about morning routines",
    max_iterations=3,
)
print(result["content"])
print(f"Refinement iterations: {result['total_iterations']}")
for it in result["iterations"]:
    print(f"  Verdict: {it['verdict']}")
```

### Dynamic model selection

```python
from copyme import list_available_models

models = list_available_models(api_key="sk-ant-...")
print(models)  # sorted list of available model IDs
```

### With chat history (multi-turn)

```python
from copyme.prompt_pipeline import create_chain, build_system_prompt
from langchain_core.messages import AIMessage, HumanMessage

chain = create_chain(
    api_key="sk-ant-...",
    model="claude-sonnet-4-20250514",
    temperature=0.7,
    top_p=0.9,
)
system_prompt = build_system_prompt(profile)

result = chain.invoke({
    "system_prompt": system_prompt,
    "chat_history": [],
    "user_input": "Write a short intro for my blog",
})
print(result.content)
```

### Streamlit App

```bash
poetry run streamlit run streamlit_app.py
```

1. Enter your Anthropic API key in the sidebar (or set it in `.env`).
2. Select a model from the dropdown (dynamically populated from the API).
3. Paste example text that represents your writing style.
4. Click **Generate linguistic profile**.
5. Expand **📊 Linguistic Profile** to inspect the metrics.
6. Use the chat input to request content — the AI scribe will write in your
   style, with automatic refinement against the profile.
7. Expand **🔄 Refinement** to see iteration details and reviewer verdicts.

## How the Prompt Works

The system prompt is structured in layers:

1. **Scribe persona** — establishes the AI's role as a raw, authentic
   style-mirroring writer.
2. **Metric reference** — the full `docs/linguistic_metrics.md` is embedded.
3. **Intensity-calibrated analysis** — for each metric, the score/threshold
   ratio is computed as a multiplier (e.g., 2.0× means twice the minimum
   threshold). Prescriptive directives are generated per-metric.
4. **Mandatory style rules** — concrete DO directives for discourse markers,
   hedging, sentence structure, punctuation, reading level, vocabulary, and
   phrasing patterns.
5. **Style exemplar** — a dynamically constructed example paragraph
   demonstrating the target voice.
6. **Anti-pattern warnings** — explicit "Do NOT" rules that prevent the LLM
   from falling back to its default polished style.
7. **Vocabulary mandates** — the user's common vocabulary and frequent phrases
   with minimum usage requirements.

### Self-evaluation refinement loop

After initial generation, a separate reviewer prompt compares the output
against the linguistic profile across all key dimensions. If the verdict is
FAIL, the critique is fed back to the writer chain for revision. This repeats
up to 3 times (configurable).

## Configuration

| Parameter | Default | Description |
|---|---|---|
| `model` | `claude-sonnet-4-20250514` | Anthropic model identifier |
| `api_key` | `ANTHROPIC_API_KEY` env var | API key (env or explicit) |
| `max_tokens` | 4096 | Max output tokens per response |
| `temperature` | 0.7 | Sampling temperature for style variation |
| `max_iterations` | 3 | Max refinement loop passes |
