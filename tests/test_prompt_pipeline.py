import os
import unittest

from copyme.prompt_pipeline import (
    METRICS_REFERENCE,
    build_system_prompt,
    create_chain,
    create_prompt_template,
    generate_styled_content,
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
        "function_word_frequency": {
            "prepositions": 0.067,
            "conjunctions": 0.045,
            "pronouns": 0.106,
            "determiners": 0.091,
        },
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
            "tell ye", "but i", "and the", "let me", "me tell",
            "ye about", "about the", "the time", "and me", "were and",
        ],
    },
}


class TestBuildSystemPrompt(unittest.TestCase):
    """Tests for the system prompt builder."""

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

    def test_contains_calibration_instructions(self):
        self.assertIn("quantitative", self.prompt.lower())
        self.assertIn("qualitative", self.prompt.lower())
        self.assertIn("how much", self.prompt.lower())

    def test_empty_profile_does_not_crash(self):
        prompt = build_system_prompt({})
        self.assertIn("AI scribe", prompt)


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


class TestMetricsReference(unittest.TestCase):
    """Verify the metrics doc was loaded."""

    def test_metrics_reference_loaded(self):
        self.assertIn("Type-Token Ratio", METRICS_REFERENCE)
        self.assertIn("Flesch Reading Ease", METRICS_REFERENCE)


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
