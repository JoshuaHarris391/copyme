# Prompt Pipeline: AI Scribe with Linguistic Style Mirroring

This module provides a LangChain-based prompt pipeline that takes a linguistic profile (from `analyze_linguistic_style`) and generates content in the user's unique writing style using Anthropic's Claude.

## Architecture

```
Example Text
     │
     ▼
analyze_linguistic_style()  ──►  Linguistic Profile (dict)
                                       │
                                       ▼
                              build_system_prompt(profile)
                                       │
                                       ▼
                              System Prompt (embeds metric
                              reference + quantitative scores
                              + qualitative assessments
                              + vocabulary/phrases)
                                       │
                                       ▼
                              ChatPromptTemplate
                              ┌─ system: system_prompt
                              ├─ chat_history (multi-turn)
                              └─ human: user_input
                                       │
                                       ▼
                              ChatAnthropic (claude-sonnet-4-20250514)
                                       │
                                       ▼
                              Styled Response
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

The `.env` file is gitignored. Alternatively, enter the key in the Streamlit sidebar.

## Usage

### Programmatic

```python
from copyme import analyze_linguistic_style, generate_styled_content

# 1. Generate a linguistic profile from example text
profile = analyze_linguistic_style("Your example writing goes here...")

# 2. Generate styled content
response = generate_styled_content(
    profile=profile,
    user_prompt="Write a blog post about morning routines",
)
print(response)
```

### With chat history (multi-turn)

```python
from copyme.prompt_pipeline import create_chain, build_system_prompt
from langchain_core.messages import AIMessage, HumanMessage

chain = create_chain(api_key="sk-ant-...")
system_prompt = build_system_prompt(profile)

# First turn
result = chain.invoke({
    "system_prompt": system_prompt,
    "chat_history": [],
    "user_input": "Write a short intro for my blog",
})
print(result.content)

# Second turn with history
history = [
    HumanMessage(content="Write a short intro for my blog"),
    AIMessage(content=result.content),
]
result2 = chain.invoke({
    "system_prompt": system_prompt,
    "chat_history": history,
    "user_input": "Now make it more casual",
})
print(result2.content)
```

### Streamlit App

```bash
poetry run streamlit run streamlit_app.py
```

1. Enter your Anthropic API key in the sidebar (or set it in `.env`).
2. Paste example text that represents your writing style.
3. Click **Generate linguistic profile**.
4. Expand **📊 Linguistic Profile** to inspect the metrics.
5. Use the chat input to request content — the AI scribe will write in your style.

## How the Prompt Works

The system prompt is structured in layers:

1. **Scribe persona** — establishes the AI's role as a style-mirroring writer.
2. **Metric reference** — the full `docs/linguistic_metrics.md` table is embedded so the LLM understands what each metric measures and what the assessment categories mean.
3. **Profile interpretation** — both quantitative scores and qualitative assessments are provided. The LLM is instructed to use the qualitative label for *direction* and the quantitative value for *intensity* (e.g., a score far past a threshold = strong expression of that trait).
4. **Vocabulary directives** — the user's `common_vocabulary` and `frequent_phrases` are injected with instructions to weave them naturally into output.

## Configuration

| Parameter | Default | Description |
|---|---|---|
| `model` | `claude-sonnet-4-20250514` | Anthropic model identifier |
| `api_key` | `ANTHROPIC_API_KEY` env var | API key (env or explicit) |
| `max_tokens` | 4096 | Max output tokens per response |
