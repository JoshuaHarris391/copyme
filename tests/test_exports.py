"""The export targets: one profile rendered everywhere a voice is needed.

Five targets plus two partials, all from the same :class:`Profile`. The tests
here fall into three groups: the prompt formats carry the right content in the
right order, the machine formats validate against what consumes them, and
nothing anywhere leaks a path, a key or the selection reasoning.
"""

import json
from pathlib import Path

import jsonschema
import pytest

from copyme.exports import (
    CLAUDE_TOKEN_MULTIPLIER,
    FORMATS,
    FREQUENCY_REMINDER,
    UnknownFormatError,
    build_pre_prompt,
    sillytavern_card,
    token_estimates,
    voice_card,
)

CARD_SCHEMA = json.loads(
    (Path(__file__).parent / "fixtures" / "character_card_v2.schema.json").read_text()
)


def test_every_format_renders_something(london_profile):
    """A target that silently returns nothing is worse than one that raises.

    The format list is offered to the user in a dropdown, so each entry has to
    produce usable output for any profile, not only for the ones it was
    developed against.
    """
    for export_format in FORMATS:
        rendered = build_pre_prompt(london_profile, format=export_format)
        assert rendered.strip(), f"{export_format} rendered nothing"


def test_an_unknown_format_raises_rather_than_guessing(london_profile):
    """A typo in a format name must not quietly return the default.

    The CLI and the UI both pass this through from user input. Falling back to
    ``first_message`` would hand someone a chat prompt when they asked for a
    character card, and they would only find out after pasting it.
    """
    with pytest.raises(UnknownFormatError) as error:
        build_pre_prompt(london_profile, format="system-prompt")

    assert "system_prompt" in str(error.value), "the error should list the real names"


def test_the_prompt_carries_no_metric_dictionary_and_no_raw_json(london_profile):
    """This is the change v2 exists to make.

    v1 sent a dictionary defining every metric, then the metrics themselves as
    JSON. The evidence says the sample is the part that works and the numbers
    are the part a model cannot act on, so both blocks are gone from the prompt
    and kept in the profile for the user.
    """
    for export_format in ("first_message", "system_prompt"):
        rendered = build_pre_prompt(london_profile, format=export_format)
        assert "Metric Dictionary" not in rendered
        assert "```json" not in rendered
        assert "type_token_ratio" not in rendered


def test_the_prompt_contains_the_author_s_own_passages(london_profile):
    """The payload is the author's writing. Without it there is no v2.

    An export that dropped the exemplar block would still look plausible -- it
    would have rules and a voice card -- so this is worth asserting directly
    rather than assuming.
    """
    rendered = " ".join(
        build_pre_prompt(london_profile, format="first_message").split()
    )

    assert london_profile.exemplars
    for exemplar in london_profile.exemplars:
        # Compared against the masked form, because masking is on by default
        # and the masked text is what actually reaches the model.
        body = exemplar.masked_text or exemplar.text
        opening = " ".join(body.split()[:8])
        assert opening in rendered, (
            f"passage {exemplar.passage_index} is missing from the prompt"
        )


def test_the_selection_reasoning_is_never_sent_to_the_model(london_profile):
    """The reasons are for the user, and only the user.

    A model shown "chosen because it is the only conversational passage" will
    treat that as something to live up to, and may imitate the explanation
    rather than the passage. The reasons exist so a person can audit the
    selection, which is a different job from prompting.
    """
    for export_format in FORMATS:
        if export_format == "json":
            # The JSON profile is the audit trail; it is supposed to carry them.
            continue
        rendered = build_pre_prompt(london_profile, format=export_format)
        for exemplar in london_profile.exemplars:
            assert exemplar.reason not in rendered, (
                f"a selection reason leaked into {export_format}"
            )


def test_the_section_order_is_identical_across_the_prompt_formats(london_profile):
    """A fixed prefix is what lets an API consumer cache it.

    Instruction, rules, exemplars, known failures, voice card. If the order
    varied between the two prose formats, any caching built on the stable prefix
    would miss, and the only symptom would be a larger bill.
    """
    def headings(text):
        return [line for line in text.splitlines() if line.startswith("## ")]

    first = headings(build_pre_prompt(london_profile, format="first_message"))
    system = headings(build_pre_prompt(london_profile, format="system_prompt"))

    assert first == system
    assert len(first) >= 4


def test_the_system_prompt_drops_the_chat_framing(london_profile):
    """A system prompt is not read at a moment in time.

    "You are about to be given..." makes sense as the first message of a chat
    and makes no sense in a system field, where it describes an event that
    already happened before every turn. Same content, different framing.
    """
    first_message = build_pre_prompt(london_profile, format="first_message")
    system = build_pre_prompt(london_profile, format="system_prompt")

    assert "about to be given" in first_message
    assert "about to be given" not in system
    assert "every response" in system


def test_the_prompt_forbids_importing_the_author_s_subjects(london_profile):
    """One load-bearing sentence, not a decorative one.

    Without it, a profile of someone's work email produces a model that keeps
    mentioning the quarterly report, and a character voice drags the author's
    circumstances along with it. It is the sentence that makes the separation
    between manner and subject actually hold at generation time.
    """
    rendered = build_pre_prompt(london_profile, format="first_message")

    assert "not what they know or" in rendered
    assert "Do not import their subjects" in rendered


def test_the_voice_card_is_at_most_five_lines_and_ends_on_the_reminder(
    london_profile, james_profile
):
    """The card is a cheap mid-conversation reminder, so brevity is the point.

    "Up to five" rather than "exactly five": a profile with three strong rules
    should not be padded out with two weak ones just to reach a line count. The
    frequency reminder closes it because over-performing a quirk is the usual
    failure.
    """
    for profile in (london_profile, james_profile):
        card = voice_card(profile)
        lines = [line for line in card.splitlines() if line.strip()]

        assert 1 <= len(lines) <= 5
        assert lines[-1].endswith(FREQUENCY_REMINDER)


def test_the_exported_card_validates_against_the_character_card_v2_schema(
    london_profile,
):
    """SillyTavern will reject a card that does not match the published spec.

    This is spec 02's gate. The schema is checked in as a fixture so the test
    needs no network, and it covers the required fields rather than only the
    ones copyme happens to populate.
    """
    card = sillytavern_card(london_profile, name="London")

    jsonschema.validate(card, CARD_SCHEMA)
    assert card["data"]["mes_example"].startswith("<START>")
    assert card["data"]["name"] == "London"


def test_no_export_emits_a_prefill(london_profile):
    """Prefill is a 400 error on current Claude models.

    Older SillyTavern presets lean on an assistant-message prefill to lock
    register, and Claude Sonnet 4.6 and later reject it outright. The in-voice
    opening goes inside the system text instead, so no export may contain a
    prefill or an assistant-role message.
    """
    for export_format in FORMATS:
        rendered = build_pre_prompt(london_profile, format=export_format).lower()
        assert "prefill" not in rendered
        assert '"role": "assistant"' not in rendered


def test_every_prose_export_ends_with_a_provenance_footer(london_profile):
    """Two profiles six months apart have to be distinguishable.

    The footer is also the mechanism behind the commitment that no feature
    strips attribution: the copyme version, the profile hash, the sample size
    and the baseline are always attached to the thing that was generated.
    """
    for export_format in ("first_message", "system_prompt"):
        rendered = build_pre_prompt(london_profile, format=export_format)

        assert london_profile.hash in rendered
        assert "copyme" in rendered
        assert f"{london_profile.word_count:,} words" in rendered


def test_the_footer_names_no_path_no_host_and_no_key(london_profile):
    """Provenance must not become a leak.

    The footer travels wherever the prompt is pasted, which may be a shared
    chat or a published character card. It records what the profile is, never
    where it was built or with what credentials.
    """
    rendered = build_pre_prompt(london_profile, format="first_message")
    footer = rendered.strip().splitlines()[-1]

    assert footer.startswith("<!--")
    for forbidden in ("/Users", "/home", "http://", "https://", "sk-", "ANTHROPIC"):
        assert forbidden not in footer


def test_the_size_indicator_reports_both_tokenisers(london_profile):
    """One number misleads, because the two tokenisers genuinely differ.

    ``cl100k_base`` is exact for the GPT family and works offline. Claude's
    tokeniser is neither, and produces noticeably more tokens for the same
    English. A profile sized against one figure can overflow a budget measured
    by the other, so both are reported and the multiplier is named rather than
    hidden in the arithmetic.
    """
    rendered = build_pre_prompt(london_profile, format="first_message")
    counts = token_estimates(rendered)

    assert counts["gpt"] > 0
    assert counts["claude"] == int(round(counts["gpt"] * CLAUDE_TOKEN_MULTIPLIER))
    assert counts["claude"] > counts["gpt"]
    # The Claude figure can never be exact while the multiplier is in use.
    assert counts["claude_exact"] is False


def test_a_larger_size_renders_a_larger_prompt_from_the_same_profile(london_profile):
    """Re-sizing must work from a stored profile, with no sample and no parse.

    This is what lets the CLI re-render a profile from disk and the UI switch
    size instantly. It works because the full greedy ranking is stored, not just
    the selection.
    """
    compact = build_pre_prompt(london_profile, size="compact")
    full = build_pre_prompt(london_profile, size="full")

    assert token_estimates(full)["gpt"] > token_estimates(compact)["gpt"]


def test_no_export_exceeds_its_size_ceiling(london_profile, james_profile):
    """The preset's token figure is a ceiling the output must respect.

    It is a ceiling rather than a target, and the two cannot both hold: 30
    exemplars capped at 400 tokens each cannot fill a 20,000-token block, so
    Full lands well under its figure. What matters for the user is the
    direction of the error -- a prompt that overflows the field it was sized for
    is a broken prompt, one that comes in short is merely a smaller prompt.
    """
    from copyme.profile import SIZE_PRESETS

    for profile in (london_profile, james_profile):
        for size, preset in SIZE_PRESETS.items():
            rendered = build_pre_prompt(profile, size=size, format="first_message")
            counts = token_estimates(rendered)
            assert counts["claude"] <= preset["total"], (
                f"{size} rendered {counts['claude']} tokens against a ceiling "
                f"of {preset['total']}"
            )


def test_the_v1_result_dictionary_still_renders_the_v1_block(london):
    """Old callers must keep working, including the notebooks.

    ``build_pre_prompt`` accepts either shape. Given the v1 dictionary it
    produces the v1 block, metric dictionary and all -- not because that output
    is good, but because a caller who has not migrated should not silently get
    something different from what they asked for.
    """
    from copyme import build_profile

    legacy = build_profile(london)
    rendered = build_pre_prompt(legacy)

    assert "Metric Dictionary" in rendered
    assert "```json" in rendered
