"""The generic-prose baseline: the null hypothesis every rule is tested against.

copyme only tells a model to do something if the model would not already do it.
This file is what "already" means, so two things have to hold: it must contain
numbers and nothing else, and it must be honest about how provisional it is.

The second point is not a nicety. The shipped baseline is hand-written and far
smaller than intended, which makes its spreads wider than they should be and so
makes rule suppression conservative. Every profile records which baseline it was
built against precisely because that will change.
"""

import json
from pathlib import Path

import pytest

from copyme.baseline import (
    SUPPRESSION_THRESHOLD,
    BaselineUnavailableError,
    load_baseline,
)
from copyme.features import FEATURE_NAMES

BASELINE_FILE = Path("src/copyme/data/baseline.json")


def test_the_baseline_ships_with_the_package(baseline):
    """Rule suppression and distinctiveness both need it at import time.

    It is packaged rather than generated on first run because a user pasting
    text into the app should not be waiting for a corpus to be analysed, and
    because a baseline that differed between installations would make two
    profiles incomparable.
    """
    assert BASELINE_FILE.exists()
    assert baseline.version
    assert baseline.passages > 0


def test_the_baseline_contains_no_text(baseline):
    """Numbers, feature names and a version only.

    The corpus it was computed from is assistant output, and shipping any of it
    inside the package would mean distributing text nobody asked to distribute
    -- and would invite someone to read the baseline as a style to imitate,
    which is the opposite of its purpose.
    """
    payload = json.loads(BASELINE_FILE.read_text())

    def walk(value, path="root"):
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, str):
            # The only strings allowed are metadata: feature names, the
            # version, the status, a date, the corpus description and the
            # per-feature stability record.
            assert path.startswith(
                (
                    "root.features",
                    "root.version",
                    "root.status",
                    "root.generated",
                    "root.corpus",
                    "root.stability",
                )
            ), f"unexpected text at {path}: {value!r}"
            assert len(value) < 200, f"text at {path} is long enough to be prose"

    walk(payload)


def test_the_baseline_covers_every_shipped_feature(baseline):
    """A feature with no baseline cannot be suppressed or ranked.

    It would silently always produce a rule, because distance from a missing
    mean reads as zero. Adding a feature therefore means regenerating the
    baseline, and this test is what makes that obvious rather than mysterious.
    """
    for name in FEATURE_NAMES:
        assert name in baseline.means, f"{name} has no baseline mean"
        assert name in baseline.spreads, f"{name} has no baseline spread"


def test_the_baseline_is_measured_from_real_model_output(baseline):
    """The baseline must describe a model, not someone's idea of one.

    It shipped first as 20 hand-written passages, and on several features that
    was simply wrong: the passages were single paragraphs, which gave paragraph
    length a large false salience for every author profiled against it. It is
    now 1,152 generated passages, and the status is what the UI reads to decide
    whether to caption a rule set with a warning.
    """
    assert baseline.status == "measured"
    assert baseline.passages > 1_000

    payload = json.loads(BASELINE_FILE.read_text())
    assert payload["corpus"]["model"], "the corpus must record which model it sampled"
    assert payload["corpus"]["approximate_words"] > 300_000


def test_every_feature_driving_a_substantive_rule_has_converged(baseline):
    """Stability is per feature, and only some features matter much.

    `--check` compares each feature's spread over the first half of the corpus
    against the second half. A spread that moves when the corpus grows is a
    spread that cannot be trusted, and because the spread is the denominator of
    every z-score, an untrustworthy one means untrustworthy rule suppression for
    that feature.

    These are the features the most consequential rules are rendered from, so
    this test is the line between "the baseline is good enough to suppress
    rules" and "it is not". The features that remain unconverged are the
    near-zero-frequency ones -- emoji, exclamations, ellipses -- where the spread
    is set by a few outlier passages and is noisy however large the corpus gets.
    """
    payload = json.loads(BASELINE_FILE.read_text())
    unconverged = {row["feature"] for row in payload["stability"]["unstable_features"]}

    substantive = {
        "sentence_length_q1",
        "sentence_length_median",
        "sentence_length_q3",
        "sentence_length_cv",
        "share_short_sentences",
        "share_long_sentences",
        "paragraph_sentences_median",
        "contraction_rate",
        "opener_conjunction_rate",
        "comma_per_sentence",
        "fragment_rate",
        "discourse_marker_per_1k",
        "closing_sentence_length",
        "opening_sentence_length",
    }

    overlap = substantive & unconverged
    assert overlap == set(), (
        f"these features drive substantive rules and their spreads have not "
        f"converged: {sorted(overlap)}"
    )


def test_the_unconverged_features_are_recorded_rather_than_hidden(baseline):
    """A caveat nobody can check is not a caveat.

    15 of 36 spreads are still moving, and the honest thing is to name which,
    with the numbers needed to judge whether it matters for a given author. A
    single "provisional" flag conflated two different questions -- where the
    corpus came from, and whether every spread had converged -- so the baseline
    now answers them separately.
    """
    payload = json.loads(BASELINE_FILE.read_text())
    stability = payload["stability"]

    assert stability["tolerance"] == 0.05
    assert stability["features_above_tolerance"] == len(stability["unstable_features"])

    for row in stability["unstable_features"]:
        assert row["feature"] in FEATURE_NAMES
        # The absolute scale is what makes the percentage interpretable: a 70%
        # difference on a feature averaging 0.1 per 1,000 words is a different
        # matter from 70% on sentence length.
        assert "mean" in row and "spread" in row
        assert row["relative_difference"] > stability["tolerance"]


def test_a_value_at_the_baseline_mean_is_not_distinct(baseline):
    """Zero deviation must never earn a rule. This is the suppression rule itself."""
    for name in FEATURE_NAMES:
        mean = baseline.means[name]
        assert baseline.z(name, mean) == 0.0
        assert baseline.is_distinct(name, mean) is False


def test_a_value_far_from_the_mean_is_distinct(baseline):
    """And the counterpart, so suppression is a threshold rather than an off switch."""
    distinct = 0
    for name in FEATURE_NAMES:
        spread = baseline.spread(name)
        if spread <= 0:
            continue
        far = baseline.means[name] + spread * (SUPPRESSION_THRESHOLD + 1)
        assert baseline.is_distinct(name, far) is True
        distinct += 1

    assert distinct > 10, "most features should have a usable spread"


def test_a_feature_with_no_spread_is_treated_as_carrying_no_evidence(baseline):
    """A zero spread means the corpus never varied, which proves nothing.

    Dividing by it would produce an infinite z-score and that feature would
    dominate every distance and always generate a rule. Returning zero instead
    reads as "no evidence this is unusual", which is the truth.
    """
    from copyme.baseline import Baseline

    flat = Baseline(
        version="test",
        status="test",
        means={"emoji_per_1k": 0.0},
        spreads={"emoji_per_1k": 0.0},
        passages=10,
    )

    assert flat.z("emoji_per_1k", 99.0) == 0.0
    assert flat.is_distinct("emoji_per_1k", 99.0) is False


def test_an_unknown_feature_is_handled_rather_than_raising(baseline):
    """A profile built by a newer copyme may name a feature this baseline lacks.

    Reading it should degrade to "not unusual" rather than raise, so an old
    baseline and a new profile can still be compared, with the gap visible in
    the version each records.
    """
    assert baseline.z("not_a_real_feature", 1.0) == 0.0
    assert baseline.spread("not_a_real_feature") == 0.0


def test_distance_is_standardised_so_no_single_feature_dominates(baseline):
    """Rates per 1,000 words and ratios between 0 and 1 are not comparable raw.

    Without dividing each feature by its own spread, ``discourse_marker_per_1k``
    at 54 would outweigh ``contraction_rate`` at 0.8 purely because its numbers
    are bigger, and distinctiveness would collapse into a measure of one
    feature.
    """
    at_mean = dict(baseline.means)
    assert baseline.distance_from(at_mean) == pytest.approx(0.0, abs=1e-9)

    one_sd_out = {
        name: baseline.means[name] + baseline.spread(name) for name in FEATURE_NAMES
    }
    distance = baseline.distance_from(one_sd_out)
    # Every feature a single standard deviation out gives a mean-square distance
    # of one, whatever the units each feature happens to be measured in.
    assert distance == pytest.approx(1.0, abs=0.01)


def test_a_missing_baseline_raises_a_message_that_names_the_fix(tmp_path):
    """A broken installation should say what to run, not where it crashed."""
    with pytest.raises(BaselineUnavailableError) as error:
        load_baseline(tmp_path / "absent.json")

    assert "build_baseline.py" in str(error.value)


def test_the_baseline_is_cached_so_repeated_loads_are_free(baseline):
    """It is read on every profile build, and the file never changes at runtime."""
    assert load_baseline() is baseline
