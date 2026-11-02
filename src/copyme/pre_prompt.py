"""Compose a copy-paste-ready pre-prompt.

``build_pre_prompt`` is the public entry point and takes either shape:

- a :class:`copyme.profile.Profile`, which renders the v2 export targets. The
  rendering itself lives in :mod:`copyme.exports`.
- the v1 result dictionary, which renders the v1 block unchanged, so existing
  callers, notebooks and the v1 tests are unaffected.

The v1 block is kept rather than deprecated because a profile produced by an
older version of copyme should still render. It is no longer what the tool
produces by default: the metric dictionary and the raw JSON it carries are
exactly what v2 removed from the prompt, on the evidence that a model cannot act
on them.
"""

import json

from .metrics_dictionary import LINGUISTIC_STYLE_METRICS, PRE_PROMPT_INSTRUCTION


def build_v1_pre_prompt(results):
    """Compose the v1 Markdown pre-prompt: metric dictionary, metrics, instruction.

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


def build_pre_prompt(profile, size=None, format="first_message", mask_names=None):
    """Render a profile to a pre-prompt.

    Args:
        profile (copyme.profile.Profile | dict): A v2 profile, or a v1 result
            dictionary.
        size (str, optional): ``"compact"``, ``"standard"`` or ``"full"``.
            Ignored for a v1 dictionary.
        format (str): One of :data:`copyme.exports.FORMATS`. Ignored for a v1
            dictionary.
        mask_names (bool, optional): Whether to mask one-off names in the
            exemplars. Defaults to the profile's own setting.

    Returns:
        str: The rendered pre-prompt.
    """
    # Imported here rather than at module scope: exports needs the v1 renderer
    # above for its own compatibility path, and importing both ways at module
    # scope would be a cycle.
    from .exports import build_pre_prompt as render

    return render(profile, size=size, format=format, mask_names=mask_names)
