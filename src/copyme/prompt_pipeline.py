import json
import logging
import os
import re
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

load_dotenv()

logger = logging.getLogger("copyme.prompt_pipeline")

# --- CONSTANTS ---

DEFAULT_MODEL = "claude-sonnet-4-20250514"

FALLBACK_MODELS = [
    "claude-sonnet-4-20250514",
    "claude-haiku-35-20241022",
    "claude-opus-4-20250514",
]

_METRICS_DOC_PATH = (
    Path(__file__).resolve().parent.parent.parent / "docs" / "linguistic_metrics.md"
)

try:
    METRICS_REFERENCE = _METRICS_DOC_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    METRICS_REFERENCE = "(linguistic_metrics.md not found)"

# Threshold map: metric_key -> (threshold_value, direction)
# direction "above" means score > threshold triggers the assessment
METRIC_THRESHOLDS = {
    "type_token_ratio": [
        (0.60, "diverse"),
        (0.40, "standard"),
    ],
    "mean_length_of_sentence": [
        (25, "complex/elaborate"),
        (15, "standard"),
    ],
    "punctuation_density": [
        (150, "heavily punctuated"),
        (100, "balanced"),
    ],
    "discourse_marker_density": [
        (40, "conversational"),
        (15, "natural"),
    ],
    "hapax_legomena_ratio": [
        (0.60, "unique/creative"),
        (0.40, "rich"),
    ],
    "formulaic_density": [
        (0.30, "highly formulaic"),
        (0.10, "standard"),
    ],
    "modal_hedging_ratio": [
        (0.20, "tentative/hedged"),
        (0.05, "balanced"),
    ],
    "flesch_reading_ease": [
        (80, "very easy"),
        (60, "easy/standard"),
        (40, "difficult"),
    ],
}

# Prescriptive directive templates keyed by (metric, assessment)
STYLE_DIRECTIVES = {
    "discourse_marker_density": {
        "conversational": (
            "You MUST insert discourse markers (well, actually, so, basically, "
            "you know, I mean, like, right, honestly, anyway) frequently — aim "
            "for at least one every {freq} words. Start sentences with them. "
            "Use them as transitions between ideas. Think out loud."
        ),
        "natural": (
            "Include occasional discourse markers (well, so, actually) to keep "
            "the tone relaxed, roughly one every {freq} words."
        ),
        "formal/polished": (
            "Avoid discourse markers and fillers. Write in a clean, edited style."
        ),
    },
    "modal_hedging_ratio": {
        "tentative/hedged": (
            "You MUST hedge frequently. Use words like 'might', 'could', "
            "'perhaps', 'I think', 'seems like', 'maybe', 'probably', "
            "'I believe', 'it appears' in at least {pct}% of sentences. "
            "Avoid absolute or definitive statements."
        ),
        "balanced": (
            "Use moderate hedging — mix confident statements with occasional "
            "'might', 'could', 'perhaps'."
        ),
        "assertive/direct": (
            "Write with confidence and certainty. Use direct, declarative "
            "statements. Avoid hedging language."
        ),
    },
    "punctuation_density": {
        "heavily punctuated": (
            "Use heavy punctuation — commas, dashes, semicolons, parenthetical "
            "asides. Break clauses frequently. The user's density is {val} per "
            "1000 words (threshold is 150)."
        ),
        "balanced": (
            "Use standard punctuation pacing with natural clause breaks."
        ),
        "sparse": (
            "Use minimal punctuation. Prefer flowing, unbroken sentences."
        ),
    },
    "flesch_reading_ease": {
        "very easy": (
            "Use simple, short words and straightforward sentence structures. "
            "Target a 5th-grade reading level."
        ),
        "easy/standard": (
            "Write at a conversational level — clear, accessible English."
        ),
        "difficult": (
            "Use college-level vocabulary and complex sentence structures with "
            "multiple clauses."
        ),
        "technical": (
            "Use specialized/academic vocabulary, dense sentence structures, "
            "and technical precision."
        ),
    },
    "mean_length_of_sentence": {
        "complex/elaborate": (
            "Write long sentences averaging {val}+ words with multiple clauses, "
            "qualifiers, and embedded ideas."
        ),
        "standard": (
            "Target an average sentence length around {val} words — balanced "
            "mix of short and medium sentences."
        ),
        "short/telegraphic": (
            "Keep sentences short and punchy, averaging under 15 words. "
            "Use fragments where natural."
        ),
    },
    "type_token_ratio": {
        "diverse": (
            "Use rich, varied vocabulary. Avoid repeating the same words. "
            "Introduce synonyms and precise descriptors."
        ),
        "standard": (
            "Use a normal range of vocabulary — some repetition of common "
            "words is fine."
        ),
        "repetitive": (
            "Stick to a small core vocabulary. Repeat key words rather than "
            "reaching for synonyms."
        ),
    },
    "hapax_legomena_ratio": {
        "unique/creative": (
            "Constantly introduce new, one-off words and terms. Be descriptive "
            "and literary. Avoid predictable word choices."
        ),
        "rich": (
            "Use good variety in word choice — engaging but grounded."
        ),
        "basic/repetitive": (
            "Rely on a small set of anchor words. Keep word choice predictable "
            "and familiar."
        ),
    },
    "formulaic_density": {
        "highly formulaic": (
            "Use common collocations, idioms, and repeated phrase patterns "
            "frequently."
        ),
        "standard": (
            "Use some common collocations naturally (e.g., 'in the end', "
            "'at the same time')."
        ),
        "original": (
            "Avoid stock phrases and clichés. Use novel, original phrasing."
        ),
    },
}


# --- HELPERS ---


def list_available_models(api_key: str) -> list[str]:
    """
    Query the Anthropic API for available models.

    Args:
        api_key: Anthropic API key.

    Returns:
        Sorted list of model ID strings, or FALLBACK_MODELS on failure.
    """
    try:
        logger.info("Querying Anthropic API for available models")
        client = anthropic.Anthropic(api_key=api_key)
        response = client.models.list(limit=100)
        model_ids = [m.id for m in response.data]
        if model_ids:
            logger.info("Found %d models", len(model_ids))
            return sorted(model_ids)
        logger.warning("API returned 0 models, using fallback list")
        return FALLBACK_MODELS
    except Exception as exc:
        logger.warning("Failed to fetch models: %s. Using fallback list", exc)
        return FALLBACK_MODELS


def _compute_intensity(score: float, thresholds: list[tuple]) -> tuple[str, float]:
    """
    Determine which assessment category a score falls into and compute
    the intensity multiplier (score / threshold).

    Returns:
        (assessment_label, intensity_multiplier)
    """
    for threshold_val, label in thresholds:
        if score > threshold_val:
            multiplier = round(score / threshold_val, 2) if threshold_val > 0 else 1.0
            return label, multiplier
    # Below all thresholds — return lowest category
    last_label = thresholds[-1][1] if thresholds else "unknown"
    lowest_threshold = thresholds[-1][0] if thresholds else 1
    # For below-threshold, invert: how far below
    if lowest_threshold > 0:
        multiplier = round(score / lowest_threshold, 2)
    else:
        multiplier = 0.0
    # The label for below-all-thresholds
    below_labels = {
        "diverse": "repetitive",
        "standard": "short/telegraphic",
        "balanced": "sparse",
        "conversational": "formal/polished",
        "natural": "formal/polished",
        "unique/creative": "basic/repetitive",
        "rich": "basic/repetitive",
        "highly formulaic": "original",
        "tentative/hedged": "assertive/direct",
        "very easy": "technical",
        "easy/standard": "technical",
        "difficult": "very easy",
    }
    below_label = below_labels.get(last_label, last_label)
    return below_label, multiplier


def _compute_intensity_report(quantitative: dict) -> list[dict]:
    """
    For each metric in the profile, compute intensity multiplier and
    generate a prescriptive directive.

    Returns:
        List of dicts with keys: metric, score, assessment, threshold,
        multiplier, directive
    """
    report = []
    for metric_key, thresholds in METRIC_THRESHOLDS.items():
        score = quantitative.get(metric_key, 0)
        assessment, multiplier = _compute_intensity(score, thresholds)

        # Find the matched threshold value
        matched_threshold = None
        for t_val, t_label in thresholds:
            if assessment == t_label:
                matched_threshold = t_val
                break
        if matched_threshold is None and thresholds:
            matched_threshold = thresholds[-1][0]

        # Build directive from templates
        directive = ""
        metric_directives = STYLE_DIRECTIVES.get(metric_key, {})
        template = metric_directives.get(assessment, "")
        if template:
            # Compute substitution values
            freq = max(1, round(1000 / score)) if score > 0 else 50
            pct = round(min(score * 100, 100)) if score <= 1 else round(score)
            directive = template.format(
                freq=freq, pct=pct, val=score
            )

        report.append({
            "metric": metric_key,
            "score": score,
            "assessment": assessment,
            "threshold": matched_threshold,
            "multiplier": multiplier,
            "directive": directive,
        })
    return report


def _build_intensity_section(report: list[dict]) -> str:
    """Format the intensity report as a prompt section."""
    lines = []
    for entry in report:
        strength = "MILD"
        if entry["multiplier"] >= 2.0:
            strength = "VERY STRONG"
        elif entry["multiplier"] >= 1.5:
            strength = "STRONG"
        elif entry["multiplier"] >= 1.0:
            strength = "MODERATE"

        metric_name = entry["metric"].replace("_", " ").title()
        line = (
            f"- **{metric_name}**: {entry['score']} "
            f"(threshold for '{entry['assessment']}' is {entry['threshold']}) "
            f"→ {entry['multiplier']}× — {strength}"
        )
        if entry["directive"]:
            line += f"\n  DIRECTIVE: {entry['directive']}"
        lines.append(line)
    return "\n".join(lines)


def _build_anti_patterns(qualitative: dict, report: list[dict]) -> str:
    """Generate explicit anti-pattern warnings based on the profile."""
    warnings = []

    dm_assessment = qualitative.get("discourse_marker_density_assessment", "")
    if dm_assessment == "conversational":
        warnings.append(
            "Do NOT write in a polished, formal, or edited academic style. "
            "Do NOT remove filler words or discourse markers. "
            "Do NOT sound like a professional copywriter or journalist."
        )
    elif dm_assessment == "formal/polished":
        warnings.append(
            "Do NOT use conversational fillers like 'well', 'you know', 'like'. "
            "Do NOT write in a casual or chatty tone."
        )

    hedge_assessment = qualitative.get("modal_hedging_ratio_assessment", "")
    if hedge_assessment == "tentative/hedged":
        warnings.append(
            "Do NOT make absolute, definitive, or authoritative statements. "
            "Do NOT sound overly confident or assertive. "
            "Always soften claims with hedging language."
        )
    elif hedge_assessment == "assertive/direct":
        warnings.append(
            "Do NOT hedge or equivocate. Do NOT use 'might', 'perhaps', 'maybe' "
            "unless truly uncertain."
        )

    reading_assessment = qualitative.get("flesch_reading_ease_assessment", "")
    if reading_assessment == "very easy":
        warnings.append(
            "Do NOT use complex vocabulary or long, multi-clause sentences. "
            "Keep it simple and accessible."
        )
    elif reading_assessment in ("difficult", "technical"):
        warnings.append(
            "Do NOT oversimplify. Do NOT 'dumb down' the language. "
            "Maintain intellectual/academic vocabulary."
        )

    genre = qualitative.get("genre_alignment", "")
    if genre == "conversational_speech":
        warnings.append(
            "Do NOT write like a formal document, essay, or report. "
            "Write as if speaking to someone directly."
        )

    if not warnings:
        return ""

    return "## CRITICAL ANTI-PATTERNS — DO NOT DO THESE\n\n" + "\n".join(
        f"- {w}" for w in warnings
    )


def _build_style_exemplar(
    qualitative: dict, common_vocab: list, frequent_phrases: list
) -> str:
    """
    Build a short example paragraph demonstrating the target voice.
    Dynamically constructed from profile traits.
    """
    dm = qualitative.get(
        "discourse_marker_density_assessment", "standard"
    )
    hedge = qualitative.get(
        "modal_hedging_ratio_assessment", "balanced"
    )

    # Pick discourse markers to inject
    markers = []
    if dm == "conversational":
        markers = ["Well", "Actually", "So", "You know", "I mean", "Basically"]
    elif dm == "natural":
        markers = ["So", "Well"]

    # Pick hedging phrases
    hedges = []
    if hedge == "tentative/hedged":
        hedges = [
            "I think", "might be", "could potentially",
            "perhaps", "seems like", "probably",
        ]
    elif hedge == "balanced":
        hedges = ["might", "could"]

    # Use some frequent phrases if available
    phrases_to_use = frequent_phrases[:3] if frequent_phrases else []

    # Construct exemplar
    parts = []
    if markers:
        parts.append(
            f"{markers[0]}, this is how the user's writing voice sounds."
        )
    else:
        parts.append("This is how the user's writing voice sounds.")

    if hedges:
        parts.append(
            f"They {hedges[0]} express ideas with a degree of uncertainty, "
            f"and {hedges[1] if len(hedges) > 1 else 'often'} qualify their "
            f"statements rather than being definitive."
        )

    if markers and len(markers) > 2:
        parts.append(
            f"{markers[2]}, they tend to use markers like "
            f"'{markers[1].lower()}' and '{markers[3].lower()}' "
            f"when transitioning between thoughts."
        )

    if phrases_to_use:
        parts.append(
            f"Phrases like '{phrases_to_use[0]}' "
            + (f"and '{phrases_to_use[1]}' " if len(phrases_to_use) > 1 else "")
            + "appear naturally in their speech."
        )

    return " ".join(parts)


# --- SYSTEM PROMPT BUILDER ---


def build_system_prompt(profile: dict) -> str:
    """
    Construct a system prompt that instructs the LLM to write in the user's
    linguistic style, using intensity-calibrated prescriptive rules.

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

    logger.info("Building system prompt: %d quantitative metrics, %d qualitative assessments",
                len(quantitative), len(qualitative))
    logger.info("Vocabulary: %d common words, %d frequent phrases",
                len(common_vocab), len(frequent_phrases))

    # Compute intensity report
    intensity_report = _compute_intensity_report(quantitative)
    intensity_section = _build_intensity_section(intensity_report)

    for entry in intensity_report:
        logger.debug("  %s: score=%.2f assessment=%s multiplier=%.2fx",
                     entry["metric"], entry["score"],
                     entry["assessment"], entry["multiplier"])

    # Build anti-patterns
    anti_patterns = _build_anti_patterns(qualitative, intensity_report)

    # Build style exemplar
    exemplar = _build_style_exemplar(qualitative, common_vocab, frequent_phrases)

    return f"""You are an AI scribe. Your SOLE PURPOSE is to produce writing that \
sounds EXACTLY like the user wrote it — not polished, not improved, not cleaned up. \
Raw, authentic, in their exact voice. Every response must be indistinguishable from \
the user's own writing.

You have been given the user's measured linguistic profile with precise scores. \
You MUST match every dimension of their style. This is not optional.

---

## METRIC REFERENCE GUIDE

{METRICS_REFERENCE}

---

## USER'S LINGUISTIC PROFILE

### Quantitative Metrics
{json.dumps(quantitative, indent=2)}

### Qualitative Assessments
{json.dumps(qualitative, indent=2)}

---

## INTENSITY-CALIBRATED STYLE ANALYSIS

Each metric below shows the user's score, the threshold that triggered their \
assessment, and the intensity multiplier (how far past the threshold they are). \
A multiplier of 2.0× means they exhibit the trait at TWICE the minimum — lean \
heavily into it.

{intensity_section}

---

## MANDATORY STYLE RULES

These are non-negotiable directives derived from the user's profile. You MUST \
follow every single one:

### Discourse & Formality
{_get_directive(intensity_report, "discourse_marker_density")}

### Hedging & Certainty
{_get_directive(intensity_report, "modal_hedging_ratio")}

### Sentence Structure
{_get_directive(intensity_report, "mean_length_of_sentence")}

### Punctuation
{_get_directive(intensity_report, "punctuation_density")}

### Reading Level
{_get_directive(intensity_report, "flesch_reading_ease")}

### Vocabulary Richness
{_get_directive(intensity_report, "type_token_ratio")}
{_get_directive(intensity_report, "hapax_legomena_ratio")}

### Phrasing Patterns
{_get_directive(intensity_report, "formulaic_density")}

---

## VOCABULARY & PHRASING — MANDATORY

### Words the user uses constantly — YOU MUST use these:
{json.dumps(common_vocab)}

### Phrases the user repeats — YOU MUST incorporate these where they fit:
{json.dumps(frequent_phrases)}

You MUST use at least 3 of the common vocabulary words and at least 2 of the \
frequent phrases per substantial paragraph. These are the user's verbal \
fingerprints.

---

## EXAMPLE OF TARGET VOICE

This is approximately what the user's writing sounds like. Match this register:

"{exemplar}"

---

{anti_patterns}

---

## FINAL INSTRUCTIONS

1. NEVER default to your own polished, formal AI writing style.
2. ALWAYS prioritise the user's measured style over what "sounds good" to you.
3. The intensity multipliers tell you HOW MUCH -- follow them precisely.
4. If the user's style is conversational, your output must be conversational.
5. If the user hedges, you hedge. If they're direct, you're direct.
6. Use their vocabulary and phrases as naturally as they would.
7. The content must still be helpful, accurate, and responsive to the request \
-- but delivered entirely in the user's distinctive voice.
8. ABSOLUTELY NEVER use hyphens (-) or dashes (-- or longer) in your output. \
Not in compound words, not as punctuation, not as list markers, NOWHERE. \
Use commas, semicolons, colons, or rephrase instead. This rule is UNCONDITIONAL."""


def _get_directive(report: list[dict], metric_key: str) -> str:
    """Extract the directive for a specific metric from the intensity report."""
    for entry in report:
        if entry["metric"] == metric_key:
            if entry["directive"]:
                return entry["directive"]
            return f"(Match the '{entry['assessment']}' style for {metric_key})"
    return ""


def _strip_dashes(text: str) -> str:
    """Remove all hyphens and dashes from generated text.

    Handles em-dashes, en-dashes, regular hyphens, and
    multi-hyphen sequences. Collapses any leftover double
    spaces.
    """
    # Em-dash / en-dash surrounded by spaces -> single space
    text = re.sub(r'\s*[\u2014\u2013]+\s*', ' ', text)
    # Spaced hyphens (used as dashes): " - " or " -- "
    text = re.sub(r'\s+-{1,3}\s+', ' ', text)
    # Remaining hyphens (compound words, etc.)
    text = text.replace('-', '')
    # Clean up any double spaces
    text = re.sub(r'  +', ' ', text)
    return text.strip()


# --- REVIEWER PROMPT ---

REVIEWER_SYSTEM_PROMPT = """You are a linguistic style reviewer. Your job is to \
compare a piece of writing against a target linguistic profile and determine if \
the writing faithfully matches the profile.

You will receive:
1. The target linguistic profile (quantitative + qualitative metrics)
2. The writing to evaluate

For each of these key dimensions, assess whether the writing matches:
- Discourse marker density (conversational markers like 'well', 'actually', 'so')
- Modal hedging (tentative language like 'might', 'could', 'perhaps')
- Sentence length and complexity
- Punctuation density
- Reading ease level
- Vocabulary usage (common words and frequent phrases from the profile)

Respond in this EXACT format:
VERDICT: PASS or FAIL
ISSUES:
- [list each specific issue, or "None" if PASS]
REVISION_INSTRUCTIONS:
- [specific instructions for fixing each issue, or "None" if PASS]"""


def build_reviewer_prompt(profile: dict, draft: str) -> str:
    """Build the reviewer prompt with the profile and draft to evaluate."""
    quantitative = profile.get("quantitative", {})
    qualitative = profile.get("qualitative", {})
    words = profile.get("words", {})

    return f"""## TARGET LINGUISTIC PROFILE

### Quantitative
{json.dumps(quantitative, indent=2)}

### Qualitative
{json.dumps(qualitative, indent=2)}

### Target Vocabulary
Common words: {json.dumps(words.get('common_vocabulary', []))}
Frequent phrases: {json.dumps(words.get('frequent_phrases', []))}

---

## WRITING TO EVALUATE

{draft}

---

Evaluate the writing above against the target profile. Be strict — the writing \
must genuinely sound like the person described by the profile."""


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


def create_chain(
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_tokens: int = 4096,
):
    """
    Create a LangChain chain (prompt | model) ready to invoke.

    Args:
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
        model: Model identifier. Defaults to claude-sonnet-4-20250514.
        temperature: Sampling temperature for style variation.
        max_tokens: Maximum tokens in the response.

    Returns:
        A LangChain Runnable (prompt | llm).
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError(
            "No Anthropic API key provided. Set ANTHROPIC_API_KEY in your "
            "environment or .env file, or pass api_key explicitly."
        )

    logger.info(
        "Creating chain: model=%s temperature=%.2f max_tokens=%d",
        model, temperature, max_tokens,
    )
    llm = ChatAnthropic(
        model=model,
        api_key=key,
        max_tokens=max_tokens,
        temperature=temperature,
    )
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
    logger.info("generate_styled_content: prompt length=%d chars", len(user_prompt))
    chain = create_chain(api_key=api_key, model=model)
    system_prompt = build_system_prompt(profile)
    result = chain.invoke({
        "system_prompt": system_prompt,
        "chat_history": chat_history or [],
        "user_input": user_prompt,
    })
    content = _strip_dashes(result.content)
    logger.info("generate_styled_content: response length=%d chars", len(content))
    return content


def generate_with_refinement(
    profile: dict,
    user_prompt: str,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    chat_history: list | None = None,
    max_iterations: int = 3,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> dict:
    """
    Generate styled content with a self-evaluation refinement loop.

    The LLM generates a draft, then a reviewer compares it against the
    linguistic profile. If the reviewer says FAIL, the critique is fed
    back for revision. Repeats up to max_iterations times.

    Args:
        profile: Linguistic profile dict.
        user_prompt: The user's content request.
        api_key: Anthropic API key.
        model: Model identifier.
        chat_history: Prior messages for multi-turn context.
        max_iterations: Maximum refinement passes (default 3).
        temperature: Sampling temperature (default 0.7).
        max_tokens: Maximum tokens per response (default 4096).

    Returns:
        Dict with keys:
            - 'content': final text
            - 'iterations': list of dicts with 'draft', 'verdict', 'critique'
            - 'total_iterations': int
    """
    logger.info(
        "generate_with_refinement: model=%s max_iterations=%d "
        "temperature=%.2f max_tokens=%d",
        model, max_iterations, temperature, max_tokens,
    )
    chain = create_chain(
        api_key=api_key, model=model,
        temperature=temperature, max_tokens=max_tokens,
    )
    reviewer_llm = ChatAnthropic(
        model=model,
        api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
        max_tokens=max_tokens,
        temperature=0.0,
    )

    system_prompt = build_system_prompt(profile)
    iterations = []

    # Initial generation
    logger.info("Generating initial draft...")
    result = chain.invoke({
        "system_prompt": system_prompt,
        "chat_history": chat_history or [],
        "user_input": user_prompt,
    })
    current_draft = _strip_dashes(result.content)
    logger.info("Initial draft: %d chars", len(current_draft))

    for i in range(max_iterations):
        # Review the draft
        logger.info("Refinement iteration %d/%d: reviewing draft...", i + 1, max_iterations)
        review_prompt = build_reviewer_prompt(profile, current_draft)
        review_result = reviewer_llm.invoke([
            SystemMessage(content=REVIEWER_SYSTEM_PROMPT),
            HumanMessage(content=review_prompt),
        ])
        review_text = review_result.content

        # Parse verdict
        verdict = "FAIL"
        if "VERDICT: PASS" in review_text.upper():
            verdict = "PASS"

        logger.info("Refinement iteration %d/%d: verdict=%s", i + 1, max_iterations, verdict)

        iterations.append({
            "draft": current_draft,
            "verdict": verdict,
            "critique": review_text,
        })

        if verdict == "PASS":
            logger.info("Draft passed review on iteration %d", i + 1)
            break

        # If FAIL and not last iteration, revise
        if i < max_iterations - 1:
            revision_prompt = (
                f"Your previous draft was reviewed against the user's linguistic "
                f"profile and FAILED the style check. Here is the critique:\n\n"
                f"{review_text}\n\n"
                f"Please rewrite your response to fix ALL the issues identified. "
                f"Remember to strictly follow the user's linguistic style as "
                f"defined in the system prompt. Here was the original request:\n\n"
                f"{user_prompt}"
            )
            # Build history including the failed draft
            revision_history = list(chat_history or [])
            revision_history.append(HumanMessage(content=user_prompt))
            revision_history.append(AIMessage(content=current_draft))

            logger.info("Revising draft (iteration %d)...", i + 2)
            result = chain.invoke({
                "system_prompt": system_prompt,
                "chat_history": revision_history,
                "user_input": revision_prompt,
            })
            current_draft = _strip_dashes(result.content)
            logger.info("Revised draft: %d chars", len(current_draft))

    logger.info("Refinement complete: %d iteration(s), final verdict=%s",
                len(iterations), iterations[-1]["verdict"] if iterations else "N/A")
    return {
        "content": current_draft,
        "iterations": iterations,
        "total_iterations": len(iterations),
    }
