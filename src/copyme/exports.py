"""Render one profile to every place a voice is needed.

A pre-prompt pasted as a first message is one of five destinations. Until the
profile renders to a system prompt, a character card and a machine-readable
object, every other application has to re-implement copyme.

One :class:`copyme.profile.Profile` renders to all of them, and none of the
renderers knows how selection or rule rendering works. That is the boundary
ADR 0004 exists to protect: a sixth target is a function in this file and
nothing else.

The section order inside the prompt formats is fixed -- instruction, rules,
exemplars, known failures, voice card -- so an API consumer can cache the stable
prefix.
"""

import json

from .analyser import count_tokens
from .profile import Profile, resolve_size

# Claude's tokeniser produces roughly this much more than cl100k_base for the
# same English text. The multiplier is named here, reported in the UI caption
# and documented, rather than hidden in a calculation, because it is an estimate
# with a shelf life: when an offline Claude tokeniser exists, this constant and
# the code paths using it should be deleted, not kept alongside it.
CLAUDE_TOKEN_MULTIPLIER = 1.3

FORMATS = (
    "first_message",
    "system_prompt",
    "voice_card",
    "sillytavern_card",
    "json",
    "exemplars",
    "rules",
)

# The formats that render prose for a model to read, as opposed to a machine
# format. Only these get the instruction block and the footer.
_PROSE_FORMATS = ("first_message", "system_prompt")

# Load-bearing, not decorative. Without this sentence a profile of someone's
# work email produces a model that keeps mentioning the quarterly report, and a
# character voice drags the author's circumstances along with it.
SEPARATION_SENTENCE = (
    "The examples show *how* this person writes, not what they know or "
    "believe. Do not import their subjects, names, settings or opinions."
)

# The closing line of the instruction block. Over-performing a quirk is the
# usual failure, so the frequency instruction is stated once, prominently, and
# repeated on the voice card.
FREQUENCY_REMINDER = (
    "Match how often each habit occurs, not merely whether it occurs. "
    "Over-performing a quirk is the usual failure."
)

NO_REPRODUCTION_SENTENCE = (
    "Do not reproduce any phrase of more than a few words from the examples. "
    "Write new sentences in the same manner."
)


class UnknownFormatError(ValueError):
    """Raised for a format that is not one of :data:`FORMATS`."""


def token_estimates(text):
    """Report the size of a text for both major tokenisers.

    A single number misleads. ``cl100k_base`` is exact for the GPT family and
    available offline; Claude's tokeniser is not available offline and produces
    noticeably more tokens for the same text. Reporting one figure as if it
    covered both is how a profile that fits a budget on paper overflows it in
    practice.

    Args:
        text (str): The text to measure.

    Returns:
        dict: ``gpt``, ``claude``, ``gpt_exact`` and ``multiplier``. The Claude
            figure is always an estimate.
    """
    gpt, exact = count_tokens(text)
    return {
        "gpt": gpt,
        "gpt_exact": exact,
        "claude": int(round(gpt * CLAUDE_TOKEN_MULTIPLIER)),
        "claude_exact": False,
        "multiplier": CLAUDE_TOKEN_MULTIPLIER,
    }


def exemplar_text(exemplar, mask_names=True):
    """The text of one exemplar, masked or verbatim.

    Args:
        exemplar (copyme.exemplars.Exemplar): The exemplar.
        mask_names (bool): Whether to use the masked form. Falls back to the
            verbatim text when no masked form was stored, which is the case for
            a profile built before masking existed.

    Returns:
        str: The text.
    """
    if mask_names and exemplar.masked_text:
        return exemplar.masked_text
    return exemplar.text


def _instruction_block(profile, first_message):
    """The opening instruction.

    Args:
        profile (copyme.profile.Profile): The profile.
        first_message (bool): Whether this is the chat-message framing. The
            system-prompt form says the same things as standing instructions,
            with no "you are about to be given" framing, because a system
            prompt is not read at a moment in time.

    Returns:
        str: The block.
    """
    if first_message:
        opening = (
            "You are about to be given a set of voice rules and a number of "
            "passages written by one person. Everything you write from here on "
            "should read as though that person wrote it."
        )
    else:
        opening = (
            "Write as the person whose voice is described below. The rules and "
            "passages that follow define that voice, and they apply to every "
            "response."
        )

    lines = [opening, "", SEPARATION_SENTENCE, "", NO_REPRODUCTION_SENTENCE, "", FREQUENCY_REMINDER]

    if profile.thin:
        lines += [
            "",
            "This profile was built from a short sample, so it describes the "
            "voice loosely. Prefer the passages over the rules where they "
            "disagree.",
        ]
    if profile.provenance.get("entity_check_relaxed"):
        lines += [
            "",
            "This writer keeps to one subject throughout, so the passages carry "
            "more of their subject matter than usual. Take the manner and leave "
            "the subject.",
        ]
    return "\n".join(lines)


def _rules_block(profile):
    """The rules, as a numbered list."""
    if not profile.rules:
        return (
            "This writer's measurable habits sit close to ordinary prose. "
            "Follow the passages."
        )
    return "\n".join(
        f"{index}. {rule.prose}" for index, rule in enumerate(profile.rules, start=1)
    )


def _exemplars_block(profile, mask_names=True, separator="---"):
    """The exemplars, separated and unlabelled.

    The selection reasons are deliberately absent. They exist to tell the user
    why a passage was chosen; telling the model why would have it imitate the
    explanation.
    """
    chunks = []
    for exemplar in profile.exemplars:
        chunks.append(exemplar_text(exemplar, mask_names).strip())
    return f"\n\n{separator}\n\n".join(chunks)


def _known_failures_block(profile, size):
    """The contrastive notes, or None where there are none.

    Compact carries the correction text only. That is not a budget decision: a
    smaller model shown a failed draft sometimes imitates it instead of avoiding
    it, so the draft is withheld at the size most likely to be pasted into one.
    """
    if not profile.known_failures:
        return None
    notes = list(profile.known_failures)
    if size == "compact":
        notes = [note.split("\n\n")[0] for note in notes]
    return "\n\n".join(notes)


def voice_card(profile, max_lines=5):
    """Up to five lines for re-pasting mid-conversation.

    A long chat drifts, and re-pasting the whole profile is expensive and
    disruptive. This is the cheap reminder. It is up to five lines rather than
    exactly five: a profile with three strong rules should not be padded to
    length with weak ones.

    Args:
        profile (copyme.profile.Profile): The profile.
        max_lines (int): The ceiling, including the frequency reminder.

    Returns:
        str: The card.
    """
    lines = []
    for rule in profile.rules[: max_lines - 1]:
        lines.append(f"- {rule.magnitude[0].upper()}{rule.magnitude[1:]}.")
    lines.append(f"- {FREQUENCY_REMINDER}")
    return "\n".join(lines)


def provenance_footer(profile):
    """The footer every prose export carries.

    This is what lets a user tell two profiles apart six months later, and it is
    the mechanism behind the commitment that no feature strips attribution. It
    names no path, no host and no key -- only the model's name, where a model was
    involved at all.

    Args:
        profile (copyme.profile.Profile): The profile.

    Returns:
        str: The footer.
    """
    parts = [
        f"copyme {profile.provenance.get('copyme_version', 'unknown')}",
        f"profile {profile.hash}",
        f"{profile.word_count:,} words of sample",
        f"baseline {profile.provenance.get('baseline_version', '0')}"
        f" ({profile.provenance.get('baseline_status', 'provisional')})",
    ]
    model = profile.provenance.get("contrastive_model")
    if model:
        parts.append(f"drift measured against {model}")
    return "<!-- " + " | ".join(parts) + " -->"


def _fit_to_ceiling(profile, size, render):
    """Drop exemplars until the rendered prompt fits the preset's ceiling.

    A preset's token figure is a ceiling, not a target, and for Compact it is
    the whole point: the size exists to fit a 2,000-token system-prompt field.
    Overflowing it produces a prompt that is silently truncated by whatever it
    was pasted into, which is the worst outcome available -- the user sees a
    complete profile and the model sees half of one.

    Exemplars are dropped from the end of the greedy order, so the passages that
    survive are the ones selection ranked highest. The count may fall below the
    preset's minimum: fitting the field beats carrying one more passage into a
    prompt that will be cut off anyway.

    Args:
        profile (copyme.profile.Profile): The profile to render.
        size (str): The preset name.
        render (callable): Called as ``render(profile)``, returning the text.

    Returns:
        str: The rendered export, within the ceiling where that is achievable.
    """
    from dataclasses import replace

    ceiling = resolve_size(size)["total"]
    exemplars = list(profile.exemplars)

    while True:
        candidate = replace(profile, exemplars=tuple(exemplars))
        rendered = render(candidate)
        # Measured against the Claude estimate, which is the larger of the two:
        # fitting the smaller one would still overflow for half of users.
        if token_estimates(rendered)["claude"] <= ceiling or not exemplars:
            return rendered
        exemplars.pop()


def _prose_export(profile, size, first_message, mask_names):
    """Assemble a prompt-shaped export in the fixed section order."""
    sections = [
        ("Instructions", _instruction_block(profile, first_message)),
        ("Voice rules", _rules_block(profile)),
        ("Passages written by this person", _exemplars_block(profile, mask_names)),
    ]

    failures = _known_failures_block(profile, size)
    if failures:
        sections.append(("Where this usually goes wrong", failures))

    sections.append(("Voice card, for re-pasting later", voice_card(profile)))

    body = "\n\n".join(f"## {title}\n\n{text}" for title, text in sections)
    return f"# Voice profile\n\n{body}\n\n{provenance_footer(profile)}\n"


def sillytavern_card(profile, mask_names=True, name="Voice"):
    """Render a Character Card V2 object.

    No prefill is emitted. Older SillyTavern presets lean on an
    assistant-message prefill to lock register, and Claude Sonnet 4.6 and later
    reject prefill with a 400 error, so the in-voice opening goes inside the
    system text instead.

    Args:
        profile (copyme.profile.Profile): The profile.
        mask_names (bool): Whether to mask one-off names in the examples.
        name (str): The character name.

    Returns:
        dict: A Character Card V2 object, ready to serialise.
    """
    examples = "\n".join(
        f"<START>\n{exemplar_text(exemplar, mask_names).strip()}"
        for exemplar in profile.exemplars
    )
    return {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": name,
            "description": _rules_block(profile),
            "personality": ", ".join(rule.magnitude for rule in profile.rules[:5]),
            "scenario": "",
            "first_mes": "",
            "mes_example": examples,
            "creator_notes": (
                f"{voice_card(profile)}\n\n"
                f"Paste the lines above into the Author's Note field at depth 4. "
                f"That is SillyTavern's own anti-drift mechanism and it is where "
                f"this card expects the voice card to live.\n\n"
                f"{provenance_footer(profile)}"
            ),
            "system_prompt": _instruction_block(profile, first_message=False),
            "post_history_instructions": FREQUENCY_REMINDER,
            "alternate_greetings": [],
            "character_book": None,
            "tags": ["copyme", "voice"],
            "creator": "copyme",
            "character_version": profile.hash,
            "extensions": {
                "copyme": {
                    "profile_hash": profile.hash,
                    "copyme_version": profile.provenance.get("copyme_version"),
                    "baseline_version": profile.provenance.get("baseline_version"),
                    "size": profile.size,
                }
            },
        },
    }


def build_pre_prompt(profile, size=None, format="first_message", mask_names=None):
    """Render a profile to one of the export targets.

    Also accepts the v1 result dictionary, in which case it produces the v1
    block unchanged. Existing callers, notebooks and tests are unaffected.

    Args:
        profile (copyme.profile.Profile | dict): The profile, or a v1 result
            dictionary.
        size (str, optional): ``"compact"``, ``"standard"`` or ``"full"``.
            Defaults to the size the profile was built for. A different size
            re-selects from the stored ranking without re-parsing.
        format (str): One of :data:`FORMATS`.
        mask_names (bool, optional): Whether to mask one-off names. Defaults to
            the profile's own setting.

    Returns:
        str: The rendered export. The ``sillytavern_card`` and ``json`` formats
            return JSON text.

    Raises:
        UnknownFormatError: If ``format`` is not a known target.
    """
    if not isinstance(profile, Profile):
        # v1 compatibility: the old function took the result dictionary.
        from .pre_prompt import build_v1_pre_prompt

        return build_v1_pre_prompt(profile)

    if format not in FORMATS:
        raise UnknownFormatError(
            f"Unknown format {format!r}. Choose one of: {', '.join(FORMATS)}."
        )

    size = (size or profile.size).lower()
    resolve_size(size)
    if size != profile.size:
        profile = profile.at_size(size)

    if mask_names is None:
        mask_names = bool(profile.provenance.get("mask_names", True))

    if format in _PROSE_FORMATS:
        first_message = format == "first_message"
        return _fit_to_ceiling(
            profile,
            size,
            lambda candidate: _prose_export(
                candidate, size, first_message, mask_names
            ),
        )
    if format == "voice_card":
        return voice_card(profile)
    if format == "sillytavern_card":
        return json.dumps(sillytavern_card(profile, mask_names), indent=2)
    if format == "json":
        return profile.to_json()
    if format == "exemplars":
        return _exemplars_block(profile, mask_names)
    return _rules_block(profile)
