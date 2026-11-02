"""Generating a blind-test run from a profile, with no network and no key.

Background. copyme's claim is that a model given a profile writes recognisably
like the author. The only thing that can settle that is the blind pairwise test:
show a reader a real passage and a generated one, don't say which is which, and
count how often they pick the real one correctly. Until now the generated side
was produced by hand -- render a prompt, paste it into a chat, copy the reply
back -- which is why no run had ever been recorded.

:mod:`copyme.generate` does that step. These tests cover the two properties that
decide whether a run means anything:

1. The real side of every comparison is a passage the model was **not** shown. A
   passage that is in the prompt tests recall, not voice, and would flatter the
   profile.
2. Nothing here needs a network. The model call is passed in as a function, so a
   fake one returning fixed text exercises the whole module. Only the HTTP call
   itself is left untested.

Every test uses the ``held_out_profile`` fixture -- the London slice rendered at
Compact, where the selection is small enough to leave passages spare.
"""

from dataclasses import replace

import pytest

from copyme.blind import BlindTestError
from copyme.generate import (
    SUBJECT_CHARS,
    TARGET_WORD_FLOOR,
    build_live_run,
    generate_pairs,
    held_out,
    imitation_prompt,
)


def recording_model(text="A short draft, in the author's manner, about the sea."):
    """Return a fake ``model_call`` and the list it records its prompts in.

    Args:
        text (str): What the fake model returns for every call.

    Returns:
        tuple[callable, list]: The callable, and a list that each call appends
            ``(prompt, max_words)`` to.
    """
    calls = []

    def call(prompt, max_words):
        calls.append((prompt, max_words))
        return text

    return call, calls


# --- held_out ---------------------------------------------------------------


def test_held_out_excludes_every_passage_the_prompt_already_carries(held_out_profile):
    """The real side has to be writing the model has not seen.

    The prompt carries the chosen exemplars verbatim. If one of those were used
    as the real side of a comparison, the model would be writing on the subject
    of a passage sitting a few lines above in its own instructions -- so a good
    score would show it can echo, not that it can imitate. Held-out passages are
    ranked but unselected, which makes them the author's genuine writing with
    none of that advantage.

    Input: a Compact London profile, whose selection is smaller than its ranking.
    Expected: no held-out passage shares an index with a chosen one, and every
    held-out passage really is from the ranking.
    """
    chosen = {exemplar.passage_index for exemplar in held_out_profile.exemplars}
    ranked = {exemplar.passage_index for exemplar in held_out_profile.ranking}
    spare = held_out(held_out_profile)

    assert spare, "a Compact profile of this slice should leave passages spare"
    assert not {exemplar.passage_index for exemplar in spare} & chosen
    assert {exemplar.passage_index for exemplar in spare} <= ranked
    assert len(spare) == len(ranked) - len(chosen)


def test_held_out_returns_everything_when_no_count_is_given(held_out_profile):
    """The full list is how the page knows how many rounds a profile affords.

    A user asking for ten rounds from a profile with four spare passages needs to
    be told the ceiling, and the ceiling is the length of this list. Passing a
    count then trims it, best-ranked first.

    Input: the same profile, once with no count and once with ``count=2``.
    Expected: the uncapped call returns more than the capped one, and the capped
    one returns the first two of the same order.
    """
    everything = held_out(held_out_profile)
    first_two = held_out(held_out_profile, count=2)

    assert len(first_two) == 2
    assert len(everything) >= len(first_two)
    assert first_two == everything[:2]


def test_a_profile_that_used_every_passage_holds_nothing_out(london_profile):
    """A short sample at a large size is consumed entirely by its selection.

    This is correct behaviour, not a bug -- Standard is meant to carry as much of
    the author as it can. But it leaves the blind test with nothing honest to
    compare against, so the failure has to be loud and name the fixes rather
    than quietly scoring the model against passages it was shown.

    Input: a profile whose exemplars are its whole ranking.
    Expected: ``held_out`` is empty, and ``generate_pairs`` raises a
    ``BlindTestError`` naming both the Compact fix and the longer-sample fix.
    """
    nothing_spare = replace(london_profile, exemplars=london_profile.ranking)
    model, _ = recording_model()

    assert held_out(nothing_spare) == []

    with pytest.raises(BlindTestError) as error:
        generate_pairs(nothing_spare, model, rounds=3, author="London")

    message = str(error.value)
    assert "Compact" in message
    assert "longer sample" in message


# --- imitation_prompt -------------------------------------------------------


def test_the_prompt_carries_the_profile_and_forbids_reusing_the_wording(
    held_out_profile,
):
    """The model is given the subject, not the sentences.

    The held-out passage is shown so the model knows what to write about, which
    is what keeps the comparison fair: both passages are on the same subject, so
    a reader is judging manner rather than topic. Asking for the subject while
    forbidding the wording is what stops the model simply paraphrasing the
    passage back.

    Input: a short pre-prompt and one held-out passage.
    Expected: the prompt contains the pre-prompt, the instruction not to reuse
    the wording, and at most ``SUBJECT_CHARS`` characters of the passage.
    """
    passage = held_out(held_out_profile, count=1)[0]
    prompt, words = imitation_prompt("THE PROFILE GOES HERE", passage)

    assert "THE PROFILE GOES HERE" in prompt
    assert "do not reuse its wording" in prompt
    assert passage.text[:SUBJECT_CHARS] in prompt
    assert f"about {words} words" in prompt

    long_passage = replace(passage, text="word " * (SUBJECT_CHARS * 2))
    truncated, _ = imitation_prompt("profile", long_passage)
    assert long_passage.text not in truncated


def test_the_target_length_matches_the_real_passage(held_out_profile):
    """A length mismatch is a tell that has nothing to do with voice.

    If the generated passage is half the length of the real one, a reader can
    sort them without reading either, and the run measures nothing. So the
    target word count is taken from the held-out passage itself, with a floor:
    below about sixty words a passage cannot show a sentence rhythm.

    Input: a real held-out passage, and a stub standing in for a very short one.
    Expected: the ask matches the passage's own word count, and never drops
    below ``TARGET_WORD_FLOOR``.
    """
    passage = held_out(held_out_profile, count=1)[0]
    _, words = imitation_prompt("profile", passage)

    assert words == max(TARGET_WORD_FLOOR, len(passage.text.split()))

    tiny = replace(passage, text="Three words only.")
    _, floored = imitation_prompt("profile", tiny)

    assert floored == TARGET_WORD_FLOOR


def test_the_live_contrastive_tier_asks_for_exactly_the_same_thing(held_out_profile):
    """Both surfaces must send one instruction, not two that resemble each other.

    The live contrastive tier predicts where a model will drift; the blind test
    measures whether readers can tell. If the two asked the model for different
    things, the prediction and the measurement would be about different writing,
    and comparing them would be meaningless. They share one function, and this
    test is what stops a later change to one of them from quietly forking it.

    Input: the same pre-prompt and passage through both call sites.
    Expected: byte-identical prompts.
    """
    from copyme.contrastive import imitation_prompt as tier_prompt

    passage = held_out(held_out_profile, count=1)[0]

    assert imitation_prompt("profile", passage) == tier_prompt("profile", passage)


# --- generate_pairs ---------------------------------------------------------


def test_one_comparison_is_generated_per_round(held_out_profile):
    """Each round is a fresh passage and a fresh generation.

    The flashcard loop shows one comparison at a time and moves on to a new
    passage, so three rounds means three held-out passages and three calls to
    the model -- not one generation shown three ways.

    Input: three rounds against a fake model.
    Expected: three model calls, three items, each pairing a held-out passage
    with the model's reply, and the record agreeing.
    """
    model, calls = recording_model()
    items, record = generate_pairs(
        held_out_profile, model, rounds=3, author="Jack London", variant="v2"
    )

    assert len(calls) == 3
    assert len(items) == 3
    assert record["rounds_requested"] == 3
    assert record["rounds_built"] == 3
    assert record["skipped"] == 0

    spare = {exemplar.text for exemplar in held_out(held_out_profile)}
    for item in items:
        assert item["real"] in spare
        assert item["generated"] == "A short draft, in the author's manner, about the sea."
        assert item["author"] == "Jack London"
        assert item["variant"] == "v2"

    assert len({item["pair_id"] for item in items}) == 3


def test_asking_for_more_rounds_than_the_sample_affords_is_capped_not_refused(
    held_out_profile,
):
    """Asking for ten is a reasonable thing for a user to do.

    A user has no way of knowing how many passages a profile holds out before
    they paste it, so asking for more than exists is an ordinary mistake rather
    than an error. The run is trimmed to what the sample affords and the record
    reports both numbers, which is what lets the page say "you asked for 50, this
    profile affords 6" instead of failing.

    Input: 50 rounds from a profile with far fewer spare passages.
    Expected: as many items as there are held-out passages, with the shortfall
    visible in the record.
    """
    available = len(held_out(held_out_profile))
    model, calls = recording_model()

    items, record = generate_pairs(held_out_profile, model, rounds=50, author="London")

    assert len(items) == available
    assert len(calls) == available
    assert record["rounds_requested"] == 50
    assert record["held_out_available"] == available
    assert record["rounds_built"] == available


def test_an_empty_draft_is_dropped_and_counted(held_out_profile):
    """A refusal should cost one round, not the whole run.

    Models occasionally return nothing, or refuse. Raising would throw away the
    rounds that did come back, after the user has already paid for them; silently
    dropping would misreport how many comparisons the run contains. So the round
    is dropped and the count is recorded.

    Input: a model returning empty text on its second call.
    Expected: two items from three rounds, with ``skipped`` reporting the third.
    """
    replies = iter(["First draft.", "   ", "Third draft."])

    def flaky(prompt, max_words):
        return next(replies)

    items, record = generate_pairs(held_out_profile, flaky, rounds=3, author="London")

    assert [item["generated"] for item in items] == ["First draft.", "Third draft."]
    assert record["rounds_built"] == 2
    assert record["skipped"] == 1


def test_progress_is_reported_so_the_page_can_say_what_it_is_doing(held_out_profile):
    """Generation is the slow part, and silence reads as a hang.

    Three rounds is three sequential API calls, which is long enough that a user
    with no feedback will assume the app has frozen. The callback fires before
    each call and once at the end, so a progress bar can reach completion.

    Input: three rounds with a recording callback.
    Expected: one report per round plus a final one, with the total constant.
    """
    model, _ = recording_model()
    reports = []

    generate_pairs(
        held_out_profile,
        model,
        rounds=3,
        author="London",
        on_progress=lambda done, total, label: reports.append((done, total, label)),
    )

    assert [done for done, _, _ in reports] == [0, 1, 2, 3]
    assert {total for _, total, _ in reports} == {3}


def test_a_smaller_size_holds_more_out_so_affords_more_rounds(london_profile):
    """This is the fix for a profile that affords no rounds at all.

    Size decides how many passages the prompt carries, and everything it does
    not carry is held out. A Standard profile of a short sample can take every
    passage there is, leaving the blind test nothing to use -- and re-rendering
    at Compact fixes it without re-parsing anything, because the selection comes
    from the stored ranking.

    Input: the same profile at Standard and at Compact.
    Expected: Compact holds strictly more out.
    """
    compact = london_profile.at_size("compact")

    assert len(held_out(compact)) > len(held_out(london_profile))


# --- build_live_run ---------------------------------------------------------


def test_a_run_produces_a_packet_with_no_answers_in_it(held_out_profile):
    """Blindness is structural: the answers live in the other object.

    The packet is what a reader sees, and it has no record of which side is
    real -- that is in the answer key. Generating the whole run before any of it
    is judged is what makes this hold inside a single-reader session too: the key
    is complete before the first comparison is shown, so the page has nothing to
    leak early even by accident.

    Input: a three-round run with a fixed seed.
    Expected: three pairs in the packet, no side information anywhere in its
    serialised form, and a key that does hold the sides.
    """
    model, _ = recording_model()
    packet, key, record = build_live_run(
        held_out_profile,
        model,
        rounds=3,
        author="Jack London",
        packet_id="run-1",
        seed=7,
        model="test-model",
    )

    assert len(packet.pairs) == 3
    assert packet.authors == ["Jack London"]

    served = packet.to_dict()
    assert "real_side" not in str(served)
    assert "seed" not in str(served)

    assert set(key.real_sides) == {pair.pair_id for pair in packet.pairs}
    assert set(key.real_sides.values()) <= {"left", "right"}
    assert key.seed == 7
    assert record["model"] == "test-model"


def test_the_same_seed_reproduces_the_same_side_assignment(held_out_profile):
    """A run has to be reproducible from its key, or it cannot be audited.

    The side each passage lands on is a seeded coin flip, and the seed is kept in
    the key rather than the packet -- in the packet it would let a reader
    regenerate the assignment and read off the answers. Two runs with one seed
    must therefore agree exactly.

    Input: two runs over the same profile with ``seed=11``.
    Expected: identical sides for identical pair ids.
    """
    model, _ = recording_model()

    _, first, _ = build_live_run(
        held_out_profile, model, rounds=3, author="London", packet_id="a", seed=11
    )
    _, second, _ = build_live_run(
        held_out_profile, model, rounds=3, author="London", packet_id="b", seed=11
    )

    assert first.real_sides == second.real_sides


def test_the_record_names_the_model_but_never_a_key(held_out_profile):
    """No credential may reach a profile, a packet, a result or a log line.

    The model's name does have to travel, because corrections built against one
    model transfer poorly to another and a reader of the result needs to know
    which model wrote the imitation. The name, and only the name.

    Input: a run with a model name set.
    Expected: the name in the record, and nothing key-shaped anywhere in it.
    """
    model, _ = recording_model()
    _, _, record = build_live_run(
        held_out_profile,
        model,
        rounds=2,
        author="London",
        packet_id="run-1",
        model="claude-sonnet-5",
    )

    assert record["model"] == "claude-sonnet-5"
    assert "api_key" not in record
    assert "sk-" not in str(record)


def test_a_run_whose_every_draft_came_back_empty_fails_rather_than_pretending(
    held_out_profile,
):
    """An empty packet would tally to a confident-looking zero.

    ``tally`` on a packet with no pairs returns a pick rate of 0%, which reads
    as a perfect imitation. Refusing to build the packet at all is the only safe
    answer, and ``build_packet`` already does it -- this test is here to prove
    the live path reaches that guard rather than routing around it.

    Input: a model that returns nothing for every round.
    Expected: ``BlindTestError``, naming what each comparison needs.
    """
    with pytest.raises(BlindTestError) as error:
        build_live_run(
            held_out_profile,
            lambda prompt, words: "",
            rounds=3,
            author="London",
            packet_id="run-1",
        )

    assert "both a real passage and a generated one" in str(error.value)


def test_the_key_fits_the_packet_so_a_run_can_be_tallied(held_out_profile):
    """The run has to end in a number, through the same path as a mailed packet.

    A live run is scored by the same ``tally`` as a multi-reader run, against the
    same packet and key objects. That is what keeps a self-serve run comparable
    with a mailed-out one and fit to file in ``docs/evals/``, rather than a
    separate scoring path that happens to produce a similar-looking percentage.

    Input: a three-round run, and a ballot that picks the real side every time.
    Expected: a pick rate of 100% over three judgements -- the arithmetic is
    trivial, which is the point: the plumbing is what is under test.
    """
    from copyme.blind import Ballot, tally

    model, _ = recording_model()
    packet, key, _ = build_live_run(
        held_out_profile, model, rounds=3, author="London", packet_id="run-1", seed=3
    )

    perfect = Ballot(reader="me", picks=dict(key.real_sides), packet_id="run-1")
    result = tally(packet, key, [perfect])

    assert result.judgements == 3
    assert result.correct == 3
    assert result.pick_rate == 1.0
    # One reader is below the protocol's minimum, so the verdict must say the
    # number is indicative rather than a finding.
    assert not result.enough_readers
