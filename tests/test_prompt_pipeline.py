import os
import unittest

from copyme.prompt_pipeline import (
    METRICS_REFERENCE,
    METRIC_THRESHOLDS,
    REVIEWER_SYSTEM_PROMPT,
    build_system_prompt,
    build_reviewer_prompt,
    create_chain,
    create_prompt_template,
    generate_styled_content,
    list_available_models,
    _compute_intensity,
    _compute_intensity_report,
    _build_intensity_section,
    _build_anti_patterns,
    _build_style_exemplar,
    _strip_dashes,
    FALLBACK_MODELS,
)


# --- SAMPLE PROFILE FIXTURE ---

SAMPLE_PROFILE = {
    "quantitative": {
        "type_token_ratio": 0.554,
        "mean_length_of_sentence": 15.42,
        "punctuation_density": 240.54,
        "discourse_marker_density": 78.38,
        "hapax_legomena_ratio": 0.732,
        "formulaic_density": 0.143,
        "modal_hedging_ratio": 0.21,
        "flesch_reading_ease": 85.5,
    },
    "qualitative": {
        "type_token_ratio_assessment": "standard",
        "mean_length_of_sentence_assessment": "standard",
        "punctuation_density_assessment": "heavily punctuated",
        "discourse_marker_density_assessment": "conversational",
        "hapax_legomena_ratio_assessment": "unique/creative",
        "formulaic_density_assessment": "standard",
        "modal_hedging_ratio_assessment": "tentative/hedged",
        "flesch_reading_ease_assessment": "very easy",
        "lexical_sophistication": "basic",
        "syntactic_variety": "varied",
        "cohesive_harmony": "fragmented",
        "rhetorical_intent": "informative",
        "genre_alignment": "conversational_speech",
    },
    "words": {
        "common_vocabulary": [
            "the", "me", "and", "i", "ye",
            "a", "'s", "of", "but", "were",
        ],
        "frequent_phrases": [
            "tell ye", "but i", "and the",
            "let me", "me tell",
            "ye about", "about the", "the time",
            "and me", "were and",
        ],
    },
}


# ---- Intensity computation ----


class TestComputeIntensity(unittest.TestCase):
    """Tests for _compute_intensity helper."""

    def test_above_top_threshold(self):
        label, mult = _compute_intensity(
            89.8, METRIC_THRESHOLDS["discourse_marker_density"]
        )
        self.assertEqual(label, "conversational")
        self.assertAlmostEqual(mult, 2.25, places=1)

    def test_between_thresholds(self):
        label, mult = _compute_intensity(
            20.0, METRIC_THRESHOLDS["discourse_marker_density"]
        )
        self.assertEqual(label, "natural")
        self.assertGreater(mult, 1.0)

    def test_below_all_thresholds(self):
        label, mult = _compute_intensity(
            5.0, METRIC_THRESHOLDS["discourse_marker_density"]
        )
        self.assertEqual(label, "formal/polished")
        self.assertLess(mult, 1.0)

    def test_hedging_above_threshold(self):
        label, mult = _compute_intensity(
            0.23, METRIC_THRESHOLDS["modal_hedging_ratio"]
        )
        self.assertEqual(label, "tentative/hedged")
        self.assertGreater(mult, 1.0)


class TestComputeIntensityReport(unittest.TestCase):
    """Tests for _compute_intensity_report."""

    def test_returns_all_metrics(self):
        report = _compute_intensity_report(
            SAMPLE_PROFILE["quantitative"]
        )
        metric_keys = {e["metric"] for e in report}
        for key in METRIC_THRESHOLDS:
            self.assertIn(key, metric_keys)

    def test_each_entry_has_required_keys(self):
        report = _compute_intensity_report(
            SAMPLE_PROFILE["quantitative"]
        )
        required = {
            "metric", "score", "assessment",
            "threshold", "multiplier", "directive",
        }
        for entry in report:
            self.assertTrue(
                required.issubset(entry.keys()),
                f"Missing keys in {entry}",
            )

    def test_conversational_directive_present(self):
        report = _compute_intensity_report(
            SAMPLE_PROFILE["quantitative"]
        )
        dm_entry = next(
            e for e in report
            if e["metric"] == "discourse_marker_density"
        )
        self.assertEqual(dm_entry["assessment"], "conversational")
        self.assertIn("MUST", dm_entry["directive"])

    def test_hedging_directive_present(self):
        report = _compute_intensity_report(
            SAMPLE_PROFILE["quantitative"]
        )
        hedge_entry = next(
            e for e in report
            if e["metric"] == "modal_hedging_ratio"
        )
        self.assertEqual(
            hedge_entry["assessment"], "tentative/hedged"
        )
        self.assertIn("hedge", hedge_entry["directive"].lower())


class TestBuildIntensitySection(unittest.TestCase):
    """Tests for _build_intensity_section formatting."""

    def test_contains_strength_labels(self):
        report = _compute_intensity_report(
            SAMPLE_PROFILE["quantitative"]
        )
        section = _build_intensity_section(report)
        # discourse_marker_density 78.38/40 = 1.96x -> STRONG
        self.assertIn("DIRECTIVE:", section)
        self.assertTrue(
            any(s in section for s in [
                "MILD", "MODERATE", "STRONG", "VERY STRONG"
            ])
        )


# ---- Anti-patterns ----


class TestBuildAntiPatterns(unittest.TestCase):
    """Tests for _build_anti_patterns."""

    def test_conversational_anti_pattern(self):
        result = _build_anti_patterns(
            SAMPLE_PROFILE["qualitative"], []
        )
        self.assertIn("Do NOT write in a polished", result)

    def test_hedging_anti_pattern(self):
        result = _build_anti_patterns(
            SAMPLE_PROFILE["qualitative"], []
        )
        self.assertIn(
            "Do NOT make absolute", result
        )

    def test_genre_anti_pattern(self):
        result = _build_anti_patterns(
            SAMPLE_PROFILE["qualitative"], []
        )
        self.assertIn("formal document", result)

    def test_empty_qualitative_returns_empty(self):
        result = _build_anti_patterns({}, [])
        self.assertEqual(result, "")

    def test_formal_profile_different_warnings(self):
        formal_qual = {
            "discourse_marker_density_assessment": "formal/polished",
            "modal_hedging_ratio_assessment": "assertive/direct",
        }
        result = _build_anti_patterns(formal_qual, [])
        self.assertIn("Do NOT use conversational", result)
        self.assertIn("Do NOT hedge", result)


# ---- Style exemplar ----


class TestBuildStyleExemplar(unittest.TestCase):
    """Tests for _build_style_exemplar."""

    def test_conversational_includes_markers(self):
        result = _build_style_exemplar(
            SAMPLE_PROFILE["qualitative"],
            SAMPLE_PROFILE["words"]["common_vocabulary"],
            SAMPLE_PROFILE["words"]["frequent_phrases"],
        )
        self.assertIn("Well", result)
        self.assertIn("actually", result.lower())

    def test_hedging_includes_hedge_words(self):
        result = _build_style_exemplar(
            SAMPLE_PROFILE["qualitative"],
            [], [],
        )
        self.assertIn("I think", result)

    def test_includes_phrases(self):
        result = _build_style_exemplar(
            SAMPLE_PROFILE["qualitative"],
            SAMPLE_PROFILE["words"]["common_vocabulary"],
            SAMPLE_PROFILE["words"]["frequent_phrases"],
        )
        self.assertIn("tell ye", result)

    def test_neutral_profile(self):
        result = _build_style_exemplar({}, [], [])
        self.assertIn("writing voice sounds", result)


# ---- Dash stripping ----


class TestStripDashes(unittest.TestCase):
    """Tests for _strip_dashes post-processing."""

    def test_removes_hyphens(self):
        self.assertEqual(
            _strip_dashes("well-known fact"),
            "wellknown fact",
        )

    def test_removes_em_dash(self):
        self.assertEqual(
            _strip_dashes("hello \u2014 world"),
            "hello world",
        )

    def test_removes_en_dash(self):
        self.assertEqual(
            _strip_dashes("pages 10\u201320"),
            "pages 10 20",
        )

    def test_removes_spaced_double_dash(self):
        self.assertEqual(
            _strip_dashes("this -- that"),
            "this that",
        )

    def test_no_double_spaces(self):
        result = _strip_dashes("a - b -- c")
        self.assertNotIn("  ", result)

    def test_clean_text_unchanged(self):
        self.assertEqual(
            _strip_dashes("no dashes here"),
            "no dashes here",
        )


# ---- System prompt ----


class TestBuildSystemPrompt(unittest.TestCase):
    """Tests for the full system prompt builder."""

    def setUp(self):
        self.prompt = build_system_prompt(SAMPLE_PROFILE)

    def test_contains_scribe_persona(self):
        self.assertIn("AI scribe", self.prompt)

    def test_contains_metrics_reference(self):
        self.assertIn("Type-Token Ratio", self.prompt)
        self.assertIn("Flesch Reading Ease", self.prompt)

    def test_contains_quantitative_values(self):
        self.assertIn("0.554", self.prompt)
        self.assertIn("15.42", self.prompt)
        self.assertIn("240.54", self.prompt)
        self.assertIn("78.38", self.prompt)
        self.assertIn("85.5", self.prompt)

    def test_contains_qualitative_assessments(self):
        self.assertIn("heavily punctuated", self.prompt)
        self.assertIn("conversational", self.prompt)
        self.assertIn("unique/creative", self.prompt)
        self.assertIn("tentative/hedged", self.prompt)

    def test_contains_common_vocabulary(self):
        for word in SAMPLE_PROFILE["words"]["common_vocabulary"]:
            self.assertIn(word, self.prompt)

    def test_contains_frequent_phrases(self):
        for phrase in SAMPLE_PROFILE["words"]["frequent_phrases"]:
            self.assertIn(phrase, self.prompt)

    def test_contains_intensity_section(self):
        self.assertIn("INTENSITY-CALIBRATED", self.prompt)
        self.assertIn("DIRECTIVE:", self.prompt)

    def test_contains_mandatory_rules(self):
        self.assertIn("MANDATORY STYLE RULES", self.prompt)
        self.assertIn("Discourse & Formality", self.prompt)
        self.assertIn("Hedging & Certainty", self.prompt)

    def test_contains_anti_patterns(self):
        self.assertIn("ANTI-PATTERNS", self.prompt)
        self.assertIn("Do NOT", self.prompt)

    def test_contains_style_exemplar(self):
        self.assertIn("EXAMPLE OF TARGET VOICE", self.prompt)

    def test_contains_vocabulary_mandate(self):
        self.assertIn("YOU MUST use", self.prompt)

    def test_empty_profile_does_not_crash(self):
        prompt = build_system_prompt({})
        self.assertIn("AI scribe", prompt)


# ---- Reviewer prompt ----


class TestReviewerPrompt(unittest.TestCase):
    """Tests for the reviewer system prompt and builder."""

    def test_reviewer_system_has_verdict_format(self):
        self.assertIn("VERDICT: PASS", REVIEWER_SYSTEM_PROMPT)
        self.assertIn("VERDICT:", REVIEWER_SYSTEM_PROMPT)

    def test_build_reviewer_prompt_includes_profile(self):
        prompt = build_reviewer_prompt(
            SAMPLE_PROFILE, "Test draft content."
        )
        self.assertIn("0.554", prompt)
        self.assertIn("conversational", prompt)
        self.assertIn("Test draft content.", prompt)
        self.assertIn("tell ye", prompt)


# ---- Prompt template ----


class TestPromptTemplate(unittest.TestCase):
    """Tests for the ChatPromptTemplate structure."""

    def test_template_has_expected_variables(self):
        template = create_prompt_template()
        input_vars = template.input_variables
        self.assertIn("system_prompt", input_vars)
        self.assertIn("user_input", input_vars)

    def test_template_renders(self):
        template = create_prompt_template()
        messages = template.invoke({
            "system_prompt": "Test system",
            "chat_history": [],
            "user_input": "Hello",
        })
        self.assertTrue(len(messages.messages) >= 2)


# ---- Chain creation ----


class TestCreateChain(unittest.TestCase):
    """Tests for chain creation (no API call made)."""

    def test_raises_without_key(self):
        old = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            with self.assertRaises(ValueError):
                create_chain(api_key="")
        finally:
            if old:
                os.environ["ANTHROPIC_API_KEY"] = old

    def test_chain_created_with_key(self):
        chain = create_chain(api_key="test-key-not-real")
        self.assertIsNotNone(chain)

    def test_chain_with_custom_temperature(self):
        chain = create_chain(
            api_key="test-key-not-real",
            temperature=0.5,
        )
        self.assertIsNotNone(chain)


# ---- Model listing ----


class TestListAvailableModels(unittest.TestCase):
    """Tests for list_available_models."""

    def test_invalid_key_returns_fallback(self):
        result = list_available_models("invalid-key")
        self.assertEqual(result, FALLBACK_MODELS)

    def test_empty_key_returns_fallback(self):
        result = list_available_models("")
        self.assertEqual(result, FALLBACK_MODELS)


# ---- Metrics reference ----


class TestMetricsReference(unittest.TestCase):
    """Verify the metrics doc was loaded."""

    def test_metrics_reference_loaded(self):
        self.assertIn("Type-Token Ratio", METRICS_REFERENCE)
        self.assertIn("Flesch Reading Ease", METRICS_REFERENCE)


# ---- Integration ----


@unittest.skipUnless(
    os.environ.get("ANTHROPIC_API_KEY"),
    "ANTHROPIC_API_KEY not set — skipping integration test",
)
class TestIntegration(unittest.TestCase):
    """End-to-end test (requires a valid API key)."""

    def test_generate_styled_content(self):
        result = generate_styled_content(
            profile=SAMPLE_PROFILE,
            user_prompt="Write one sentence about the weather.",
        )
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


if __name__ == "__main__":
    unittest.main()
