import json
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

load_dotenv()

# --- CONSTANTS ---

DEFAULT_MODEL = "claude-sonnet-4-20250514"

_METRICS_DOC_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "linguistic_metrics.md"

try:
    METRICS_REFERENCE = _METRICS_DOC_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    METRICS_REFERENCE = "(linguistic_metrics.md not found)"


# --- SYSTEM PROMPT BUILDER ---

def build_system_prompt(profile: dict) -> str:
    """
    Construct a system prompt that instructs the LLM to write in the user's
    linguistic style, using the full metric reference and the user's profile.

    Args:
        profile: The output dict from analyze_linguistic_style, containing
                 'quantitative', 'qualitative', and 'words' sections.

    Returns:
        A system prompt string.
    """
    quantitative = profile.get("quantitative", {})
    qualitative = profile.get("qualitative", {})
    words = profile.get("words", {})
    common_vocab = words.get("common_vocabulary", [])
    frequent_phrases = words.get("frequent_phrases", [])

    return f"""You are an AI scribe. Your purpose is to produce writing content that \
faithfully mirrors the linguistic style of the user. Every response you generate \
must sound as though the user themselves wrote it — personalised, natural, and \
uniquely theirs.

To achieve this you have been given:
1. A detailed reference guide explaining every linguistic metric, its calculation \
method, and how to interpret each assessment category.
2. The user's actual linguistic profile — both raw quantitative scores and \
qualitative assessments — so you know *what* their style is and *how strongly* \
each trait manifests.
3. The user's most common vocabulary and frequent phrases, which you must \
naturally weave into your writing.

---

## METRIC REFERENCE GUIDE

Use this to understand what each metric means, how it is calculated, and what \
the assessment categories indicate:

{METRICS_REFERENCE}

---

## USER'S LINGUISTIC PROFILE

### Quantitative Metrics (raw scores — use these to gauge intensity)
{json.dumps(quantitative, indent=2)}

### Qualitative Assessments (categorical interpretations)
{json.dumps(qualitative, indent=2)}

**How to combine quantitative and qualitative data:**
- The qualitative assessment tells you the *direction* of the trait (e.g., \
"conversational", "heavily punctuated", "tentative/hedged").
- The quantitative score tells you *how much* — a score near a threshold means \
mild expression of the trait; a score far past the threshold means strong expression.
- For example, a discourse_marker_density of 78.38 with assessment "conversational" \
(threshold >40) means the user is *very* conversational — almost double the \
threshold — so lean heavily into that style.
- Calibrate every aspect of your writing using this principle.

---

## VOCABULARY & PHRASING DIRECTIVES

### Common Vocabulary (words the user frequently uses — incorporate naturally)
{json.dumps(common_vocab)}

### Frequent Phrases (multi-word expressions the user favours — use where fitting)
{json.dumps(frequent_phrases)}

Weave these words and phrases into your writing where they fit naturally. Do not \
force them in awkwardly — they should feel like the user's natural voice.

---

## WRITING INSTRUCTIONS

1. Study the quantitative metrics and their qualitative assessments together.
2. Match the user's sentence length patterns (mean length + syntactic variety).
3. Match their punctuation habits (density + style).
4. Match their vocabulary richness (TTR + hapax ratio + lexical sophistication).
5. Match their formality level (discourse markers + hedging + reading ease).
6. Match their rhetorical intent and genre alignment.
7. Use their common vocabulary and frequent phrases throughout.
8. Maintain consistency across all responses in the conversation.
9. The content you produce should be helpful, accurate, and responsive to the \
user's request — but always delivered in their distinctive voice."""


# --- PROMPT TEMPLATE ---

def create_prompt_template() -> ChatPromptTemplate:
    """
    Build a ChatPromptTemplate with system context, chat history, and user input.
    """
    return ChatPromptTemplate.from_messages([
        ("system", "{system_prompt}"),
        MessagesPlaceholder("chat_history"),
        ("human", "{user_input}"),
    ])


# --- PIPELINE ---

def create_chain(api_key: str | None = None, model: str = DEFAULT_MODEL):
    """
    Create a LangChain chain (prompt | model) ready to invoke.

    Args:
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
        model: Model identifier. Defaults to claude-sonnet-4-20250514.

    Returns:
        A LangChain Runnable (prompt | llm).
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError(
            "No Anthropic API key provided. Set ANTHROPIC_API_KEY in your "
            "environment or .env file, or pass api_key explicitly."
        )

    llm = ChatAnthropic(model=model, api_key=key, max_tokens=4096)
    prompt = create_prompt_template()
    return prompt | llm


def generate_styled_content(
    profile: dict,
    user_prompt: str,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    chat_history: list | None = None,
) -> str:
    """
    One-shot convenience function: generate content in the user's style.

    Args:
        profile: Linguistic profile dict from analyze_linguistic_style.
        user_prompt: The user's content request.
        api_key: Anthropic API key (optional if set in env).
        model: Model identifier.
        chat_history: Optional list of prior messages for multi-turn context.

    Returns:
        The generated text as a string.
    """
    chain = create_chain(api_key=api_key, model=model)
    system_prompt = build_system_prompt(profile)
    result = chain.invoke({
        "system_prompt": system_prompt,
        "chat_history": chat_history or [],
        "user_input": user_prompt,
    })
    return result.content
