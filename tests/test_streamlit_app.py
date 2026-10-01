"""End-to-end smoke tests for the Streamlit UI's length handling."""

from streamlit.testing.v1 import AppTest

from copyme import analyze_linguistic_style, build_pre_prompt, count_tokens

APP = "streamlit_app.py"
TIMEOUT = 180

# 9 words, all distinct, and no repeated n-grams.
SAMPLE = "This is a short sample. It has two sentences."


def _app():
    return AppTest.from_file(APP, default_timeout=TIMEOUT).run()


def test_sidebar_reports_max_length_for_budget():
    at = _app()
    assert list(at.exception) == []

    at.sidebar.number_input[0].set_value(3.0).run()

    assert at.sidebar.metric[0].label == "Maximum text length"
    assert at.sidebar.metric[0].value == "300,000 characters"


def test_oversized_input_shows_error_instead_of_crashing():
    at = _app()
    at.sidebar.number_input[0].set_value(1.0)   # 100,000 character limit
    at.text_area[0].set_value("word " * 30_000)  # 150,000 characters
    at.run()
    at.button[0].click().run()

    assert list(at.exception) == []
    assert not any(s.value == "Quantitative Metrics" for s in at.subheader)

    errors = [e.value for e in at.error]
    assert errors, "expected an error message for oversized input"
    assert "this input needs about 1.50 GB" in errors[0]
    assert "Temporary memory budget" in errors[0]


def test_vocabulary_slider_defaults_to_twenty_percent():
    at = _app()
    assert list(at.exception) == []

    slider = at.sidebar.slider[0]
    assert slider.label == "Keep the most frequent (%)"
    assert slider.value == 20
    assert (slider.min, slider.max) == (1.0, 100.0)


def test_vocabulary_caption_reports_the_slice():
    at = _app()
    at.text_area[0].set_value(SAMPLE)
    at.button[0].click().run()

    assert list(at.exception) == []
    assert any(
        c.value == "Most frequent 20% of distinct terms: 2 of 9 words and 0 of 0 phrases."
        for c in at.caption
    )


def test_vocabulary_slider_rederives_without_reparsing():
    at = _app()
    at.text_area[0].set_value(SAMPLE)
    at.button[0].click().run()

    assert len(at.status) == 1  # the parse ran
    narrow = at.dataframe[0].value
    assert len(narrow) == 2

    at.sidebar.slider[0].set_value(100).run()

    # No parse ran on this rerun, so no status container was created...
    assert list(at.status) == []
    # ...yet the results were re-derived: the slider moved from 20% to 100%.
    wide = at.dataframe[0].value
    assert len(wide) == 9
    assert list(wide["term"])[:len(narrow)] == list(narrow["term"])


def test_changing_the_text_drops_the_cached_parse():
    at = _app()
    at.text_area[0].set_value(SAMPLE)
    at.button[0].click().run()
    assert any(s.value == "Quantitative Metrics" for s in at.subheader)

    at.text_area[0].set_value("Something else entirely. It is different.")
    at.run()

    assert list(at.exception) == []
    assert "Quantitative Metrics" not in [s.value for s in at.subheader]


def test_pre_prompt_token_indicator_matches_the_library():
    at = _app()
    at.text_area[0].set_value(SAMPLE)
    at.button[0].click().run()

    assert list(at.exception) == []
    indicator = [m.value for m in at.markdown if "Pre-prompt size" in m.value]
    assert len(indicator) == 1

    expected_prompt = build_pre_prompt(
        analyze_linguistic_style(SAMPLE, vocabulary_percentile=20)
    )
    expected_count, _ = count_tokens(expected_prompt)
    assert f"{len(expected_prompt):,} characters" in indicator[0]
    assert f"{expected_count:,} tokens" in indicator[0]


def test_token_indicator_follows_the_vocabulary_slider():
    at = _app()
    at.text_area[0].set_value(open("README.md").read())
    at.button[0].click().run()

    def tokens():
        value = [m.value for m in at.markdown if "Pre-prompt size" in m.value][0]
        return int(value.split("**")[1].replace(",", "").split()[0])

    narrow = tokens()
    at.sidebar.slider[0].set_value(100).run()

    # No re-parse, but a wider vocabulary makes the pre-prompt bigger.
    assert list(at.status) == []
    assert tokens() > narrow


def test_within_budget_input_renders_sections():
    at = _app()
    at.text_area[0].set_value(SAMPLE)
    at.button[0].click().run()

    assert list(at.exception) == []
    sections = [s.value for s in at.subheader]
    assert "Quantitative Metrics" in sections
    assert "Vocabulary & Phrases" in sections
    assert "Copyable Pre-Prompt" in sections
    assert any(c.value.startswith("Analysed 45 characters") for c in at.caption)


def test_status_indicator_reports_completion():
    at = _app()
    at.text_area[0].set_value(SAMPLE)

    # Before running, the status container has not been created.
    assert list(at.status) == []

    at.button[0].click().run()

    assert list(at.exception) == []
    assert len(at.status) == 1
    status = at.status[0]
    assert status.state == "complete"
    assert status.label.startswith("Analysis complete in ")
    # The status container holds a progress element while the analysis runs.
    assert len(at.get("progress")) == 1


def test_status_indicator_reports_failure():
    at = _app()
    at.sidebar.number_input[0].set_value(1.0)   # 100,000 character limit
    at.text_area[0].set_value("word " * 30_000)  # 150,000 characters
    at.run()
    at.button[0].click().run()

    assert list(at.exception) == []
    assert len(at.status) == 1
    assert at.status[0].state == "error"
    assert at.status[0].label == "Analysis failed"
    assert at.error, "expected an error message for oversized input"
