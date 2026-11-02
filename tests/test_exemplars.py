"""Exemplar selection: choosing which of the author's passages to send.

v2 rests on the finding that a model imitates a voice from examples far better
than from a description of it. That makes this the most consequential module in
the project, and the one whose parameters are least settled: the 0.4/0.4/0.2
weights are intuitions until the blind protocol measures them.

These tests therefore pin **properties** rather than particular choices. Which
passage comes first is allowed to change when the weights are tuned; the
invariants below are not.
"""

from copyme.exemplars import DEFAULT_WEIGHTS, select_exemplars


def test_a_larger_budget_returns_a_superset_of_a_smaller_one(london):
    """Raising the budget must only ever add passages, never reshuffle them.

    The Streamlit sidebar lets a user move between sizes freely, and the
    vocabulary percentile already holds this property. Without it, nudging the
    size up would silently drop a passage the user had read and approved, which
    reads as a bug even though every individual selection is defensible.

    The mechanism is that the greedy order is computed once and the budget then
    truncates it as a prefix.
    """
    small = select_exemplars(london, budget_tokens=1_200)
    large = select_exemplars(london, budget_tokens=10_000)

    small_indexes = [item.passage_index for item in small.exemplars]
    large_indexes = [item.passage_index for item in large.exemplars]

    assert len(large_indexes) > len(small_indexes)
    assert large_indexes[: len(small_indexes)] == small_indexes


def test_selection_stays_within_its_budget_once_the_floor_is_met(london):
    """The budget is a ceiling, and the exemplar count is a floor.

    Both matter, and they conflict on a short sample: three passages may cost
    more than a Compact budget allows. The floor wins, because a profile with
    one exemplar does not show a voice -- but the overspend is recorded in
    ``used_tokens`` rather than hidden, so a caller can see it.
    """
    selection = select_exemplars(london, budget_tokens=10_000, min_n=3)

    assert selection.used_tokens <= selection.budget_tokens
    assert len(selection.exemplars) >= 3


def test_every_exemplar_carries_a_reason(london):
    """A selection the user cannot interrogate is a selection they cannot trust.

    The reason is the only thing that explains why one of the author's
    paragraphs was chosen over another, and it is shown in the UI beside the
    passage. An empty reason would leave a bare passage with no account of
    itself.
    """
    selection = select_exemplars(london, budget_tokens=5_000)

    assert selection.exemplars
    for exemplar in selection.exemplars:
        assert exemplar.reason.strip(), f"passage {exemplar.passage_index} has no reason"


def test_a_zero_weight_disables_its_axis(london):
    """Each axis must be switchable, because none of them is proven.

    The weights ship as intuitions. Being able to set one to zero is what lets
    the blind protocol measure the contribution of each axis separately rather
    than only the combination that happens to ship.
    """
    typicality_only = select_exemplars(london, 5_000, weights=(1.0, 0.0, 0.0))
    distinct_only = select_exemplars(london, 5_000, weights=(0.0, 1.0, 0.0))

    assert typicality_only.exemplars
    assert distinct_only.exemplars
    # Optimising for opposite things must not produce the same first pick.
    assert (
        typicality_only.exemplars[0].passage_index
        != distinct_only.exemplars[0].passage_index
    )


def test_typicality_and_distinctiveness_rank_differently(london):
    """The two axes must measure genuinely different things.

    Typicality is distance from the author's own centre; distinctiveness is
    distance from generic model prose. If they ranked passages identically, one
    of them would be redundant and the weighted combination would be
    theatre.
    """
    selection = select_exemplars(london, 20_000, weights=DEFAULT_WEIGHTS)
    ranking = selection.ranking

    by_typicality = sorted(ranking, key=lambda item: -item.typicality)
    by_distinctiveness = sorted(ranking, key=lambda item: -item.distinctiveness)

    assert [item.passage_index for item in by_typicality] != [
        item.passage_index for item in by_distinctiveness
    ]


def test_selection_is_deterministic(london):
    """The same sample must always produce the same exemplars.

    Exemplar choices are snapshotted per author and reviewed as diffs. Any
    non-determinism -- a set iteration order, an unstable tie-break -- would make
    every snapshot churn and the review worthless.
    """
    first = select_exemplars(london, 5_000)
    second = select_exemplars(london, 5_000)

    assert [item.passage_index for item in first.exemplars] == [
        item.passage_index for item in second.exemplars
    ]
    assert [item.reason for item in first.exemplars] == [
        item.reason for item in second.exemplars
    ]


def test_author_spreads_are_returned_for_the_rule_bands(london):
    """The scorer's bands come from the author's own variation, measured here.

    A band set to a flat percentage would call a consistent writer's ordinary
    sentence out of range and let an erratic writer's wild swing pass. Selection
    already walks every passage to compute the spread, so it hands the numbers
    on rather than making the renderer walk them again.
    """
    selection = select_exemplars(london, 5_000)

    assert selection.author_spreads
    assert selection.document_features is not None
    assert all(value >= 0 for value in selection.author_spreads.values())


def test_a_sample_with_no_usable_passage_returns_an_empty_selection():
    """Too short to choose from is a normal case, not an error.

    Someone pastes two sentences to see what the tool does. It must come back
    with an empty selection -- the profile then ships rules only -- rather than
    raising from inside the distance maths.
    """
    from copyme import StyleAnalyser

    selection = select_exemplars(StyleAnalyser("Two short sentences. That is all."), 5_000)

    assert selection.exemplars == []
    assert selection.candidate_count == 0
