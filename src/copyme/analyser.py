import os
import re

import spacy
import nltk
import textstat
from empath import Empath
from collections import Counter

# --- INITIALIZATION ---

# 1. Load Spacy Model
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    print("Error: Spacy model not found. Run: python -m spacy download en_core_web_sm")
    exit()


# --- MEMORY BUDGET / INPUT LENGTH LIMITS ---

# SpaCy's parser and NER models need roughly 1 GB of temporary memory per
# 100,000 characters of input, so the character limit a document can reach is a
# direct function of how much temporary memory we are willing to allocate.
CHARS_PER_GB = 100_000

# 2 GB -> 200,000 characters. Deliberately below SpaCy's own 1,000,000-character
# default: a conservative ceiling that keeps a stray paste from asking for tens
# of gigabytes of temporary memory.
DEFAULT_MEMORY_GB = 2.0

# Budgets below this are almost certainly a mistake rather than an intent.
MIN_MEMORY_GB = 0.01


class TextTooLongError(ValueError):
    """Raised when input exceeds the configured character limit.

    Subclasses ``ValueError`` so existing ``except ValueError`` handlers (and
    the message SpaCy itself would have raised) keep working.
    """


def max_length_for_memory(memory_gb):
    """Return the number of characters that fit in ``memory_gb`` GB of temp memory.

    Args:
        memory_gb (float): Temporary memory budget in gigabytes.

    Returns:
        int: Maximum input length in characters (at least 1).
    """
    return max(1, int(memory_gb * CHARS_PER_GB))



def memory_for_length(text_length):
    """Return the temporary memory (GB) an input of ``text_length`` would need.

    This is the inverse of :func:`max_length_for_memory`.

    Args:
        text_length (int): Input length in characters.

    Returns:
        float: Estimated temporary memory in gigabytes, rounded to 2 decimals.
    """
    return round(max(0, text_length) / CHARS_PER_GB, 2)



def configure_memory_budget(memory_gb=None):
    """Set ``nlp.max_length`` from a temporary-memory budget.

    Args:
        memory_gb (float, optional): Temporary memory budget in gigabytes. When
            ``None``, the ``COPYME_MEMORY_GB`` environment variable is used,
            falling back to :data:`DEFAULT_MEMORY_GB`.

    Returns:
        int: The resulting maximum input length in characters.
    """
    if memory_gb is None:
        memory_gb = memory_budget_from_env()
    try:
        memory_gb = float(memory_gb)
    except (TypeError, ValueError):
        raise ValueError(f"memory_gb must be a number, got {memory_gb!r}") from None
    nlp.max_length = max_length_for_memory(max(memory_gb, MIN_MEMORY_GB))
    return nlp.max_length



def memory_budget_from_env():
    """Read the temporary memory budget from ``COPYME_MEMORY_GB``.

    Returns:
        float: The configured budget, or :data:`DEFAULT_MEMORY_GB` when the
            variable is unset or not a positive number.
    """
    raw = os.environ.get("COPYME_MEMORY_GB")
    if raw is None:
        return DEFAULT_MEMORY_GB
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_MEMORY_GB
    return value if value > 0 else DEFAULT_MEMORY_GB



def get_max_length():
    """Return the current maximum input length in characters (``nlp.max_length``)."""
    return nlp.max_length


def check_text_length(text):
    """Validate ``text`` against the configured character limit.

    Args:
        text (str): The text about to be analysed.

    Raises:
        TextTooLongError: If ``len(text)`` exceeds the configured maximum. The
            message reports the current limit, the budget behind it, and the
            budget that would be required to analyse the text.
    """
    text_length = len(text)
    max_length = get_max_length()
    if text_length > max_length:
        budget = memory_for_length(max_length)
        required = memory_for_length(text_length)
        raise TextTooLongError(
            f"Text of length {text_length:,} characters exceeds the configured "
            f"maximum of {max_length:,} characters "
            f"(temporary memory budget: {budget:.2f} GB; "
            f"this input needs about {required:.2f} GB). "
            f"Raise the budget with configure_memory_budget({required}) or by "
            f"setting COPYME_MEMORY_GB={required}."
        )


# Apply the environment-configured budget at import time so callers that never
# touch the helpers still get a sensible limit.
configure_memory_budget()

# 2. Load NLTK Resources
try:
    from nltk.corpus import nps_chat
    try:
        chat_words = nps_chat.tagged_words()
        NLTK_FILLERS = {word.lower() for word, tag in chat_words if tag == 'UH'}
    except LookupError:
        print("Warning: NLTK 'nps_chat' not found. Using fallback list.")
        NLTK_FILLERS = set()
except ImportError:
    NLTK_FILLERS = set()

FALLBACK_MARKERS = {
    "so", "actually", "really", "okay", "well", "like", "basically", 
    "literally", "totally", "honestly", "anyway", "you know", "i mean", "right",
    "however", "moreover", "therefore", "thus", "hence", "furthermore"
}
DISCOURSE_MARKERS = NLTK_FILLERS.union(FALLBACK_MARKERS)

lexicon = Empath()


# --- PROGRESS REPORTING ---

# Ordered analysis stages and their rough share of total runtime. These turn the
# multi-step analysis into a single monotonic 0-100 progress value so UIs (the
# Streamlit app, notebooks) can show a status indicator while long texts are
# processed. Tune the weights if the balance of work changes materially.
ANALYSIS_STAGES = (
    ("parse", "Parsing text with spaCy", 0.70),
    ("extract", "Extracting tokens and sentences", 0.05),
    ("semantics", "Running semantic analysis", 0.10),
    ("phrases", "Counting repeated phrases", 0.05),
    ("metrics", "Computing quantitative metrics", 0.05),
    ("assessments", "Running qualitative assessments", 0.03),
    ("vocabulary", "Collecting vocabulary and phrases", 0.02),
)


def _stage_boundaries(stages=ANALYSIS_STAGES):
    """Map each stage key to ``(label, start_percent, end_percent)``."""
    total = sum(weight for _, _, weight in stages)
    boundaries = {}
    elapsed = 0.0
    for key, label, weight in stages:
        start = 100.0 * elapsed / total
        elapsed += weight
        end = 100.0 * elapsed / total
        boundaries[key] = (label, round(start, 1), round(end, 1))
    return boundaries


STAGE_BOUNDARIES = _stage_boundaries()


class ProgressReporter:
    """Translate internal stage reports into ``(label, percent)`` callbacks.

    Callers pass an ``on_progress`` callback to :class:`StyleAnalyser` or
    :func:`analyze_linguistic_style`. This class maps the internal stage
    identifiers onto a single monotonic 0-100 percentage, so callers never need
    to know the stage list and the value never goes backwards.
    """

    def __init__(self, callback=None):
        """
        Args:
            callback (callable, optional): Called as ``callback(label, percent)``
                where ``label`` is a human-readable stage name and ``percent`` is
                a float between 0.0 and 100.0.
        """
        self._callback = callback
        self._percent = 0.0

    @property
    def enabled(self):
        """bool: Whether a callback is attached (reports are a no-op otherwise)."""
        return self._callback is not None

    def __call__(self, key, fraction=1.0):
        """Report that stage ``key`` is ``fraction`` complete.

        Args:
            key (str): A stage key from :data:`ANALYSIS_STAGES`.
            fraction (float): Completion within the stage, 0.0 to 1.0.
        """
        if self._callback is None:
            return
        label, start, end = STAGE_BOUNDARIES.get(key, (key, 0.0, 100.0))
        fraction = max(0.0, min(1.0, fraction))
        percent = max(self._percent, start + (end - start) * fraction)
        self._percent = percent
        self._callback(label, round(percent, 1))


# --- PHRASE LENGTH ---

# The phrase list is configurable, but the Formulaic Density metric is not: it is
# pinned to 2-4 word sequences so that two profiles stay comparable no matter
# what the slider is set to. The default below therefore matches the metric.
PHRASE_METRIC_N_RANGE = (2, 3, 4)

MIN_PHRASE_WORDS = 2
MAX_PHRASE_WORDS = 6
DEFAULT_MAX_PHRASE_WORDS = max(PHRASE_METRIC_N_RANGE)


def repeated_phrase_counts(
    words, max_words=DEFAULT_MAX_PHRASE_WORDS, min_words=MIN_PHRASE_WORDS
):
    """Count n-grams that repeat, for phrase lengths from ``min_words`` to ``max_words``.

    Only sequences occurring more than once are kept: a phrase that appears a
    single time is not a phrase the author leans on. Longer sequences repeat
    far less often than shorter ones, so raising ``max_words`` mostly adds
    shorter candidates rather than long ones.

    Args:
        words (list[str]): Tokenised words, in order.
        max_words (int): Longest sequence to count, in words.
        min_words (int): Shortest sequence to count, in words.

    Returns:
        Counter: Repeated sequences, lowercased, mapped to their frequency.

    Raises:
        ValueError: If ``min_words`` is below 1, or ``max_words`` is below
            ``min_words``.
    """
    if min_words < 1:
        raise ValueError(f"min_words must be at least 1, got {min_words}")
    if max_words < min_words:
        raise ValueError(
            f"max_words must be at least min_words, got {max_words} < {min_words}"
        )

    combined_counts = Counter()
    for n in range(min_words, max_words + 1):
        counts = Counter(
            " ".join(words[i:i + n]).lower()
            for i in range(len(words) - n + 1)
        )
        for gram, count in counts.items():
            if count > 1:
                combined_counts[gram] += count
    return combined_counts


# --- TOKEN COUNTING ---

# Fallback tokeniser, used when ``tiktoken`` is not installed: one token per run
# of letters, per run of digits, and per non-space symbol. Measured against
# cl100k_base it lands on 99% of the true count for a generated pre-prompt, and
# within roughly +/-10% for prose, JSON and source code.
_TOKEN_CHUNK = re.compile(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]")

_ENCODER = None
_ENCODER_CHECKED = False


def _exact_encoder():
    """Return a ``tiktoken`` encoder, or ``None`` when one is unavailable.

    Resolved once and cached. ``tiktoken`` fetches its merge table on first use,
    so a missing package, no network access, or any other load failure falls
    back to :func:`estimate_tokens` instead of breaking the caller.
    """
    global _ENCODER, _ENCODER_CHECKED
    if not _ENCODER_CHECKED:
        _ENCODER_CHECKED = True
        try:
            import tiktoken

            _ENCODER = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _ENCODER = None
    return _ENCODER


def estimate_tokens(text):
    """Estimate the number of LLM tokens in ``text`` without ``tiktoken``.

    Args:
        text (str): The text to measure.

    Returns:
        int: The estimated token count, 0 for empty input.
    """
    if not text:
        return 0
    return max(1, len(_TOKEN_CHUNK.findall(text)))


def count_tokens(text):
    """Count the LLM tokens in ``text``, exactly when possible.

    Uses ``tiktoken``'s ``cl100k_base`` encoding when it is installed and
    loadable, which is exact for the GPT-3.5/GPT-4 family and a close guide for
    other vendors. Falls back to :func:`estimate_tokens` otherwise, so no
    dependency and no network access are required.

    Args:
        text (str): The text to measure.

    Returns:
        tuple[int, bool]: The token count and whether it is exact. The flag is
            ``False`` when the count is an estimate.
    """
    encoder = _exact_encoder()
    if encoder is not None:
        return len(encoder.encode(text)), True
    return estimate_tokens(text), False


# --- VOCABULARY SELECTION ---

# Percentage of the most frequent distinct terms kept by default.
DEFAULT_VOCABULARY_PERCENTILE = 20.0


def top_fraction(counts, percentile=DEFAULT_VOCABULARY_PERCENTILE):
    """Keep the most frequent ``percentile`` percent of distinct terms.

    Terms are ranked by frequency descending, with ties left in order of first
    appearance in the text (the ordering ``Counter.most_common`` produces), so
    the selection is deterministic for a given input.

    The knob is proportional, not absolute: 20% of a short text is a handful of
    terms, 20% of a long text is a large one. At least one term is always kept
    so a non-empty text never yields an empty vocabulary.

    Args:
        counts (Counter): Term-to-frequency counts, e.g. word or n-gram counts.
        percentile (float): Percentage of distinct terms to keep, 0-100.

    Returns:
        list[tuple[str, int]]: ``(term, count)`` pairs, most frequent first.
    """
    ranked = counts.most_common()
    if not ranked:
        return []

    percentile = max(0.0, min(100.0, float(percentile)))
    keep = int(round(len(ranked) * percentile / 100.0))
    return ranked[:max(1, min(keep, len(ranked)))]


def summarise_vocabulary(word_counts, phrase_counts,
                         percentile=DEFAULT_VOCABULARY_PERCENTILE):
    """Select the most frequent words and phrases at ``percentile``.

    Words and phrases are truncated independently: each list keeps its own top
    ``percentile`` percent of distinct terms.

    Args:
        word_counts (Counter): Counts of single words.
        phrase_counts (Counter): Counts of repeated n-gram phrases.
        percentile (float): Percentage of distinct terms to keep, 0-100.

    Returns:
        dict: ``common_vocabulary`` and ``frequent_phrases``, each a list of
            ``(term, count)`` pairs, most frequent first.
    """
    return {
        "common_vocabulary": top_fraction(word_counts, percentile),
        "frequent_phrases": top_fraction(phrase_counts, percentile),
    }


# --- UNIFIED ANALYZER CLASS ---

class StyleAnalyser:
    """
    A class for performing comprehensive linguistic and stylistic analysis on text data.
    
    This class leverages SpaCy for NLP processing and Empath for semantic analysis to calculate
    a variety of quantitative metrics (e.g., TTR, sentence length) and qualitative assessments
    (e.g., rhetorical intent, genre alignment).
    
    Attributes:
        text (str): The original input text.
        doc (spacy.tokens.Doc): The processed SpaCy document object.
        words (list[str]): A list of all non-punctuation, non-space tokens in the text.
        sentences (list[spacy.tokens.Span]): A list of sentences derived from the text.
        word_count (int): The total number of valid words.
        sentence_count (int): The total number of sentences.
        unique_words (set[str]): A set of unique words (case-insensitive) in the text.
        word_counts (Counter): Counts of each lowercased word.
        empath_scores (dict): Semantic category scores from the Empath lexicon.
        repeated_counts (Counter): Frequency counts of repeated n-grams. Pinned
            to :data:`PHRASE_METRIC_N_RANGE` so Formulaic Density stays
            comparable between profiles. Use :meth:`phrase_counts` for the
            configurable phrase list.
    """

    def __init__(self, text, memory_gb=None, on_progress=None):
        """
        Initializes the StyleAnalyser with input text.

        Processing includes SpaCy tokenization, sentence segmentation, unique word extraction,
        Empath semantic analysis, and n-gram repetition counting.

        Args:
            text (str): The raw text string to be analyzed.
            memory_gb (float, optional): Temporary memory budget in gigabytes.
                When provided, ``nlp.max_length`` is recalculated from it before
                the text is processed.
            on_progress (callable, optional): Called as ``on_progress(label, percent)``
                as each analysis stage completes, for status indicators in UIs.

        Raises:
            TextTooLongError: If the text exceeds the character limit implied by
                the current memory budget.
        """
        self._progress = ProgressReporter(on_progress)
        if memory_gb is not None:
            configure_memory_budget(memory_gb)
        check_text_length(text)
        self._progress("parse", 0.0)
        self.text = text
        self.doc = nlp(text)
        self._progress("parse", 1.0)
        self.words = [token.text for token in self.doc if not token.is_punct and not token.is_space]
        self.sentences = list(self.doc.sents)
        self.word_count = len(self.words)
        self.sentence_count = len(self.sentences)
        self.unique_words = set(w.lower() for w in self.words)
        self.word_counts = Counter(w.lower() for w in self.words)
        self._progress("extract", 1.0)
        self.empath_scores = lexicon.analyze(text, normalize=True) or {}
        self._progress("semantics", 1.0)
        self._phrase_cache = {}
        self.repeated_counts = self.phrase_counts()
        self._progress("phrases", 1.0)

    def report_progress(self, key, fraction=1.0):
        """Report progress for a later analysis stage.

        Args:
            key (str): A stage key from :data:`ANALYSIS_STAGES`.
            fraction (float): Completion within the stage, 0.0 to 1.0.
        """
        self._progress(key, fraction)

    def _get_ngrams(self, n):
        """
        Generates a list of n-grams from the tokenized text.

        Args:
            n (int): The length of the n-gram (e.g., 2 for bigrams).

        Returns:
            list[str]: A list of n-gram strings in lowercase.
        """
        return [
            " ".join(self.words[i:i + n]).lower()
            for i in range(len(self.words) - n + 1)
        ]

    def _get_repeated_ngram_counts(self, n_range=None):
        """
        Identifies and counts n-grams that appear more than once in the text.

        Kept for backwards compatibility; :meth:`phrase_counts` supersedes it.

        Args:
            n_range (list[int], optional): Contiguous n-gram lengths to check.
                Defaults to [2, 3, 4].

        Returns:
            Counter: A dictionary-like object mapping repeated n-gram strings
                to their frequency.
        """
        if n_range is None:
            n_range = list(PHRASE_METRIC_N_RANGE)
        return repeated_phrase_counts(self.words, max(n_range), min(n_range))

    def phrase_counts(self, max_words=DEFAULT_MAX_PHRASE_WORDS, min_words=MIN_PHRASE_WORDS):
        """
        Counts repeated phrases from ``min_words`` up to ``max_words`` long.

        Results are memoised per range. The vocabulary view re-derives its
        phrase list every time a slider moves, while the parsed document stays
        cached, so a repeat call for the same range must be free.

        Args:
            max_words (int): Longest sequence to count, in words.
            min_words (int): Shortest sequence to count, in words.

        Returns:
            Counter: Repeated phrases mapped to their frequency.
        """
        key = (min_words, max_words)
        if key not in self._phrase_cache:
            self._phrase_cache[key] = repeated_phrase_counts(
                self.words, max_words, min_words
            )
        return self._phrase_cache[key]


    # --- QUANTITATIVE METRICS ---

    def get_ttr(self):
        """
        Calculates the Type-Token Ratio (TTR).

        TTR is a measure of lexical diversity, defined as the number of unique
        word types divided by the total number of word tokens.

        Returns:
            float: The TTR value between 0.0 and 1.0 (rounded to 3 decimals).
                   Returns 0.0 if the text is empty.
        """
        if self.word_count == 0:
            return 0.0
        return round(len(self.unique_words) / self.word_count, 3)

    def assess_ttr(self, ttr):
        """
        Categorizes lexical diversity based on TTR value.

        Args:
            ttr (float): The Type-Token Ratio.

        Returns:
            str: One of "diverse" (>0.6), "standard" (>0.4), or "repetitive" (<=0.4).
        """
        if ttr > 0.6:
            return "diverse"
        elif ttr > 0.4:
            return "standard"
        return "repetitive"

    def get_mls(self):
        """
        Calculates the Mean Length of Sentence (MLS).

        Returns:
            float: The average number of words per sentence (rounded to 2 decimals).
                   Returns 0.0 if there are no sentences.
        """
        if self.sentence_count == 0:
            return 0.0
        return round(self.word_count / self.sentence_count, 2)

    def assess_mls(self, mls):
        """
        Categorizes syntactic complexity based on sentence length.

        Args:
            mls (float): Mean Length of Sentence.

        Returns:
            str: One of "complex/elaborate" (>25), "standard" (>15),
                 or "short/telegraphic" (<=15).
        """
        if mls > 25:
            return "complex/elaborate"
        elif mls > 15:
            return "standard"
        return "short/telegraphic"

    def get_punctuation_density(self):
        """
        Calculates Punctuation Density per 1,000 words.

        Returns:
            float: The normalized frequency of punctuation marks per 1,000 words.
        """
        if self.word_count == 0:
            return 0.0
        punct_count = len([t for t in self.doc if t.is_punct])
        return round((punct_count / self.word_count) * 1000, 2)

    def assess_punctuation_density(self, density):
        """
        Categorizes structural pacing based on punctuation density.

        Args:
            density (float): Punctuation marks per 1,000 words.

        Returns:
            str: One of "heavily punctuated" (>150), "balanced" (>100),
                 or "sparse" (<=100).
        """
        if density > 150:
            return "heavily punctuated"
        elif density > 100:
            return "balanced"
        return "sparse"

    def get_flesch_reading_ease(self):
        """
        Calculates the Flesch Reading Ease score.

        Uses the `textstat` library to compute the score based on sentence
        length and syllables per word. Scale: 0-100 (where 100 is easiest
        to read).

        Returns:
            float: The reading ease score (rounded to 1 decimal).
        """
        return round(textstat.flesch_reading_ease(self.text), 1)

    def assess_flesch_reading_ease(self, score):
        """
        Interprets the Flesch Reading Ease score into difficulty levels.

        Args:
            score (float): The Flesch Reading Ease score.

        Returns:
            str: Difficulty category ranging from "very easy" to "very difficult/technical".
        """
        if score > 80:
            return "very easy"
        elif score > 60:
            return "easy/standard"
        elif score > 40:
            return "difficult"
        return "very difficult/technical"

    def get_discourse_marker_density(self):
        """
        Calculates the density of conversational fillers (Discourse Markers).

        Scans for words defined in the global `DISCOURSE_MARKERS` list (e.g., 'like', 'so', 'well')
        and normalizes the count per 1,000 words.

        Returns:
            float: Markers per 1,000 words.
        """
        if self.word_count == 0:
            return 0.0
        dm_count = sum(1 for w in self.words if w.lower() in DISCOURSE_MARKERS)
        return round((dm_count / self.word_count) * 1000, 2)

    def assess_discourse_marker_density(self, density):
        """
        Assesses the formality level based on discourse marker usage.

        Args:
            density (float): Discourse markers per 1,000 words.

        Returns:
            str: One of "conversational" (>40), "natural" (>15),
                 or "formal/polished" (<=15).
        """
        if density > 40:
            return "conversational"
        elif density > 15:
            return "natural"
        return "formal/polished"

    def get_hapax_legomena_ratio(self):
        """
        Calculates the Hapax Legomena Ratio (uniqueness metric).

        This is the ratio of words that appear exactly once (hapax legomena)
        to the total count of *unique* words. High values indicate
        descriptive richness.

        Returns:
            float: Ratio between 0.0 and 1.0.
        """
        total_unique = len(self.unique_words)
        if total_unique == 0:
            return 0.0
        word_freqs = Counter(w.lower() for w in self.words)
        hapax_count = sum(1 for count in word_freqs.values() if count == 1)
        return round(hapax_count / total_unique, 3)

    def assess_hapax_legomena_ratio(self, ratio):
        """
        Categorizes descriptive richness based on the Hapax Legomena Ratio.

        Args:
            ratio (float): The Hapax Legomena Ratio.

        Returns:
            str: One of "unique/creative" (>0.6), "rich" (>0.4),
                 or "basic/repetitive" (<=0.4).
        """
        if ratio > 0.6:
            return "unique/creative"
        elif ratio > 0.4:
            return "rich"
        return "basic/repetitive"

    def get_formulaic_density(self):
        """
        Calculates Formulaic Density based on repeated n-grams.

        Measures the proportion of the total word count that is comprised of repeated
        2-gram, 3-gram, or 4-gram sequences.

        Returns:
            float: A value between 0.0 and 1.0 representing the saturation of repeated phrases.
        """
        if self.word_count == 0:
            return 0.0
        total_repeated = sum(self.repeated_counts.values())
        return round(min(total_repeated / self.word_count, 1.0), 3)

    def assess_formulaic_density(self, density):
        """
        Assesses reliance on stock phrases or clichés.

        Args:
            density (float): Formulaic Density score.

        Returns:
            str: One of "highly formulaic" (>0.3), "standard" (>0.1),
                 or "original" (<=0.1).
        """
        if density > 0.3:
            return "highly formulaic"
        elif density > 0.1:
            return "standard"
        return "original"

    def get_modal_ratio(self):
        """
        Calculates the Modal Hedging Ratio.

        Determines the frequency of hedging/uncertainty markers (e.g.,
        'could', 'might', 'seems') per sentence.

        Returns:
            float: Average number of hedging terms per sentence (capped at 1.0).
        """
        hedges = {
            "can", "could", "may", "might", "would", "should",
            "possibly", "probably", "likely", "maybe", "seems", "appear",
            "suggests"
        }
        hedge_count = sum(
            1 for t in self.doc
            if t.text.lower() in hedges or t.lemma_.lower() in hedges
        )
        if self.sentence_count == 0:
            return 0.0
        return round(min(hedge_count / self.sentence_count, 1.0), 2)

    def assess_modal_ratio(self, ratio):
        """
        Interprets the author's level of certainty or tentativeness.

        Args:
            ratio (float): Modal Hedging Ratio.

        Returns:
            str: One of "tentative/hedged" (>0.2), "balanced" (>0.05),
                 or "assertive/direct" (<=0.05).
        """
        if ratio > 0.2:
            return "tentative/hedged"
        elif ratio > 0.05:
            return "balanced"
        return "assertive/direct"

    def get_function_word_frequencies(self):
        """
        Calculates the relative frequency of specific Part-of-Speech (POS) tags.

        Focuses on function words (Prepositions, Conjunctions, Pronouns,
        Determiners), which are useful for stylistic fingerprinting.

        Returns:
            dict: Keys are POS categories (e.g., "prepositions"), values are
                ratios (0.0-1.0).
        """
        pos_counts = Counter(token.pos_ for token in self.doc)
        total = sum(pos_counts.values()) or 1

        def get_pos_ratio(target_pos_list):
            count = sum(pos_counts.get(pos, 0) for pos in target_pos_list)
            return round(count / total, 3)

        return {
            "prepositions": get_pos_ratio(["ADP"]),
            "conjunctions": get_pos_ratio(["CCONJ", "SCONJ"]),
            "pronouns": get_pos_ratio(["PRON"]),
            "determiners": get_pos_ratio(["DET"])
        }


    # --- WORDS DATA ---


    def get_common_vocabulary(self, n=10):
        """
        Retrieves the most frequently used words in the text.

        Args:
            n (int): The number of top words to return. Defaults to 10.

        Returns:
            list[str]: A list of the `n` most common words.
        """
        return [word for word, count in self.word_counts.most_common(n)]

    def get_frequent_phrases(self, n=10):
        """
        Retrieves the most frequently occurring n-gram phrases.

        Args:
            n (int): The number of top phrases to return. Defaults to 10.

        Returns:
            list[str]: A list of the `n` most common repeated phrases.
        """
        return [phrase for phrase, count in self.repeated_counts.most_common(n)]


    # --- QUALITATIVE ANALYZER ---


    def get_lexical_sophistication(self):
        """
        Assesses vocabulary difficulty based on word length.

        Calculates the ratio of "long words" (length > 6 characters) to total
        words.

        Returns:
            str: Interpretation of sophistication level ("basic",
                 "intermediate", "advanced", or "specialized/technical").
        """
        if not self.words:
            return "basic"
        long_words = [w for w in self.words if len(w) > 6]
        ratio = len(long_words) / self.word_count

        if ratio > 0.3:
            return "specialized/technical"
        elif ratio > 0.2:
            return "advanced"
        elif ratio > 0.12:
            return "intermediate"
        return "basic"

    def get_syntactic_variety(self):
        """
        Evaluates the variation in sentence structures.

        Uses the standard deviation of sentence lengths as a proxy for
        structural variety. High deviation implies a mix of short and
        long sentences.

        Returns:
            str: Variety classification ("repetitive", "standard", "varied",
                 or "complex").
        """
        if not self.sentences:
            return "repetitive"
        sent_lengths = [
            len([t for t in s if not t.is_punct]) for s in self.sentences
        ]
        if not sent_lengths:
            return "repetitive"

        mean_len = sum(sent_lengths) / len(sent_lengths)
        variance = sum(
            (x - mean_len) ** 2 for x in sent_lengths
        ) / len(sent_lengths)
        std_dev = variance ** 0.5

        if std_dev > 10:
            return "complex"
        elif std_dev > 6:
            return "varied"
        elif std_dev > 3:
            return "standard"
        return "repetitive"

    def get_cohesive_harmony(self):
        """
        Measures the flow and connectivity between sentences (Cohesive Harmony).

        Analyzes overlap of nouns and proper nouns between adjacent sentences.
        A high overlap indicates strong threading of subjects/objects through
        the text.

        Returns:
            str: Integration level ("fragmented", "loose", "coherent",
                 or "highly_integrated").
        """
        if self.sentence_count <= 1:
            return "coherent"
        overlaps = 0
        for i in range(1, self.sentence_count):
            prev_nouns = {
                t.lemma_ for t in self.sentences[i - 1]
                if t.pos_ in ["NOUN", "PROPN"]
            }
            curr_nouns = {
                t.lemma_ for t in self.sentences[i]
                if t.pos_ in ["NOUN", "PROPN"]
            }
            if not prev_nouns.isdisjoint(curr_nouns):
                overlaps += 1

        score = overlaps / (self.sentence_count - 1)
        if score > 0.7:
            return "highly_integrated"
        elif score > 0.5:
            return "coherent"
        elif score > 0.25:
            return "loose"
        return "fragmented"

    def get_rhetorical_intent(self):
        """
        Determines the primary communicative purpose of the text.

        Uses Empath semantic scoring to detect dominant themes (e.g., 'help' for persuasion,
        'science' for exposition).

        Returns:
            str: The detected intent (e.g., "persuasive", "narrative", "informative").
        """
        scores = self.empath_scores
        if scores.get('help', 0) > 0.02 or scores.get('negotiate', 0) > 0.02:
            return "persuasive"
        elif scores.get('science', 0) > 0.02 or scores.get('school', 0) > 0.02:
            return "expository"
        elif scores.get('emotional', 0) > 0.02 or scores.get('negative_emotion', 0) > 0.02:
            return "narrative"
        elif scores.get('appearance', 0) > 0.02 or scores.get('art', 0) > 0.02:
            return "descriptive"
        elif scores.get('tool', 0) > 0.02 or scores.get('work', 0) > 0.02:
            return "instructional"
        return "informative"

    def get_genre_alignment(self, intent):
        """
        Classifies the text into a likely genre based on other metrics.

        Combines Flesch Reading Ease scores, Empath semantic topics, and 
        Rhetorical Intent to map the text to a standard genre (e.g., Academic, 
        Legal, Journalistic).

        Args:
            intent (str): The previously calculated rhetorical intent.

        Returns:
            str: The predicted genre alignment.
        """
        readability = textstat.flesch_reading_ease(self.text)
        scores = self.empath_scores

        if readability < 40 and (
            scores.get('law', 0) > 0.01 or scores.get('government', 0) > 0.01
        ):
            return "legal"
        elif readability < 50 and scores.get('science', 0) > 0.02:
            return "academic"
        elif readability > 60 and intent == "narrative":
            return "literary_fiction"
        elif (
            scores.get('computer', 0) > 0.02 or scores.get('technology', 0) > 0.02
        ):
            return "technical_manual"
        elif intent == "persuasive" or scores.get('speaking', 0) > 0.02:
            return "conversational_speech"
        elif 40 < readability < 60 and intent == "informative":
            return "journalistic"
        return "conversational_speech"



# --- MAIN ANALYSIS FUNCTION ---

def build_profile(analyzer, vocabulary_percentile=DEFAULT_VOCABULARY_PERCENTILE,
                  max_phrase_words=DEFAULT_MAX_PHRASE_WORDS):
    """Assemble the full linguistic-style profile from a parsed analyser.

    This is the cheap half of the analysis: it reuses the tokens, sentences and
    counts already held by ``analyzer`` and never touches SpaCy, so UIs can call
    it again whenever a vocabulary control changes.

    Args:
        analyzer (StyleAnalyser): An analyser that has already parsed the text.
        vocabulary_percentile (float, optional): Percentage of the most frequent
            distinct terms to keep in the ``words`` section. Pass ``None`` for
            the legacy behaviour of the top ten words and phrases.
        max_phrase_words (int, optional): Longest phrase to keep in the
            ``words`` section, in words. Only affects the phrase list; Formulaic
            Density stays pinned to :data:`PHRASE_METRIC_N_RANGE`.

    Returns:
        dict: The ``quantitative``, ``qualitative`` and ``words`` sections, plus
            a ``limits`` section reporting the input length, the configured
            character limit, the memory budget behind it and the phrase length.
    """
    # Calculate Quantitative Values
    ttr = analyzer.get_ttr()
    mls = analyzer.get_mls()
    punct_density = analyzer.get_punctuation_density()
    dm_density = analyzer.get_discourse_marker_density()
    hapax = analyzer.get_hapax_legomena_ratio()
    formulaic = analyzer.get_formulaic_density()
    modal = analyzer.get_modal_ratio()
    readability = analyzer.get_flesch_reading_ease()
    
    # Calculate Intent for alignment
    intent = analyzer.get_rhetorical_intent()

    quantitative = {
        "type_token_ratio": ttr,
        "mean_length_of_sentence": mls,
        "punctuation_density": punct_density,
        "discourse_marker_density": dm_density,
        "hapax_legomena_ratio": hapax,
        "formulaic_density": formulaic,
        "modal_hedging_ratio": modal,
        "flesch_reading_ease": readability,
        "function_word_frequency": analyzer.get_function_word_frequencies()
    }
    analyzer.report_progress("metrics")

    qualitative = {
        "type_token_ratio_assessment":
            analyzer.assess_ttr(ttr),
        "mean_length_of_sentence_assessment":
            analyzer.assess_mls(mls),
        "punctuation_density_assessment":
            analyzer.assess_punctuation_density(punct_density),
        "discourse_marker_density_assessment":
            analyzer.assess_discourse_marker_density(dm_density),
        "hapax_legomena_ratio_assessment":
            analyzer.assess_hapax_legomena_ratio(hapax),
        "formulaic_density_assessment":
            analyzer.assess_formulaic_density(formulaic),
        "modal_hedging_ratio_assessment":
            analyzer.assess_modal_ratio(modal),
        "flesch_reading_ease_assessment":
            analyzer.assess_flesch_reading_ease(readability),
        "lexical_sophistication":
            analyzer.get_lexical_sophistication(),
        "syntactic_variety":
            analyzer.get_syntactic_variety(),
        "cohesive_harmony":
            analyzer.get_cohesive_harmony(),
        "rhetorical_intent":
            intent,
        "genre_alignment":
            analyzer.get_genre_alignment(intent)
    }
    analyzer.report_progress("assessments")

    phrases = analyzer.phrase_counts(max_phrase_words)

    if vocabulary_percentile is None:
        words = {
            "common_vocabulary": analyzer.get_common_vocabulary(),
            "frequent_phrases": [phrase for phrase, _ in phrases.most_common(10)],
        }
    else:
        vocabulary = summarise_vocabulary(
            analyzer.word_counts, phrases, vocabulary_percentile
        )
        words = {
            "common_vocabulary": [term for term, _ in vocabulary["common_vocabulary"]],
            "frequent_phrases": [term for term, _ in vocabulary["frequent_phrases"]],
        }
    analyzer.report_progress("vocabulary")

    return {
        "quantitative": quantitative,
        "qualitative": qualitative,
        "words": words,
        "limits": {
            "text_length": len(analyzer.text),
            "max_length": get_max_length(),
            "max_phrase_words": max_phrase_words,
            "memory_budget_gb": memory_for_length(get_max_length())
        }
    }


def analyze_linguistic_style(text, memory_gb=None, on_progress=None,
                             vocabulary_percentile=DEFAULT_VOCABULARY_PERCENTILE,
                             max_phrase_words=DEFAULT_MAX_PHRASE_WORDS):
    """Analyse ``text`` and return the full linguistic-style profile.

    Args:
        text (str): The raw text string to analyze.
        memory_gb (float, optional): Temporary memory budget in gigabytes,
            forwarded to :class:`StyleAnalyser`.
        on_progress (callable, optional): Called as ``on_progress(label, percent)``
            as each analysis stage completes, for status indicators in UIs.
        vocabulary_percentile (float, optional): Percentage of the most frequent
            distinct terms to keep in the ``words`` section. Pass ``None`` for
            the legacy behaviour of the top ten words and phrases.
        max_phrase_words (int, optional): Longest phrase to keep in the
            ``words`` section, in words.

    Returns:
        dict: The ``quantitative``, ``qualitative`` and ``words`` sections, plus
            a ``limits`` section reporting the input length, the configured
            character limit, the memory budget behind it and the phrase length.
    """
    analyzer = StyleAnalyser(text, memory_gb=memory_gb, on_progress=on_progress)
    return build_profile(
        analyzer,
        vocabulary_percentile=vocabulary_percentile,
        max_phrase_words=max_phrase_words,
    )