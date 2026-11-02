"""The scorer: telling the user whether it worked.

No version of copyme has done this before. A user pasted a pre-prompt, read the
output and judged by feel.

Two properties matter more than any individual measurement. The scorer must be
**pure** -- no model, no network, no writes -- because it is the one part of
copyme a user might run in a loop. And a text scored against its own profile
must be in band on every rule, because a scorer that fails its own author is
measuring something other than what the rules asked for.
"""

import copyme.scorer as scorer_module
from copyme.scorer import COPY_SPAN_WORDS, FOOTER, find_copied_spans, score


def test_the_sample_is_in_band_against_its_own_profile(london, london_profile):
    """Spec 03's gate, and the scorer's definition of correct.

    Every band is centred on the author's own value and widened by the author's
    own passage-to-passage variation. If the text the profile was built from
    fell outside one of those bands, the band would be describing a writer who
    does not exist, and every drift reported against it would be noise.
    """
    report = score(london.text, london_profile)

    assert report.in_band == 1.0
    assert all(drift.verdict == "in band" for drift in report.drifts)


def test_in_band_is_exactly_one_only_when_nothing_drifted(london, london_profile):
    """The headline number has to mean precisely what it says.

    ``in_band`` is the share of rules met. It reads as a pass mark, so 100% must
    be unachievable while any rule is still broken -- and a clearly off-voice
    text must not score 100%.
    """
    own = score(london.text, london_profile)
    assert own.in_band == 1.0
    assert [d for d in own.drifts if d.verdict != "in band"] == []

    # Assistant-register prose, about as far from London as the fixtures get.
    off_voice = (
        "It is important to note that there are several factors which may "
        "influence the outcome of this process, and each of them should be "
        "carefully considered before any decision is reached. Additionally, it "
        "would generally be advisable to establish a clear understanding of "
        "the underlying requirements, since an approach that works well at a "
        "small scale may not perform adequately as volume grows over time."
    )
    drifted = score(off_voice, london_profile)

    assert drifted.in_band < 1.0
    assert any(drift.verdict != "in band" for drift in drifted.drifts)


def test_a_drift_note_reads_as_a_correction_not_a_measurement(london_profile):
    """The summary feeds the contrastive block, so its wording is functional.

    "sentences 40% longer than the author" can be handed to a model as a
    correction. "sentence_length_median: 24.0 (expected 17.0)" has to be
    rewritten first, and anything that has to be rewritten drifts out of step
    with the thing it was derived from.
    """
    off_voice = (
        "It is important to note that there are a number of considerations "
        "which should be borne in mind, each of which may bear upon the "
        "eventual outcome in ways that are not immediately apparent to those "
        "involved in the earlier stages of the process."
    )
    report = score(off_voice, london_profile)

    for drift in report.drifts:
        assert drift.note.strip()
        # No metric names and no bare numbers-with-colons.
        assert drift.feature not in drift.note
        assert ":" not in drift.note

    assert "%" in report.summary or "than the author" in report.summary


def test_a_twelve_word_copied_span_is_flagged_and_an_eleven_word_one_is_not():
    """The threshold is tested at its boundary, because that is where it matters.

    The prompt tells the model not to reproduce the author's phrases, and until
    now nothing checked. Twelve words is long enough that ordinary English
    collocations do not trip it, and short enough to catch a lifted sentence.
    """
    source = (
        "the quick brown fox jumps over the lazy dog and then it runs away "
        "across the field"
    )
    eleven = " ".join(source.split()[:11])
    twelve = " ".join(source.split()[:12])

    assert find_copied_spans(eleven, [source], span=COPY_SPAN_WORDS) == []
    assert find_copied_spans(twelve, [source], span=COPY_SPAN_WORDS) != []


def test_a_copied_span_is_reported_once_at_full_length():
    """One lifted sentence is one finding, not a dozen overlapping windows.

    A naive sliding window reports every 12-word slice of a 30-word copy, which
    buries the actual information -- how much was copied -- under repetition.
    """
    source = " ".join(f"word{index}" for index in range(30))
    hits = find_copied_spans(source, [source], span=COPY_SPAN_WORDS)

    assert len(hits) == 1
    assert len(hits[0].split()) == 30


def test_copying_is_detected_across_a_change_of_punctuation():
    """A lifted sentence with the commas moved is still a lifted sentence.

    Comparing word sequences rather than characters is what makes the check
    resistant to reformatting, which a model does routinely.
    """
    source = "we walked, slowly, down the long and very empty road towards the sea"
    reflowed = "We walked slowly down the long and very empty road towards the sea."

    assert find_copied_spans(reflowed, [source], span=COPY_SPAN_WORDS) != []


def test_score_is_pure(london, london_profile, monkeypatch, tmp_path):
    """Stated as a test, not as an intention.

    ``score`` is the one function a user might call in a loop over many drafts.
    It must not open a socket, write a file or call a model -- so here the
    network is removed outright and any write is made to fail, and the score
    still has to come back.
    """
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError("score() attempted a network connection")

    def no_writes(*args, **kwargs):
        raise AssertionError("score() attempted to open a file for writing")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)

    real_open = open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            no_writes()
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded_open)

    report = score(london.text[:4_000], london_profile)
    assert report.in_band >= 0.0


def test_every_report_carries_the_footer_caveat(london, london_profile):
    """The scorer must not be read as a verdict.

    Passing every band is not the same as sounding right: the bands cover the
    habits copyme can measure, and a passage can satisfy all of them and still
    read wrongly. The footer says so in every report and every render, because
    a number without that caveat invites exactly the wrong conclusion.
    """
    report = score(london.text[:4_000], london_profile)

    assert report.footer == FOOTER
    assert "blind read" in report.footer
    assert FOOTER in report.render()
    assert report.to_dict()["footer"] == FOOTER


def test_the_report_serialises_for_the_cli(london, london_profile):
    """``copyme score --json`` is meant to be piped into something.

    Every field a caller would need has to be in the dictionary, and it has to
    contain only JSON-safe values.
    """
    import json

    report = score(london.text[:4_000], london_profile)
    payload = json.loads(json.dumps(report.to_dict()))

    assert set(payload) == {"in_band", "drifts", "copied_spans", "summary", "footer"}
    assert payload["drifts"]
    for drift in payload["drifts"]:
        assert set(drift) == {"feature", "author", "generated", "verdict", "note"}


def test_a_profile_with_no_rules_scores_as_fully_in_band(london_profile):
    """An empty rule set means nothing was asked for, so nothing can drift.

    This happens for a writer whose habits sit close to ordinary prose. The
    honest answer is 100% with no drift lines, not a division by zero.
    """
    from dataclasses import replace

    ruleless = replace(london_profile, rules=())
    report = score("Anything at all.", ruleless)

    assert report.in_band == 1.0
    assert report.drifts == []
