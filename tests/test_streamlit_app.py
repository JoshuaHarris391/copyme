"""End-to-end smoke tests for the Streamlit UI's length handling."""

from streamlit.testing.v1 import AppTest

APP = "streamlit_app.py"
TIMEOUT = 180


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


def test_within_budget_input_renders_sections():
    at = _app()
    at.text_area[0].set_value("This is a short sample. It has two sentences.")
    at.button[0].click().run()

    assert list(at.exception) == []
    sections = [s.value for s in at.subheader]
    assert "Quantitative Metrics" in sections
    assert "Copyable Pre-Prompt" in sections
    assert any(c.value.startswith("Analysed 45 characters") for c in at.caption)


def test_status_indicator_reports_completion():
    at = _app()
    at.text_area[0].set_value("This is a short sample. It has two sentences.")

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
