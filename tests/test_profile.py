"""The Profile: the contract between everything upstream and everything down.

Exports and the scorer read a profile and nothing else. Two properties make that
boundary worth having, and both are tested here: a profile survives a JSON round
trip without loss, and a profile can be re-rendered at any size with no sample
and no parse.

The third group of tests covers backwards compatibility, which is the promise
that opting into v2 is a choice rather than a migration.
"""

import pytest

from copyme import Profile, StyleAnalyser, build_profile
from copyme.profile import (
    RECOMMENDED_MINIMUM_WORDS,
    SIZE_PRESETS,
    UnknownSizeError,
    resolve_size,
)


def test_build_profile_with_no_new_arguments_returns_the_v1_dictionary(london):
    """Existing callers must be entirely unaffected.

    ``analyze_linguistic_style``, the notebooks and the v1 tests all call
    ``build_profile`` with at most a vocabulary percentile. They have to keep
    getting the dictionary they expect, with the same four sections, or v2 is a
    breaking change dressed up as an addition.
    """
    result = build_profile(london)

    assert isinstance(result, dict)
    assert set(result) == {"quantitative", "qualitative", "words", "limits"}
    assert "type_token_ratio" in result["quantitative"]


def test_asking_for_a_size_returns_a_v2_profile_that_still_carries_the_v1_metrics(
    london,
):
    """Opting in must add, never subtract.

    The nine v1 metrics and the qualitative assessments stop being prompt
    content in v2, because a model cannot act on them. They do not stop being
    *available*: they move to the profile's ``metrics`` field, where the UI and
    the JSON export still show them.
    """
    profile = build_profile(london, size="standard")

    assert isinstance(profile, Profile)
    assert profile.rules
    assert profile.exemplars
    assert "type_token_ratio" in profile.metrics["quantitative"]
    assert "cohesive_harmony" in profile.metrics["qualitative"]


def test_a_profile_round_trips_through_json_without_loss(london_profile):
    """A stored profile has to be the same profile when it comes back.

    ``copyme render`` and ``copyme score`` both work from a file, so anything
    lost in serialisation is silently absent at the point of use. Equality on
    the whole dataclass is a stricter check than comparing fields one at a
    time, and it catches a field added without a serialiser.
    """
    reloaded = Profile.from_json(london_profile.to_json())

    assert reloaded == london_profile
    assert reloaded.hash == london_profile.hash


def test_the_serialised_form_records_its_schema_and_hash(london_profile):
    """A file needs to say what it is, so a reader can refuse it politely.

    The CLI checks the schema string and reports "not a copyme v2 profile"
    rather than failing somewhere inside the parsing with a KeyError.
    """
    payload = london_profile.to_dict()

    assert payload["schema"] == "copyme/profile/2"
    assert payload["profile_hash"] == london_profile.hash
    assert payload["provenance"]["copyme_version"]
    assert payload["provenance"]["baseline_version"]


def test_resizing_uses_the_stored_ranking_and_needs_no_analyser(london_profile):
    """Re-rendering at another size must not require the sample back.

    The full greedy order is stored, not just the chosen passages, so a profile
    loaded from disk can be re-sized. Without this the CLI's ``render --size``
    would have to re-parse, and the UI's size radio would re-analyse on every
    click.
    """
    reloaded = Profile.from_json(london_profile.to_json())

    compact = reloaded.at_size("compact")
    full = reloaded.at_size("full")

    assert len(compact.exemplars) < len(full.exemplars)
    assert compact.size == "compact"
    # A prefix of the same ranking, so sizes nest rather than reshuffle.
    assert [e.passage_index for e in full.exemplars][: len(compact.exemplars)] == [
        e.passage_index for e in compact.exemplars
    ]


def test_the_hash_tracks_content_and_not_provenance(london_profile):
    """Two profiles of the same writing should be recognisably the same.

    The hash is what a user compares when they want to know whether a profile
    changed. It covers the features, the rules and which passages were chosen,
    so re-running on the same sample gives the same hash, while a different
    selection gives a different one.
    """
    from dataclasses import replace

    same_content = replace(
        london_profile,
        provenance=dict(london_profile.provenance, word_count=999_999),
    )
    assert same_content.hash == london_profile.hash

    fewer = london_profile.at_size("compact")
    assert fewer.hash != london_profile.hash


def test_an_unknown_size_raises_and_lists_the_real_ones():
    """Size comes from user input in both the CLI and the UI.

    A typo should produce a message naming the three presets, not a KeyError on
    a dictionary the user has never heard of.
    """
    with pytest.raises(UnknownSizeError) as error:
        resolve_size("medium")

    message = str(error.value)
    for size in SIZE_PRESETS:
        assert size in message


def test_the_presets_are_ordered_and_internally_consistent():
    """Compact, Standard and Full have to actually be a ladder.

    Each preset's budget and counts must increase, or the radio in the sidebar
    offers choices that do not differ in the direction they claim to.
    """
    order = ["compact", "standard", "full"]
    totals = [SIZE_PRESETS[size]["total"] for size in order]
    exemplars = [SIZE_PRESETS[size]["exemplars"] for size in order]
    maximums = [SIZE_PRESETS[size]["max_n"] for size in order]

    assert totals == sorted(totals)
    assert exemplars == sorted(exemplars)
    assert maximums == sorted(maximums)

    for size, preset in SIZE_PRESETS.items():
        assert preset["min_n"] <= preset["max_n"], size
        assert preset["exemplars"] < preset["total"], (
            f"{size} leaves no budget for the rules and the instruction block"
        )


def test_a_thin_sample_is_flagged_rather_than_quietly_profiled():
    """Confidence has to match the evidence.

    Selection needs passages to choose between. Below about 2,000 words there
    are not enough of them for distinctiveness or diversity to mean much, and
    presenting the result with the same confidence as a profile of a whole book
    would mislead. The flag drives a warning in the UI and a sentence in the
    prompt itself.
    """
    thin = build_profile(
        StyleAnalyser("A short sample. It says very little. " * 5), size="compact"
    )

    assert thin.word_count < RECOMMENDED_MINIMUM_WORDS
    assert thin.thin is True

    from copyme import build_pre_prompt

    assert "short sample" in build_pre_prompt(thin, format="first_message")


def test_a_profile_records_the_baseline_it_was_measured_against(london_profile):
    """Rules are relative to a baseline, so the baseline is part of the result.

    The shipped baseline is provisional and will be replaced. A profile built
    against the old one must remain interpretable afterwards, which means
    recording which one it was -- otherwise an old profile's rule set looks
    simply wrong rather than differently calibrated.
    """
    provenance = london_profile.provenance

    assert provenance["baseline_version"]
    assert provenance["baseline_status"] in ("provisional", "measured", "test")
    assert provenance["lexical_diversity_measure"] == "mattr"
    assert provenance["selection_weights"] == [0.4, 0.4, 0.2]


def test_a_sample_with_no_usable_passages_still_produces_rules():
    """Too short for exemplars is not too short for a profile.

    The features and the rules are computable from any text. Returning rules
    with no exemplars is more use than an error, and the prompt says the sample
    was thin.
    """
    profile = build_profile(StyleAnalyser("Two sentences. That is all."), size="compact")

    assert profile.exemplars == ()
    assert isinstance(profile.rules, tuple)
    assert profile.provenance["candidate_passages"] == 0
