"""Data dictionary for the linguistic style metrics produced by ``analyze_linguistic_style``.

The keys here mirror the keys returned by :func:`copyme.analyser.analyze_linguistic_style`
so that consumers can join the computed metrics 1:1 with their definitions when building
prompts for downstream LLMs.
"""

LINGUISTIC_STYLE_METRICS = {
    # --- Quantitative ---
    "type_token_ratio": {
        "description": (
            "The ratio of unique types (distinct words) to total tokens (total words). "
            "It measures lexical diversity but is highly sensitive to text length "
            "(decreasing as text length increases)."
        ),
        "data_type": "float",
        "constraints": {"min": 0.0, "max": 1.0},
        "typical_range": "0.3 (long texts) to 0.7 (short texts)",
    },
    "mean_length_of_sentence": {
        "description": (
            "The average number of words per sentence. Higher values correlate with "
            "formal academic writing (approx. 20+ words) and syntactic complexity."
        ),
        "data_type": "float",
        "constraints": {"min": 1.0},
        "typical_range": "15.0 - 25.0",
    },
    "punctuation_density": {
        "description": (
            "The frequency of punctuation marks per 1,000 words. Variations reflect "
            "syntactic pacing; low density suggests run-on sentences or spoken style, "
            "while high density implies complex clause structures."
        ),
        "data_type": "float",
        "constraints": {"min": 0.0},
        "typical_range": "100.0 - 150.0",
    },
    "discourse_marker_density": {
        "description": (
            "The frequency of discourse markers (e.g., 'however', 'so', 'well') per "
            "1,000 words. Rates above 50/1,000 are typical of casual spoken "
            "conversation; academic texts typically feature lower rates (<15/1,000)."
        ),
        "data_type": "float",
        "constraints": {"min": 0.0},
        "typical_range": "10.0 - 60.0",
    },
    "hapax_legomena_ratio": {
        "description": (
            "The proportion of words appearing exactly once in the text relative to "
            "the total vocabulary size. A primary indicator of descriptive richness "
            "and vocabulary breadth."
        ),
        "data_type": "float",
        "constraints": {"min": 0.0, "max": 1.0},
        "typical_range": "0.40 - 0.60",
    },
    "formulaic_density": {
        "description": (
            "The proportion of the text comprised of recurrent 2-gram to 4-gram "
            "sequences (lexical bundles). High values indicate reliance on formulaic "
            "language, cliches, or 'crutch' phrases."
        ),
        "data_type": "float",
        "constraints": {"min": 0.0, "max": 1.0},
        "typical_range": "0.10 - 0.30",
    },
    "modal_hedging_ratio": {
        "description": (
            "The ratio of epistemic modality markers (e.g., 'could', 'may', "
            "'possibly') to total assertions. Measures the author's degree of "
            "certainty or tentativeness (common in scientific discussion sections)."
        ),
        "data_type": "float",
        "constraints": {"min": 0.0, "max": 1.0},
        "typical_range": "0.05 - 0.20",
    },
    "function_word_frequency": {
        "description": (
            "A normalized distribution of function words (prepositions, "
            "conjunctions, pronouns, determiners). These high-frequency, "
            "content-independent items are reliable markers for authorship "
            "attribution (stylometry)."
        ),
        "data_type": "dict[str, float]",
        "constraints": {"value_min": 0.0, "value_max": 1.0},
    },
    "flesch_reading_ease": {
        "description": (
            "A standardized readability score based on average sentence length and "
            "average syllables per word. Scores 90-100 are 'Very Easy'; scores 0-30 "
            "are 'Very Difficult' (academic/professional)."
        ),
        "data_type": "float",
        "constraints": {"min": -20.0, "max": 120.0},
        "typical_range": "30.0 - 70.0",
    },

    # --- Qualitative assessments derived from the quantitative metrics above ---
    "type_token_ratio_assessment": {
        "description": "Categorical interpretation of type_token_ratio.",
        "data_type": "str",
        "allowed_values": ["repetitive", "standard", "diverse"],
    },
    "mean_length_of_sentence_assessment": {
        "description": "Categorical interpretation of mean_length_of_sentence.",
        "data_type": "str",
        "allowed_values": ["short/telegraphic", "standard", "complex/elaborate"],
    },
    "punctuation_density_assessment": {
        "description": "Categorical interpretation of punctuation_density.",
        "data_type": "str",
        "allowed_values": ["sparse", "balanced", "heavily punctuated"],
    },
    "discourse_marker_density_assessment": {
        "description": "Categorical interpretation of discourse_marker_density.",
        "data_type": "str",
        "allowed_values": ["formal/polished", "natural", "conversational"],
    },
    "hapax_legomena_ratio_assessment": {
        "description": "Categorical interpretation of hapax_legomena_ratio.",
        "data_type": "str",
        "allowed_values": ["basic/repetitive", "rich", "unique/creative"],
    },
    "formulaic_density_assessment": {
        "description": "Categorical interpretation of formulaic_density.",
        "data_type": "str",
        "allowed_values": ["original", "standard", "highly formulaic"],
    },
    "modal_hedging_ratio_assessment": {
        "description": "Categorical interpretation of modal_hedging_ratio.",
        "data_type": "str",
        "allowed_values": ["assertive/direct", "balanced", "tentative/hedged"],
    },
    "flesch_reading_ease_assessment": {
        "description": "Categorical interpretation of flesch_reading_ease.",
        "data_type": "str",
        "allowed_values": [
            "very difficult/technical",
            "difficult",
            "easy/standard",
            "very easy",
        ],
    },

    # --- Higher-order qualitative judgements ---
    "lexical_sophistication": {
        "description": (
            "Categorical assessment of vocabulary rarity based on word-length "
            "heuristics (proxy for academic / specialised vocabulary)."
        ),
        "data_type": "str",
        "allowed_values": [
            "basic",
            "intermediate",
            "advanced",
            "specialized/technical",
        ],
    },
    "syntactic_variety": {
        "description": (
            "Assessment of the variation in sentence structures (simple, compound, "
            "complex, compound-complex), proxied by the standard deviation of "
            "sentence lengths."
        ),
        "data_type": "str",
        "allowed_values": ["repetitive", "standard", "varied", "complex"],
    },
    "cohesive_harmony": {
        "description": (
            "A measure of the interaction between cohesive chains (identity chains "
            "and similarity chains) that facilitate text continuity, as defined by "
            "Ruqaiya Hasan. Approximated via noun-overlap between adjacent sentences."
        ),
        "data_type": "str",
        "allowed_values": ["fragmented", "loose", "coherent", "highly_integrated"],
    },
    "rhetorical_intent": {
        "description": (
            "The primary communicative purpose of the text, influencing the choice "
            "of stance and register."
        ),
        "data_type": "str",
        "allowed_values": [
            "informative",
            "persuasive",
            "expository",
            "narrative",
            "descriptive",
            "instructional",
        ],
    },
    "genre_alignment": {
        "description": (
            "The extent to which the text's stylistic features match the "
            "prototypical conventions of its intended genre."
        ),
        "data_type": "str",
        "allowed_values": [
            "academic",
            "legal",
            "literary_fiction",
            "journalistic",
            "technical_manual",
            "conversational_speech",
        ],
    },

    # --- Words data ---
    "common_vocabulary": {
        "description": "The author's most frequently used words (lower-cased, top 10).",
        "data_type": "list[str]",
    },
    "frequent_phrases": {
        "description": (
            "The author's most frequently repeated 2-4 word phrases. These are the "
            "'crutch' phrases or signature collocations that strongly mark the voice."
        ),
        "data_type": "list[str]",
    },
}


PRE_PROMPT_INSTRUCTION = (
    "You are about to write on behalf of the author profiled above. Use the metric "
    "dictionary in section 1 to interpret the computed values in section 2, then "
    "produce text that matches the author's linguistic fingerprint:\n"
    "- Mirror their lexical diversity, sentence length, and punctuation cadence.\n"
    "- Respect their rhetorical intent, genre alignment, and level of formality "
    "(discourse markers, hedging).\n"
    "- Re-use their common vocabulary and signature phrases where natural, without "
    "over-repeating to the point of parody.\n"
    "- Preserve their idiosyncrasies (e.g. hedging style, cohesive harmony, "
    "syntactic variety) rather than smoothing them into generic prose.\n"
    "Treat the profile as a target style guide. When the user asks you to write "
    "anything, default to writing in this voice unless they explicitly override it."
)
