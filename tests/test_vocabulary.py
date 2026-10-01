"""Tests for percentile-based vocabulary selection and the parse/derive split."""

import time
from collections import Counter

import copyme.analyser as analyser_module

from copyme import (
    DEFAULT_VOCABULARY_PERCENTILE,
    StyleAnalyser,
    analyze_linguistic_style,
    build_pre_prompt,
    build_profile,
    summarise_vocabulary,
    top_fraction,
)

TEXT = (
    "The river runs north. The river runs fast. The river runs cold. "
    "A heron waits. A heron watches. Another heron lands. "
    "Silence returns to the water."
)


# --- top_fraction ---

def test_top_fraction_keeps_the_most_frequent_share():
    counts = Counter({"a": 5, "b": 4, "c": 3, "d": 2, "e": 1})

    assert top_fraction(counts, 20) == [("a", 5)]
    assert top_fraction(counts, 40) == [("a", 5), ("b", 4)]
    assert top_fraction(counts, 100) == counts.most_common()


def test_top_fraction_ranks_by_frequency_not_insertion():
    counts = Counter()
    counts.update(["rare", "common", "common", "common"])

    assert top_fraction(counts, 50) == [("common", 3)]


def test_top_fraction_never_returns_empty_for_a_non_empty_text():
    counts = Counter({"only": 1})

    assert top_fraction(counts, 1) == [("only", 1)]
    assert top_fraction(counts, 0) == [("only", 1)]


def test_top_fraction_of_empty_counts_is_empty():
    assert top_fraction(Counter(), 20) == []


def test_top_fraction_clamps_out_of_range_percentiles():
    counts = Counter({"a": 3, "b": 2, "c": 1})

    assert top_fraction(counts, 250) == counts.most_common()
    assert top_fraction(counts, -50) == top_fraction(counts, 0)


def test_top_fraction_is_monotonic_as_the_slider_rises():
    counts = Counter({f"w{i}": 100 - i for i in range(40)})

    previous = []
    for percentile in range(1, 101):
        current = top_fraction(counts, percentile)
        assert current[:len(previous)] == previous, percentile
        previous = current


def test_top_fraction_is_deterministic_for_tied_counts():
    counts = Counter()
    counts.update(["b", "a", "c"])  # equal counts, insertion order b, a, c

    assert top_fraction(counts, 100) == [("b", 1), ("a", 1), ("c", 1)]
    assert top_fraction(counts, 100) == top_fraction(counts, 100)


# --- summarise_vocabulary ---

def test_summarise_vocabulary_truncates_words_and_phrases_independently():
    words = Counter({"a": 9, "b": 8, "c": 7, "d": 6, "e": 5})
    phrases = Counter({"x y": 4, "y z": 3, "z w": 2, "w v": 1})

    summary = summarise_vocabulary(words, phrases, 40)

    assert summary["common_vocabulary"] == [("a", 9), ("b", 8)]
    assert summary["frequent_phrases"] == [("x y", 4), ("y z", 3)]


def test_summarise_vocabulary_handles_missing_phrases():
    summary = summarise_vocabulary(Counter({"a": 2}), Counter(), 50)

    assert summary["common_vocabulary"] == [("a", 2)]
    assert summary["frequent_phrases"] == []


def test_default_percentile_is_twenty():
    assert DEFAULT_VOCABULARY_PERCENTILE == 20.0
    assert summarise_vocabulary(Counter(), Counter()) == {
        "common_vocabulary": [],
        "frequent_phrases": [],
    }


def test_resummarising_stays_fast_for_a_large_vocabulary():
    words = Counter({f"w{i}": 1_000 - i for i in range(20_000)})
    phrases = Counter({f"p{i}": 500 - (i % 500) for i in range(20_000)})

    started = time.perf_counter()
    summarise_vocabulary(words, phrases, 20)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5, f"resummarising took {elapsed:.3f}s"


# --- StyleAnalyser surface ---

def test_analyzer_exposes_lowercased_word_counts():
    analyzer = StyleAnalyser("The river runs. The river runs.")

    assert analyzer.word_counts["the"] == 2
    assert analyzer.word_counts["river"] == 2
    assert analyzer.word_counts["The"] == 0


# --- build_profile ---

def test_build_profile_never_calls_spacy(monkeypatch):
    analyzer = StyleAnalyser(TEXT)

    class NoParse:
        """Stands in for the SpaCy pipeline but refuses to parse anything."""

        max_length = analyser_module.nlp.max_length

        def __call__(self, *args, **kwargs):
            raise AssertionError("build_profile must reuse the cached parse")

    monkeypatch.setattr(analyser_module, "nlp", NoParse())

    results = build_profile(analyzer)

    assert results["words"]["common_vocabulary"]
    assert results["limits"]["max_length"] == NoParse.max_length


def test_build_profile_defaults_to_the_percentile_slice():
    analyzer = StyleAnalyser(TEXT)

    results = build_profile(analyzer)

    expected = summarise_vocabulary(
        analyzer.word_counts, analyzer.repeated_counts, DEFAULT_VOCABULARY_PERCENTILE
    )
    assert results["words"]["common_vocabulary"] == [
        term for term, _ in expected["common_vocabulary"]
    ]
    assert results["words"]["frequent_phrases"] == [
        term for term, _ in expected["frequent_phrases"]
    ]


def test_build_profile_with_none_restores_the_legacy_top_ten():
    analyzer = StyleAnalyser(TEXT)

    results = build_profile(analyzer, vocabulary_percentile=None)

    assert results["words"]["common_vocabulary"] == analyzer.get_common_vocabulary()
    assert results["words"]["frequent_phrases"] == analyzer.get_frequent_phrases()
    assert len(results["words"]["common_vocabulary"]) <= 10


def test_build_profile_reuses_the_analyzer_without_mutating_it():
    analyzer = StyleAnalyser(TEXT)
    before = dict(analyzer.word_counts)

    build_profile(analyzer, vocabulary_percentile=100)
    build_profile(analyzer, vocabulary_percentile=5)

    assert dict(analyzer.word_counts) == before


# --- end to end ---

def test_analyze_linguistic_style_forwards_the_percentile():
    narrow = analyze_linguistic_style(TEXT, vocabulary_percentile=10)
    wide = analyze_linguistic_style(TEXT, vocabulary_percentile=100)

    narrow_words = narrow["words"]["common_vocabulary"]
    wide_words = wide["words"]["common_vocabulary"]

    assert narrow["quantitative"] == wide["quantitative"]
    assert len(narrow_words) <= len(wide_words)
    assert wide_words[:len(narrow_words)] == narrow_words


def test_pre_prompt_follows_the_percentile():
    narrow = build_pre_prompt(analyze_linguistic_style(TEXT, vocabulary_percentile=5))
    wide = build_pre_prompt(analyze_linguistic_style(TEXT, vocabulary_percentile=100))

    assert narrow != wide
    assert len(narrow) < len(wide)
