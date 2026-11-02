"""The rules renderer: measurements turned into instructions.

The old pre-prompt carried ``modal_hedging_ratio: 0.04``. A model cannot act on
that. These tests enforce the four properties that make a rule actionable --
no metric names, a frequency on every rule, suppression of what the model
already does, and determinism -- because each of them is easy to lose by
accident when a renderer is added or reworded.
"""

from copyme.baseline import SUPPRESSION_THRESHOLD, Baseline
from copyme.features import FEATURE_NAMES, document_features
from copyme.rules import NO_RULE_FEATURES, render_rules, rule_for


def _flat_baseline(scalars, spread=1.0):
    """A baseline whose mean is exactly the author, so nothing is distinctive.

    Useful for isolating suppression: against this baseline the author is the
    generic case, so a correctly behaving renderer emits nothing at all.
    """
    return Baseline(
        version="test",
        status="test",
        means=dict(scalars),
        spreads={name: spread for name in scalars},
        passages=100,
    )


def test_a_feature_matching_the_baseline_produces_no_rule(london):
    """Telling a model to do what it already does wastes the prompt.

    Every line in the rules block competes for attention with every other line.
    A rule that restates the model's default does not just fail to help, it
    dilutes the rules that would have. So a feature within half a standard
    deviation of generic prose is dropped.

    Here the baseline *is* the author, so every feature is at zero deviation and
    the correct output is no rules whatsoever.
    """
    features = document_features(london.doc, london.text)
    rules = render_rules(features, baseline=_flat_baseline(features.scalars))

    assert rules == []


def test_a_feature_far_from_the_baseline_does_produce_a_rule(london):
    """The counterpart: suppression must not swallow everything.

    A renderer that emitted nothing would pass the test above trivially. This
    one shifts the baseline well away from the author and checks that rules
    appear, so suppression is shown to be a threshold rather than an off switch.
    """
    features = document_features(london.doc, london.text)
    distant = Baseline(
        version="test",
        status="test",
        # Every baseline mean is far from the author relative to the spread.
        means={name: value + 10.0 for name, value in features.scalars.items()},
        spreads={name: 1.0 for name in features.scalars},
        passages=100,
    )

    rules = render_rules(features, baseline=distant)
    assert len(rules) > 5


def test_no_rule_mentions_a_metric_name(london_profile):
    """The output must read as writing advice, not as a measurement report.

    This is the single clearest difference between v1 and v2. If a feature name
    leaks into the prose -- because a new renderer interpolated ``feature``
    instead of a label -- the prompt silently reverts to the register the
    research found a model cannot act on.
    """
    assert london_profile.rules

    for rule in london_profile.rules:
        for name in FEATURE_NAMES:
            assert name not in rule.prose, f"{name} leaked into: {rule.prose}"
        assert "_" not in rule.prose or "—" in rule.prose


def test_every_rule_states_a_frequency_and_a_magnitude(london_profile):
    """Whether a habit occurs is the easy half; how often is the useful half.

    "Opens sentences with conjunctions" is satisfied by doing it once and by
    doing it every time, and a model asked that way tends towards the second.
    Over-performing a quirk is the usual failure mode, so every rule carries a
    magnitude and the block closes with the frequency reminder.
    """
    assert london_profile.rules

    for rule in london_profile.rules:
        assert rule.magnitude.strip(), f"no magnitude: {rule.feature}"
        assert rule.prose.strip(), f"no prose: {rule.feature}"
        assert rule.direction.strip()


def test_every_rule_carries_a_band_the_scorer_can_use(london_profile):
    """One record renders as prose, as a card line and as a threshold.

    Keeping the band on the same object as the prose is what stops the scorer
    and the renderer drifting apart: there is no second place where a threshold
    could be defined differently from the instruction it belongs to.
    """
    for rule in london_profile.rules:
        low, high = rule.band
        assert low <= high
        assert low >= 0.0, "every feature here is a rate or a length"
        author_value = london_profile.features[rule.feature]
        assert low <= author_value <= high, (
            f"the author's own value for {rule.feature} must sit inside its band"
        )


def test_rendering_is_deterministic_including_order(london):
    """Rule sets are reviewed as snapshot diffs, so the order has to be fixed.

    Salience decides the order, and ties fall back to the renderer's declared
    priority. Without that second key the order would depend on dictionary
    iteration and the snapshots would churn on every run.
    """
    features = document_features(london.doc, london.text)

    first = render_rules(features)
    second = render_rules(features)

    assert [(r.feature, r.prose) for r in first] == [
        (r.feature, r.prose) for r in second
    ]


def test_rules_are_ordered_by_how_unusual_the_habit_is(london_profile):
    """The most distinctive habit should be the first thing the model reads.

    A prompt is read with diminishing attention, so the ordering is not
    cosmetic: the rules most likely to change the output go first.
    """
    saliences = [rule.salience for rule in london_profile.rules]
    assert saliences == sorted(saliences, reverse=True)


def test_features_held_out_of_rule_rendering_stay_held_out(london_profile):
    """Some features are measured and deliberately never instructed.

    ``cohesive_harmony`` is kept as a descriptor because the research gave no
    evidence a model can act on it. ``function_word_frequency`` is an
    authorship-attribution feature with no generation value. Named-entity
    density describes subject matter, and importing the author's subjects is
    the one thing the instruction block explicitly forbids. All three stay in
    the JSON profile for the user; none becomes a rule.
    """
    produced = {rule.feature for rule in london_profile.rules}

    for feature in NO_RULE_FEATURES:
        assert feature not in produced

    assert rule_for(london_profile.rules, "cohesive_harmony") is None
    assert rule_for(london_profile.rules, "named_entity_per_1k") is None


def test_a_near_zero_habit_renders_as_a_short_negative_rule(james, london):
    """"No semicolons." is a legitimate and valuable rule.

    Absences are as characteristic as presences, and they are cheap to state.
    The renderer must produce the short negative form rather than a frequency of
    zero per thousand words, which would read as a measurement again.
    """
    for analyser in (james, london):
        features = document_features(analyser.doc, analyser.text)
        rules = render_rules(features)
        negatives = [rule for rule in rules if rule.direction == "never"]
        for rule in negatives:
            assert rule.prose.lower().startswith(
                ("never", "no ", "use no", "do not", "write complete")
            ), rule.prose
            assert len(rule.prose) < 160, "a negative rule should be short"


def test_different_authors_get_different_rules(london, james):
    """If two very different writers got the same rules, the rules say nothing.

    London's short declaratives and James's subordinated clauses are a deliberate
    contrast in the fixture set. The rule sets they produce must differ, or the
    renderer is describing prose in general rather than this author.
    """
    london_rules = render_rules(document_features(london.doc, london.text))
    james_rules = render_rules(document_features(james.doc, james.text))

    assert {r.prose for r in london_rules} != {r.prose for r in james_rules}


def test_the_suppression_threshold_is_a_parameter(london):
    """Suppression has to be adjustable, because the baseline is provisional.

    The shipped baseline is hand-built and its spreads are wider than they
    should be, which makes suppression conservative. Being able to move the
    threshold is what lets that be investigated rather than argued about.
    """
    features = document_features(london.doc, london.text)

    strict = render_rules(features, threshold=SUPPRESSION_THRESHOLD * 6)
    loose = render_rules(features, threshold=0.0)

    assert len(strict) < len(loose)
