"""Tests for the analysis progress reporting that drives the status indicator."""

import pytest

from copyme import (
    ANALYSIS_STAGES,
    ProgressReporter,
    StyleAnalyser,
    analyze_linguistic_style,
)


def test_progress_reporter_is_a_no_op_without_callback():
    report = ProgressReporter()
    assert report.enabled is False
    report("parse", 0.0)
    report("vocabulary", 1.0)  # must not raise


def test_every_stage_key_is_in_stage_boundaries():
    from copyme.analyser import STAGE_BOUNDARIES

    assert set(STAGE_BOUNDARIES) == {key for key, _, _ in ANALYSIS_STAGES}


def test_progress_is_monotonic_and_reaches_one_hundred():
    seen = []
    report = ProgressReporter(lambda label, percent: seen.append((label, percent)))

    report("parse", 0.0)
    report("parse", 1.0)
    report("semantics", 0.5)
    report("semantics", 1.0)
    for key, _, _ in ANALYSIS_STAGES:
        report(key, 1.0)

    percents = [percent for _, percent in seen]
    assert percents == sorted(percents), percents
    assert percents[0] == 0.0
    assert percents[-1] == 100.0
    assert seen[0][0] == "Parsing text with spaCy"


def test_partial_stage_reports_are_clamped():
    seen = []
    report = ProgressReporter(lambda label, percent: seen.append(percent))

    report("parse", -5)
    report("parse", 99)

    assert seen[0] == 0.0
    assert max(seen) <= 100.0


def test_analyser_reports_parse_then_extract_stages():
    seen = []
    StyleAnalyser("One sentence here.", on_progress=lambda label, percent: seen.append(label))

    assert seen[0] == "Parsing text with spaCy"
    assert "Extracting tokens and sentences" in seen


def test_analyze_linguistic_style_reports_every_stage():
    seen = []
    analyze_linguistic_style(
        "This is a short sample. It has two sentences.",
        on_progress=lambda label, percent: seen.append((label, percent)),
    )

    reported = [label for label, _ in seen]
    for _, label, _ in ANALYSIS_STAGES:
        assert label in reported, label
    assert seen[-1][1] == 100.0


def test_progress_callback_is_not_required():
    # The pre-existing call signature keeps working unchanged.
    with pytest.raises(TypeError):
        analyze_linguistic_style()  # text is still required
