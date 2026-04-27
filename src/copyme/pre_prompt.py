"""Compose a copy-paste-ready pre-prompt from a linguistic-style analysis result."""

import json

from .metrics_dictionary import LINGUISTIC_STYLE_METRICS, PRE_PROMPT_INSTRUCTION


def build_pre_prompt(results):
    """Compose a Markdown pre-prompt that bundles the metric dictionary, the
    computed metrics for the analysed text, and the closing instruction for the
    downstream LLM.

    Args:
        results: The dict returned by ``analyze_linguistic_style``. Expected keys:
            ``quantitative``, ``qualitative``, ``words``.

    Returns:
        A Markdown-formatted string suitable for pasting into any LLM chat box.
    """
    quantitative = results.get("quantitative", {})
    qualitative = results.get("qualitative", {})
    words = results.get("words", {})

    return (
        "# Author Linguistic Style Profile\n\n"
        "## 1. Metric Dictionary\n"
        "The following dictionary defines every metric reported in section 2. Use "
        "it to interpret the values.\n\n"
        "```json\n"
        f"{json.dumps(LINGUISTIC_STYLE_METRICS, indent=2)}\n"
        "```\n\n"
        "## 2. Computed Metrics for This Author\n\n"
        "### Quantitative\n"
        "```json\n"
        f"{json.dumps(quantitative, indent=2)}\n"
        "```\n\n"
        "### Qualitative\n"
        "```json\n"
        f"{json.dumps(qualitative, indent=2)}\n"
        "```\n\n"
        "### Vocabulary & Phrases\n"
        "```json\n"
        f"{json.dumps(words, indent=2)}\n"
        "```\n\n"
        "## 3. Instructions\n"
        f"{PRE_PROMPT_INSTRUCTION}\n"
    )
