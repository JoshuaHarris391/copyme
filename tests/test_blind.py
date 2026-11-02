"""Tests for the blind pairwise test.

The blind test is the only thing that settles copyme's actual claim -- that a
model given a profile writes recognisably like the author -- so the properties
tested here are mostly about *not misleading the person reading the result*:
that a reader cannot find the answers, that a small sample is reported as a
small sample, and that a near-gate number is not dressed up as a pass.
"""

import json

import pytest

from copyme.blind import (
    CHANCE,
    MIN_READERS,
    RELEASE_GATE,
    AnswerKey,
    Ballot,
    BlindTestError,
    Packet,
    ballot_from_json,
    build_packet,
    packet_from_json,
    tally,
    wilson_interval,
)


def items(count, author="London", variant="v2"):
    """Build `count` real/generated pairs with recognisably different sides.

    The texts are deliberately trivial. No test here cares what the passages
    say: the module never looks at the text, only at which side it was put on.

    Args:
        count (int): How many pairs to make.
        author (str): Author name to attach.
        variant (str): Prompt variant to attach.

    Returns:
        list[dict]: Items suitable for `build_packet`.
    """
    return [
        {
            "author": author,
            "variant": variant,
            "real": f"REAL passage {index}",
            "generated": f"GENERATED passage {index}",
        }
        for index in range(1, count + 1)
    ]


def ballot_of(packet, key, reader, correct_count):
    """Build a ballot that gets exactly `correct_count` pairs right.

    This is how every scoring test below controls the pick rate: rather than
    simulating readers, it constructs a ballot with a known number of hits, so
    the expected pick rate is arithmetic rather than chance.

    Args:
        packet (Packet): The packet being judged.
        key (AnswerKey): Its answer key.
        reader (str): Reader label.
        correct_count (int): How many picks should be right. The rest are
            deliberately wrong.

    Returns:
        Ballot: The ballot.
    """
    picks = {}
    for position, pair in enumerate(packet.pairs):
        truth = key.real_sides[pair.pair_id]
        if position < correct_count:
            picks[pair.pair_id] = truth
        else:
            picks[pair.pair_id] = "left" if truth == "right" else "right"
    return Ballot(reader=reader, picks=picks, packet_id=packet.packet_id)


# -- Blindness ---------------------------------------------------------------


def test_the_packet_carries_no_record_of_which_side_is_real():
    """A reader holding the packet must not be able to find the answers.

    This is the whole point of the exercise. If the file handed to a reader
    contains the key in any form, the test is not blind and its number means
    nothing. So this asserts on the serialised JSON text rather than on the
    object: it is the file that gets emailed to a reader.
    """
    packet, key = build_packet(items(5), packet_id="pk1", seed=7)

    serialised = json.dumps(packet.to_dict())

    assert "real_side" not in serialised
    assert "real_sides" not in serialised
    # The seed must not travel with the packet either: with the seed and the
    # published algorithm, a reader could regenerate the side assignment.
    assert "seed" not in serialised
    assert key.seed == 7


def test_the_packet_does_not_reveal_the_answer_through_side_ordering():
    """The real passage must not always land on the same side.

    A packet that put every real passage on the left would pass the test above
    -- no key in the file -- and still be transparent to a reader after two
    pairs. Twenty pairs is enough that an all-one-side result would be a
    one-in-a-million coincidence rather than plausible chance.
    """
    _, key = build_packet(items(20), packet_id="pk1", seed=3)

    sides = set(key.real_sides.values())

    assert sides == {"left", "right"}


def test_the_assignment_is_reproducible_from_the_seed():
    """The same seed must produce the same packet.

    Needed so a run can be reconstructed from the key alone if a packet file
    is lost, and so these tests are not flaky.
    """
    first, first_key = build_packet(items(6), packet_id="pk1", seed=42)
    second, second_key = build_packet(items(6), packet_id="pk1", seed=42)

    assert first.to_dict() == second.to_dict()
    assert first_key.real_sides == second_key.real_sides


# -- Scoring -----------------------------------------------------------------


def test_a_reader_who_always_picks_the_real_author_scores_100_percent():
    """The imitation failed completely: every judgement found the real passage.

    The arithmetic end of the scale, confirming "correct" means what the
    module says it means -- identifying the *real* author, not picking the
    generated side.
    """
    packet, key = build_packet(items(10), packet_id="pk1", seed=1)
    ballots = [ballot_of(packet, key, f"r{n}", correct_count=10) for n in range(3)]

    result = tally(packet, key, ballots)

    assert result.pick_rate == 1.0
    assert result.judgements == 30
    assert result.meets_gate is False


def test_a_reader_at_chance_cannot_tell_the_difference():
    """Half right is a coin flip, which is the best imitation can do.

    The interval must reach down to chance here, and `indistinguishable` must
    say so: that flag is what stops a 50% result being reported as a triumph
    of imitation when it is in fact the expected result of guessing.
    """
    packet, key = build_packet(items(10), packet_id="pk1", seed=1)
    ballots = [ballot_of(packet, key, f"r{n}", correct_count=5) for n in range(3)]

    result = tally(packet, key, ballots)

    assert result.pick_rate == 0.5
    assert result.indistinguishable is True
    assert result.interval[0] <= CHANCE <= result.interval[1]


def test_skipped_pairs_are_not_counted_against_the_reader():
    """A reader who leaves a pair blank has not got it wrong.

    The protocol asks for a pick per pair, but a part-finished ballot is
    common and still carries information. Counting an omission as incorrect
    would bias the pick rate upward -- making the imitation look worse than it
    is -- so omissions are excluded from the denominator instead.
    """
    packet, key = build_packet(items(10), packet_id="pk1", seed=1)
    full = ballot_of(packet, key, "r1", correct_count=10)
    partial = Ballot(
        reader="r2",
        picks=dict(list(full.picks.items())[:4]),
        packet_id="pk1",
    )

    result = tally(packet, key, [partial])

    assert result.judgements == 4
    assert result.correct == 4
    assert result.pick_rate == 1.0


def test_picks_for_unknown_pairs_are_ignored_rather_than_raising():
    """A hand-edited ballot should still contribute its good rows.

    Ballots are JSON files that pass through email and spreadsheets, so a
    stray or stale pair id is a question of when, not if. Discarding the whole
    ballot would lose real judgements; raising would block the tally entirely.
    """
    packet, key = build_packet(items(5), packet_id="pk1", seed=1)
    picks = ballot_of(packet, key, "r1", correct_count=5).picks
    picks["p999-does-not-exist"] = "left"
    picks["also-bad"] = "sideways"

    result = tally(packet, key, [Ballot(reader="r1", picks=picks, packet_id="pk1")])

    assert result.judgements == 5
    assert result.pick_rate == 1.0


# -- Honesty about the sample ------------------------------------------------


def test_too_few_readers_is_reported_as_indicative_rather_than_a_result():
    """One reader's taste is not a measurement, and must not read like one.

    The protocol asks for three or more readers per author. With fewer, the
    verdict has to say so before it says anything about the gate, because a
    single reader's pick rate invites exactly the over-reading this whole
    module exists to prevent.
    """
    packet, key = build_packet(items(10), packet_id="pk1", seed=1)
    ballots = [ballot_of(packet, key, "only-reader", correct_count=6)]

    result = tally(packet, key, ballots)

    assert result.readers == 1
    assert result.enough_readers is False
    assert "at least 3" in result.verdict
    assert "indicative only" in result.verdict


def test_a_point_estimate_at_the_gate_does_not_count_as_meeting_it():
    """60% from 30 judgements is not a pass, because the interval reaches past it.

    This is the single most important behaviour here. The spec's gate is a
    pick rate of 70% or lower. A run scoring 60% looks like a comfortable
    pass, but 18 correct from 30 has a 95% interval reaching to roughly 76% --
    above the gate. Reporting that as "gate met" would be the most misleading
    thing this module could do, so `meets_gate` requires the whole interval to
    sit at or below the gate, and the verdict says the sample is too small.
    """
    packet, key = build_packet(items(10), packet_id="pk1", seed=1)
    ballots = [ballot_of(packet, key, f"r{n}", correct_count=6) for n in range(3)]

    result = tally(packet, key, ballots)

    assert result.pick_rate == pytest.approx(0.6)
    assert result.pick_rate <= RELEASE_GATE
    assert result.interval[1] > RELEASE_GATE
    assert result.meets_gate is False
    assert "too few judgements" in result.verdict


def test_a_large_enough_sample_below_the_gate_does_meet_it():
    """With enough judgements, a good result is allowed to be a good result.

    The strictness above must not make the gate unreachable. 200 judgements at
    55% gives an interval comfortably under 70%, and that is a pass.
    """
    packet, key = build_packet(items(50), packet_id="pk1", seed=1)
    ballots = [ballot_of(packet, key, f"r{n}", correct_count=22) for n in range(4)]

    result = tally(packet, key, ballots)

    assert result.judgements == 200
    assert result.pick_rate == pytest.approx(0.44)
    assert result.interval[1] <= RELEASE_GATE
    assert result.meets_gate is True
    assert "gate is met" in result.verdict


def test_no_judgements_reports_nothing_rather_than_zero_percent():
    """An empty tally must not read as a perfect score.

    `pick_rate` is 0.0 with no data, and 0% is the *best possible* result. A
    verdict reading "0%" over an empty run would invert the finding entirely,
    so the no-data case is stated as no data.
    """
    packet, key = build_packet(items(5), packet_id="pk1", seed=1)

    result = tally(packet, key, [])

    assert result.judgements == 0
    assert result.meets_gate is False
    assert "nothing to report" in result.verdict


def test_an_interval_with_no_trials_spans_everything():
    """No trials means no knowledge, which is an interval of 0 to 1.

    Guards against a divide-by-zero dressed up as certainty.
    """
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_the_interval_stays_inside_zero_and_one():
    """A proportion's confidence interval cannot leave [0, 1].

    This is why the Wilson interval is used rather than the textbook normal
    approximation, which at 10 out of 10 would put the upper bound above 1 and
    the lower bound well above where the evidence supports.
    """
    low, high = wilson_interval(10, 10)

    assert 0.0 <= low <= high <= 1.0
    assert high == pytest.approx(1.0)
    # Ten from ten is consistent with a true rate well under 1, and the
    # interval should admit that rather than claiming certainty.
    assert low < 0.95


# -- Breakdowns --------------------------------------------------------------


def test_results_are_broken_down_by_author():
    """Imitation can work for one voice and fail for another.

    An aggregate pick rate hides that, and the four golden fixtures are
    different enough -- two novelists, a humorist, a playwright -- that the
    per-author figures are the actionable ones.
    """
    london = build_packet(items(4, author="London"), packet_id="pk1", seed=1)
    james = build_packet(items(4, author="James"), packet_id="pk1", seed=2)

    # Merging is the realistic case: one packet per author, combined for a
    # reader who knows both. The default ids are author-scoped, so this is
    # safe -- `test_merging_packets_with_colliding_ids_is_refused` covers what
    # happens when they are not.
    merged = Packet(pairs=london[0].pairs + james[0].pairs, packet_id="pk1")
    merged_key = AnswerKey(
        real_sides={**london[1].real_sides, **james[1].real_sides}, packet_id="pk1"
    )

    # Readers always right about London, always wrong about James.
    picks = {}
    for pair in merged.pairs:
        truth = merged_key.real_sides[pair.pair_id]
        picks[pair.pair_id] = truth if pair.author == "London" else (
            "left" if truth == "right" else "right"
        )
    ballots = [Ballot(reader=f"r{n}", picks=picks, packet_id="pk1") for n in range(3)]

    result = tally(merged, merged_key, ballots)

    assert result.by_author["London"][0] == 1.0
    assert result.by_author["James"][0] == 0.0


def test_results_are_broken_down_by_prompt_variant():
    """The protocol compares v2 against v1, not against nothing.

    A bare pick rate cannot say whether v2 improved anything. Tagging each
    pair with the prompt that produced it turns the run into a comparison,
    which is what the spec asks for.
    """
    packet, key = build_packet(
        items(3, variant="v1") + items(3, variant="v2"),
        packet_id="pk1",
        seed=5,
    )
    ballots = [ballot_of(packet, key, f"r{n}", correct_count=6) for n in range(3)]

    result = tally(packet, key, ballots)

    assert set(result.by_variant) == {"v1", "v2"}
    assert result.by_variant["v1"][1] == 9
    assert result.by_variant["v2"][1] == 9


# -- Mistakes a user will actually make --------------------------------------


def test_tallying_against_the_wrong_packets_key_is_refused():
    """A mismatched key produces a number near chance, which looks like a finding.

    This is the dangerous failure: nothing errors, the pick rate comes out
    around 50%, and the organiser concludes the imitation is undetectable when
    in fact they tallied the wrong file. It has to be refused loudly.
    """
    packet, _ = build_packet(items(5), packet_id="morning-run", seed=1)
    _, other_key = build_packet(items(5), packet_id="afternoon-run", seed=2)

    with pytest.raises(BlindTestError, match="meaningless"):
        tally(packet, other_key, [])


def test_uploading_the_key_where_the_packet_belongs_says_so():
    """The two files look alike, and readers will mix them up.

    The error names which file is which rather than reporting a schema
    problem, because the person hitting it is a reader, not a developer.
    """
    _, key = build_packet(items(3), packet_id="pk1", seed=1)

    with pytest.raises(BlindTestError, match="not a blind-test packet"):
        packet_from_json(json.dumps(key.to_dict()))


def test_merging_packets_with_colliding_ids_is_refused():
    """Two pairs sharing an id would credit one's judgements to the other.

    This was found by writing the per-author test above: merging two packets
    whose pairs were numbered from 1 silently discarded one author's pairs
    entirely and reported a pick rate for the survivor. Nothing errored and
    the number looked ordinary, which is the worst kind of bug in a measuring
    instrument -- so a collision is now refused, and default ids are scoped by
    author so hand-built packets rarely collide in the first place.
    """
    first, _ = build_packet(items(2), packet_id="pk1", seed=1)
    clashing = Packet(pairs=first.pairs + first.pairs, packet_id="pk1")

    with pytest.raises(BlindTestError, match="repeated pair ids"):
        tally(clashing, AnswerKey(real_sides={}, packet_id="pk1"), [])


def test_default_pair_ids_are_scoped_by_author_and_variant():
    """Default ids must not collide across the packets an organiser will merge.

    A run covers several authors and both prompt variants, built as separate
    packets and combined. Positional ids alone (`p001`) collide immediately;
    including the author and variant means they do not.
    """
    london, _ = build_packet(items(2, author="Jack London", variant="v2"), packet_id="pk1", seed=1)
    james, _ = build_packet(items(2, author="Henry James", variant="v1"), packet_id="pk1", seed=1)

    ids = {pair.pair_id for pair in london.pairs} | {pair.pair_id for pair in james.pairs}

    assert len(ids) == 4
    assert "jack-london-v2-001" in ids
    assert "henry-james-v1-001" in ids


def test_a_packet_round_trips_through_json():
    """Packets travel as files between people, so the round trip must be exact."""
    packet, _ = build_packet(items(4), packet_id="pk1", seed=9, note="Pick the real one.")

    restored = packet_from_json(json.dumps(packet.to_dict()))

    assert restored == packet
    assert restored.note == "Pick the real one."


def test_a_comparison_missing_one_side_is_dropped_not_half_shown():
    """A pair needs both passages, or it is not a comparison.

    Half-filled rows are the normal state of a form while it is being filled
    in, so they are skipped quietly. If nothing usable remains, that is an
    error with a message saying what is missing.
    """
    usable = items(2)
    half_filled = [{"author": "London", "real": "only the real one", "generated": "  "}]

    packet, key = build_packet(usable + half_filled, packet_id="pk1", seed=1)

    assert len(packet.pairs) == 2
    assert len(key.real_sides) == 2

    with pytest.raises(BlindTestError, match="both a real passage"):
        build_packet(half_filled, packet_id="pk1", seed=1)


def test_the_whole_run_survives_the_round_trip_through_files():
    """A real run passes through three files and several people.

    The organiser builds a packet and a key, emails the packet, each reader
    sends back a ballot, and the organiser tallies. Every hop is JSON on disk,
    so this walks the full path rather than passing objects around in memory --
    which is the only way it is actually used, and the only way a serialisation
    mistake shows up.
    """
    packet, key = build_packet(items(10), packet_id="run-1", seed=5)

    # The organiser sends this. The key stays behind.
    posted = json.dumps(packet.to_dict())
    received = packet_from_json(posted)

    # Three readers judge the packet they received, 7 of 10 correct each.
    returned = [
        json.dumps(ballot_of(received, key, f"reader-{n}", correct_count=7).to_dict())
        for n in range(3)
    ]
    ballots = [ballot_from_json(text) for text in returned]

    result = tally(received, key, ballots)

    assert result.judgements == 30
    assert result.correct == 21
    assert result.pick_rate == pytest.approx(0.7)
    assert result.readers == 3
    assert result.enough_readers is True
    # Exactly the gate on the point estimate, and still not a pass: 21 of 30
    # reaches well above 70%, which is the whole reason the interval is shown.
    assert result.meets_gate is False
    assert "too few judgements" in result.verdict


def test_the_protocol_minimum_is_the_documented_one():
    """The constants must match the spec the documentation points readers at.

    `docs/specs/04-live-loop-and-evaluation.md` sets a 70% gate and three
    readers. If either changes, the docs and this module must change together,
    and this test is what makes that fail loudly rather than drift.
    """
    assert RELEASE_GATE == 0.70
    assert MIN_READERS == 3
    assert CHANCE == 0.50
