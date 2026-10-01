"""Tests for the pre-prompt token indicator."""

import copyme.analyser as analyser_module

from copyme import (
    StyleAnalyser,
    analyze_linguistic_style,
    build_pre_prompt,
    build_profile,
    count_tokens,
    estimate_tokens,
)

TEXT = (
    "The river runs north. The river runs fast. The river runs cold. "
    "A heron waits. A heron watches. Another heron lands. "
    "Silence returns to the water."
)


# --- estimate_tokens ---

def test_estimate_tokens_counts_words_and_symbols():
    assert estimate_tokens("Hello, world!") == 4
    assert estimate_tokens("The river runs.") == 4


def test_estimate_tokens_splits_digits_from_words():
    assert estimate_tokens("abc123") == 2
    assert estimate_tokens("version 3.8.11") == 6


def test_estimate_tokens_of_empty_input_is_zero():
    assert estimate_tokens("") == 0
    assert estimate_tokens("   ") == 1  # any real text encodes to >= 1 token


def test_estimate_tokens_sits_between_word_and_character_counts():
    words = len(TEXT.split())
    estimate = estimate_tokens(TEXT)

    assert words <= estimate <= len(TEXT)


# --- count_tokens ---

def test_count_tokens_falls_back_to_the_estimate(monkeypatch):
    monkeypatch.setattr(analyser_module, "_exact_encoder", lambda: None)

    count, exact = count_tokens("Hello, world!")

    assert (count, exact) == (estimate_tokens("Hello, world!"), False)


def test_count_tokens_prefers_tiktoken_when_available(monkeypatch):
    calls = []

    class FakeEncoder:
        def encode(self, text):
            calls.append(text)
            return list(text)  # one token per character, for a checkable value

    monkeypatch.setattr(analyser_module, "_exact_encoder", lambda: FakeEncoder())

    count, exact = count_tokens("abcd")

    assert (count, exact) == (4, True)
    assert calls == ["abcd"]


def test_count_tokens_of_empty_text_is_zero(monkeypatch):
    monkeypatch.setattr(analyser_module, "_exact_encoder", lambda: None)

    assert count_tokens("") == (0, False)


# --- pre-prompt indicator ---

def test_pre_prompt_token_count_is_reported_per_profile():
    results = analyze_linguistic_style(TEXT)
    pre_prompt = build_pre_prompt(results)

    count, _ = count_tokens(pre_prompt)

    assert count > 0
    assert count < len(pre_prompt)


def test_a_wider_vocabulary_share_costs_more_tokens():
    narrow = build_pre_prompt(analyze_linguistic_style(TEXT, vocabulary_percentile=5))
    wide = build_pre_prompt(analyze_linguistic_style(TEXT, vocabulary_percentile=100))

    assert count_tokens(narrow)[0] < count_tokens(wide)[0]


def test_the_token_count_is_not_embedded_in_the_pre_prompt():
    # Measuring the prompt must not change it, so the count lives in the UI only
    # rather than being written into the text that gets copied.
    pre_prompt = build_pre_prompt(build_profile(StyleAnalyser(TEXT)))

    assert "Pre-prompt size" not in pre_prompt
    assert count_tokens(pre_prompt)[0] > 0
