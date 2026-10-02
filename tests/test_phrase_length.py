"""Tests for the configurable phrase length."""

from collections import Counter

import pytest

from copyme import (
    DEFAULT_MAX_PHRASE_WORDS,
    MAX_PHRASE_WORDS,
    MIN_PHRASE_WORDS,
    StyleAnalyser,
    analyze_linguistic_style,
    build_profile,
    repeated_phrase_counts,
)
from copyme.analyser import PHRASE_METRIC_N_RANGE

# The 5-word sequence "the quick brown fox jumps" repeats three times, so it is a
# phrase at length 5 but invisible at the default length 4.
REPEATED = (
    "The quick brown fox jumps. "
    "We saw the quick brown fox jumps again. "
    "The quick brown fox jumps often."
)
LONG_PHRASE = "the quick brown fox jumps"


def _words(text):
    return [word for word in text.replace(".", "").split()]


# --- repeated_phrase_counts ---

def test_only_repeats_are_counted():
    counts = repeated_phrase_counts(["a", "b", "a", "b", "c"], 2)

    assert counts == Counter({"a b": 2})
    assert "b c" not in counts  # seen once: not a phrase the author leans on


def test_phrase_length_bounds_are_respected():
    words = _words(REPEATED)

    bigrams = repeated_phrase_counts(words, 2)
    default = repeated_phrase_counts(words, DEFAULT_MAX_PHRASE_WORDS)
    longer = repeated_phrase_counts(words, 5)

    assert all(len(phrase.split()) == 2 for phrase in bigrams)
    assert {len(phrase.split()) for phrase in default} <= set(PHRASE_METRIC_N_RANGE)
    assert LONG_PHRASE not in default
    assert longer[LONG_PHRASE] == 3


def test_a_shorter_range_is_a_subset_of_a_longer_one():
    words = _words(REPEATED)

    assert set(repeated_phrase_counts(words, 2)) <= set(
        repeated_phrase_counts(words, 5)
    )


def test_lengthening_the_range_keeps_the_shorter_phrases():
    words = _words(REPEATED)

    at_four = repeated_phrase_counts(words, 4)
    at_six = repeated_phrase_counts(words, 6)

    for phrase, count in at_four.items():
        assert at_six[phrase] == count


def test_empty_input_has_no_phrases():
    assert repeated_phrase_counts([], 4) == Counter()


def test_too_short_a_text_has_no_phrases():
    # No 2-gram fits in a one-word text.
    assert repeated_phrase_counts(["solo"], 4) == Counter()


def test_invalid_ranges_are_rejected():
    with pytest.raises(ValueError, match="max_words must be at least min_words"):
        repeated_phrase_counts(["a", "b", "a", "b"], max_words=2, min_words=3)

    with pytest.raises(ValueError, match="min_words must be at least 1"):
        repeated_phrase_counts(["a", "b", "a", "b"], max_words=3, min_words=0)


def test_default_length_matches_the_metric_range():
    assert DEFAULT_MAX_PHRASE_WORDS == max(PHRASE_METRIC_N_RANGE)
    assert (MIN_PHRASE_WORDS, MAX_PHRASE_WORDS) == (2, 6)


# --- StyleAnalyser.phrase_counts ---

def test_default_phrase_counts_match_the_metric_counts():
    analyzer = StyleAnalyser(REPEATED)

    assert analyzer.phrase_counts() == analyzer.repeated_counts


def test_phrase_counts_are_memoised_per_range():
    analyzer = StyleAnalyser(REPEATED)

    assert analyzer.phrase_counts(5) is analyzer.phrase_counts(5)
    assert analyzer.phrase_counts(5) is not analyzer.phrase_counts(4)


# --- build_profile ---

def test_default_phrase_list_matches_the_legacy_output():
    analyzer = StyleAnalyser(REPEATED)

    words = build_profile(analyzer, vocabulary_percentile=None)["words"]

    assert words["frequent_phrases"] == analyzer.get_frequent_phrases()


def test_phrase_length_changes_the_phrase_list():
    analyzer = StyleAnalyser(REPEATED)

    short = build_profile(
        analyzer, vocabulary_percentile=100, max_phrase_words=4
    )["words"]["frequent_phrases"]
    long = build_profile(
        analyzer, vocabulary_percentile=100, max_phrase_words=6
    )["words"]["frequent_phrases"]

    assert LONG_PHRASE not in short
    assert LONG_PHRASE in long


def test_phrase_length_changes_the_legacy_phrase_list_too():
    analyzer = StyleAnalyser(REPEATED)

    phrases = build_profile(
        analyzer, vocabulary_percentile=None, max_phrase_words=5
    )["words"]["frequent_phrases"]

    assert LONG_PHRASE in phrases


def test_phrase_length_leaves_formulaic_density_alone():
    # The metric is pinned to PHRASE_METRIC_N_RANGE: a slider must not move a
    # scored assessment that profiles are compared on.
    analyzer = StyleAnalyser(REPEATED)

    densities = {
        build_profile(analyzer, max_phrase_words=length)["quantitative"][
            "formulaic_density"
        ]
        for length in (2, 4, 6)
    }

    assert len(densities) == 1
    assert densities == {analyzer.get_formulaic_density()}


def test_limits_record_the_phrase_length():
    results = analyze_linguistic_style(REPEATED, max_phrase_words=5)

    assert results["limits"]["max_phrase_words"] == 5


def test_phrase_length_reaches_the_top_level_api():
    results = analyze_linguistic_style(
        REPEATED, vocabulary_percentile=100, max_phrase_words=5
    )

    assert LONG_PHRASE in results["words"]["frequent_phrases"]
