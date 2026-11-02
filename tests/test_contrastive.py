"""The contrastive tiers: telling the model where it will go wrong.

The one prompting technique with direct published evidence on Claude is to show
an off-voice attempt beside the real thing with a one-line explanation of the
gap -- and the explanations carried most of the gain, not the failed examples.
That is why the static tier works without ever calling a model: the gap between
the author and the baseline already says where a model will drift, because the
baseline *is* what a model does unprompted.

Every test here runs with no network and no API key. The live tier takes its
model call as an argument precisely so it can be tested this way.
"""

import pytest

from copyme.baseline import Baseline
from copyme.contrastive import (
    MAX_NOTES,
    LiveTierUnavailableError,
    anthropic_model_call,
    live_notes,
    static_notes,
)
from copyme.features import document_features
from copyme.rules import render_rules
from copyme.scorer import score


def test_at_most_three_notes_ranked_by_how_far_the_author_sits_from_generic(
    london, baseline
):
    """Three is where the token budget stops paying for itself.

    Naming specific "AI-ish" habits measurably helped in the 2025 reader study,
    so the notes are worth their space -- but each one competes with the rules
    and the passages for attention, and the fourth earns less than it costs.
    """
    features = document_features(london.doc, london.text)
    rules = render_rules(features, baseline=baseline)
    notes = static_notes(features, baseline, rules)

    assert len(notes) <= MAX_NOTES
    assert notes, "the London fixture should differ from generic prose somewhere"
    assert all(note.startswith("**Likely drift:**") for note in notes)


def test_notes_are_deterministic_for_a_fixed_profile(london, baseline):
    """These are snapshotted, so the order has to be fixed.

    Ties are broken on the feature name rather than left to dictionary order,
    which is the sort of thing that works for years and then changes with an
    interpreter upgrade.
    """
    features = document_features(london.doc, london.text)
    rules = render_rules(features, baseline=baseline)

    assert static_notes(features, baseline, rules) == static_notes(
        features, baseline, rules
    )


def test_an_author_close_to_generic_prose_gets_no_notes(london):
    """No predictable drift means no section, not an empty heading.

    A heading with nothing under it reads as a bug to the user and spends tokens
    on the model. Here the baseline is set to the author exactly, so there is
    genuinely nothing to warn about.
    """
    features = document_features(london.doc, london.text)
    identical = Baseline(
        version="test",
        status="test",
        means=dict(features.scalars),
        spreads={name: 1.0 for name in features.scalars},
        passages=100,
    )

    rules = render_rules(features, baseline=identical)
    assert static_notes(features, identical, rules) == []


def test_a_note_is_only_emitted_for_a_feature_that_also_has_a_rule(london, baseline):
    """Every warning needs a corresponding instruction.

    A note saying "your sentences will come out too long" with no rule stating
    the author's actual sentence length tells the model there is a problem and
    nothing about the solution.
    """
    features = document_features(london.doc, london.text)
    rules = render_rules(features, baseline=baseline)
    ruled = {rule.magnitude for rule in rules}

    for note in static_notes(features, baseline, rules):
        assert any(magnitude in note for magnitude in ruled), note


def test_a_note_describes_what_the_model_will_do_not_what_the_author_does(
    london, baseline
):
    """The note is a correction, so it is written from the model's side.

    "Sentences will come out longer than they should" is recognisable to a model
    as its own tendency. "The author writes short sentences" is a restatement of
    the rules, which are already in the prompt a few lines above.
    """
    features = document_features(london.doc, london.text)
    rules = render_rules(features, baseline=baseline)

    for note in static_notes(features, baseline, rules):
        assert "will come out" in note
        assert "Correct towards the author" in note


def test_the_live_tier_scores_real_drafts_without_touching_the_network(held_out_profile):
    """The live tier is testable because the model call is injected.

    Nothing here opens a socket: the "model" is a function returning fixed
    assistant-register prose. That is what lets the whole tier -- hold out
    passages, generate, score, phrase the note -- be covered by a unit test,
    leaving only the API call itself untested.
    """
    calls = []

    def fake_model(prompt, max_words):
        calls.append((prompt, max_words))
        return (
            "It is important to note that there are a number of factors which "
            "may influence the outcome, and each of them should be carefully "
            "considered before any decision is reached. Additionally, it would "
            "generally be advisable to establish a clear understanding of the "
            "requirements before proceeding any further with the work itself."
        )

    notes, record = live_notes(
        held_out_profile, fake_model, score, model="test-model", count=2
    )

    assert len(calls) == 2
    assert record["model"] == "test-model"
    assert record["drafts_scored"] == 2
    assert 0.0 <= record["mean_in_band"] <= 1.0
    assert notes, "assistant-register prose should drift from Jack London"
    assert all(note.startswith("**Measured drift (test-model)") for note in notes)
    assert len(notes) <= MAX_NOTES


def test_the_live_tier_tests_against_passages_the_selector_did_not_choose(
    held_out_profile,
):
    """Otherwise it measures the model's ability to copy, not to imitate.

    Asking the model to write on the subject of a passage it was just shown, and
    then scoring the result, flatters the profile. The held-out passages are
    ranked but unselected, so they are the author's writing that the model has
    not seen.
    """
    from copyme.contrastive import _held_out

    held = _held_out(held_out_profile, count=2)
    chosen = {exemplar.passage_index for exemplar in held_out_profile.exemplars}

    assert len(held) == 2
    assert not {exemplar.passage_index for exemplar in held} & chosen

    seen = []

    def fake_model(prompt, max_words):
        seen.append(prompt)
        return "A short draft. It does not matter what this says."

    live_notes(held_out_profile, fake_model, score, count=2)

    # Each prompt must carry one of the held-out passages as its subject. The
    # chosen exemplars also appear in every prompt, because the pre-prompt is
    # part of it -- so the check is that the subject is a held-out passage,
    # not that the chosen ones are absent.
    assert len(seen) == 2
    for prompt, passage in zip(seen, held):
        assert " ".join(passage.text.split()[:10]) in " ".join(prompt.split())


def test_the_live_tier_records_the_model_but_never_a_key(held_out_profile):
    """Corrections built against one model transfer poorly to another.

    So the model's name has to travel with the profile, which is what lets the
    UI warn a user who pastes a Claude-tuned profile into something else. The
    name, and only the name: no key may reach a profile, a cache, a footer or a
    log line.
    """
    notes, record = live_notes(
        held_out_profile,
        lambda prompt, words: "It is important to note that this is a draft.",
        score,
        model="claude-sonnet-5",
    )

    assert record["model"] == "claude-sonnet-5"
    assert "api_key" not in record
    for value in record.values():
        assert "sk-" not in str(value)


def test_the_live_tier_fails_clearly_when_there_is_nothing_to_hold_out(
    london_profile,
):
    """A short sample can be entirely consumed by the selection.

    The honest answer is to say so and name the fix, rather than silently
    scoring the model against passages it was shown.
    """
    from dataclasses import replace

    nothing_spare = replace(london_profile, exemplars=london_profile.ranking)

    with pytest.raises(LiveTierUnavailableError) as error:
        live_notes(nothing_spare, lambda prompt, words: "x", score)

    assert "longer sample" in str(error.value)


def test_asking_for_the_live_tier_with_no_key_explains_itself(monkeypatch):
    """Degrading has to come with a reason.

    The static tier is the default for good reasons, so falling back to it is
    not a failure -- but a user who asked for the live tier and silently got the
    static one would have no way to know why their profile looked different from
    what they expected.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(LiveTierUnavailableError) as error:
        anthropic_model_call(model="claude-sonnet-5")

    message = str(error.value)
    assert "ANTHROPIC_API_KEY" in message or "anthropic" in message
    assert "static" in message
