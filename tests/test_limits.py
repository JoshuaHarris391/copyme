"""Tests for the temporary-memory budget and input-length limits."""

import pytest

from copyme import (
    CHARS_PER_GB,
    DEFAULT_MEMORY_GB,
    StyleAnalyser,
    TextTooLongError,
    analyze_linguistic_style,
    configure_memory_budget,
    get_max_length,
    max_length_for_memory,
    memory_budget_from_env,
    memory_for_length,
)


@pytest.fixture(autouse=True)
def restore_budget():
    """Leave ``nlp.max_length`` as it was found."""
    original = get_max_length()
    yield
    configure_memory_budget(original / CHARS_PER_GB)


def test_default_budget_is_two_gigabytes():
    assert DEFAULT_MEMORY_GB == 2.0
    assert max_length_for_memory(DEFAULT_MEMORY_GB) == 200_000


def test_import_time_limit_uses_the_default_budget():
    # The module configures nlp.max_length from the default at import time.
    assert get_max_length() == 200_000


def test_max_length_for_memory_scales_with_budget():
    assert max_length_for_memory(10) == 1_000_000
    assert max_length_for_memory(22.53) == 2_253_000
    assert max_length_for_memory(0.5) == 50_000


def test_max_length_for_memory_never_returns_zero():
    assert max_length_for_memory(0) == 1


def test_memory_for_length_is_inverse_of_max_length_for_memory():
    assert memory_for_length(2_253_363) == 22.53
    assert memory_for_length(max_length_for_memory(25)) >= 24.99


def test_configure_memory_budget_sets_nlp_max_length():
    assert configure_memory_budget(5) == 500_000
    assert get_max_length() == 500_000


def test_configure_memory_budget_rejects_non_numeric():
    with pytest.raises(ValueError, match="memory_gb must be a number"):
        configure_memory_budget("lots")


def test_memory_budget_from_env_defaults_and_reads(monkeypatch):
    monkeypatch.delenv("COPYME_MEMORY_GB", raising=False)
    assert memory_budget_from_env() == DEFAULT_MEMORY_GB

    monkeypatch.setenv("COPYME_MEMORY_GB", "24")
    assert memory_budget_from_env() == 24.0

    monkeypatch.setenv("COPYME_MEMORY_GB", "not-a-number")
    assert memory_budget_from_env() == DEFAULT_MEMORY_GB


def test_oversized_text_raises_with_actionable_message():
    configure_memory_budget(0.01)  # 1,000 characters
    text = "a" * 1_500

    with pytest.raises(TextTooLongError) as excinfo:
        StyleAnalyser(text)

    message = str(excinfo.value)
    assert "1,500 characters" in message
    assert "1,000 characters" in message
    assert "configure_memory_budget" in message
    assert "COPYME_MEMORY_GB" in message


def test_text_too_long_is_a_value_error():
    # Existing callers that catch ValueError must keep working.
    assert issubclass(TextTooLongError, ValueError)


def test_analyze_reports_limits_for_accepted_text():
    text = "This is a short sample. It has two sentences."
    results = analyze_linguistic_style(text)
    limits = results["limits"]

    assert limits["text_length"] == len(text)
    assert limits["max_length"] == get_max_length()
    assert limits["memory_budget_gb"] == memory_for_length(get_max_length())


def test_analyze_honours_explicit_memory_budget():
    configure_memory_budget(10)
    results = analyze_linguistic_style("A short sample.", memory_gb=1)

    assert results["limits"]["max_length"] == 100_000
    assert results["limits"]["memory_budget_gb"] == 1.0
