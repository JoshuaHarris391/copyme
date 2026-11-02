"""The v2 feature set, computed for a whole document and for each passage.

Every feature here is a rate or a distribution, never a raw count, so a 2,000
word sample and a 200,000 word one are directly comparable. That property is
what lets the same numbers do three different jobs: rank passages for
distinctiveness, decide which rules are worth stating, and tell a user how far a
generated draft drifted.

Two conventions hold throughout.

**Distributions, not means.** Sentence length is reported as quartiles and a
coefficient of variation, not as an average. A flat mean is what produces the
uniform rhythm readers identify as machine-written, so the renderer needs the
spread in order to ask for it.

**Scalars are separate from descriptions.** :attr:`FeatureSet.scalars` is a flat
dictionary of floats keyed by :data:`FEATURE_NAMES`, which is what the distance
maths and the baseline comparison need. Anything that is not a number -- the
author's literal favourite sentence openers, which dash form they use -- lives in
:attr:`FeatureSet.detail`, where the renderer can reach it.

Everything re-derives from a parse that has already happened. Nothing here calls
spaCy.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .analyser import DISCOURSE_MARKERS
from .passages import paragraph_spans

# The ordered scalar feature vector. Order is fixed because the baseline file and
# every stored profile are keyed by it; append to the end, never reorder.
FEATURE_NAMES = (
    "sentence_length_q1",
    "sentence_length_median",
    "sentence_length_q3",
    "sentence_length_p90",
    "sentence_length_cv",
    "share_short_sentences",
    "share_long_sentences",
    "opener_conjunction_rate",
    "opener_pronoun_rate",
    "opener_adverb_rate",
    "opener_concentration",
    "contraction_rate",
    "first_person_singular_per_1k",
    "first_person_plural_per_1k",
    "second_person_per_1k",
    "question_rate_per_1k",
    "exclamation_rate_per_1k",
    "em_dash_per_1k",
    "ellipsis_per_1k",
    "parenthetical_per_1k",
    "semicolon_per_1k",
    "colon_per_1k",
    "comma_per_sentence",
    "fragment_rate",
    "paragraph_sentences_median",
    "paragraph_sentences_q3",
    "opening_sentence_length",
    "closing_sentence_length",
    "lowercase_start_rate",
    "allcaps_per_1k",
    "emoji_per_1k",
    "mattr",
    "named_entity_per_1k",
    "discourse_marker_per_1k",
    "modal_per_1k",
    "hedge_per_1k",
)

# Plain-language names, used wherever a feature is shown to a person: an
# exemplar's reason, a rule, a drift line in a score report. Keyed by
# FEATURE_NAMES. These are deliberately noun phrases that fit into a sentence
# -- "sentence length runs shorter than generic prose" -- rather than metric
# names, because a metric name is the thing v2 exists to stop showing people.
FEATURE_LABELS = {
    "sentence_length_q1": "the shortest quarter of sentences",
    "sentence_length_median": "sentence length",
    "sentence_length_q3": "the longest quarter of sentences",
    "sentence_length_p90": "the longest tenth of sentences",
    "sentence_length_cv": "variation in sentence length",
    "share_short_sentences": "very short sentences",
    "share_long_sentences": "long sentences",
    "opener_conjunction_rate": "opening a sentence with a conjunction",
    "opener_pronoun_rate": "opening a sentence with a pronoun",
    "opener_adverb_rate": "opening a sentence with an adverb",
    "opener_concentration": "reuse of one favourite sentence opener",
    "contraction_rate": "contractions",
    "first_person_singular_per_1k": "writing as I",
    "first_person_plural_per_1k": "writing as we",
    "second_person_per_1k": "addressing the reader as you",
    "question_rate_per_1k": "questions",
    "exclamation_rate_per_1k": "exclamations",
    "em_dash_per_1k": "dashes",
    "ellipsis_per_1k": "ellipses",
    "parenthetical_per_1k": "parentheses",
    "semicolon_per_1k": "semicolons",
    "colon_per_1k": "colons",
    "comma_per_sentence": "commas per sentence",
    "fragment_rate": "sentence fragments",
    "paragraph_sentences_median": "paragraph length",
    "paragraph_sentences_q3": "the longest quarter of paragraphs",
    "opening_sentence_length": "the opening sentence of a paragraph",
    "closing_sentence_length": "the closing sentence of a paragraph",
    "lowercase_start_rate": "starting a sentence lower case",
    "allcaps_per_1k": "words in capitals",
    "emoji_per_1k": "emoji",
    "mattr": "vocabulary range",
    "named_entity_per_1k": "names and places",
    "discourse_marker_per_1k": "discourse markers",
    "modal_per_1k": "modal verbs",
    "hedge_per_1k": "hedging",
}

# How to describe a feature moving up or down, as ``(above, below)``. Without
# this, every comparison has to fall back on "higher" and "lower", which reads
# as a metric report rather than a description of writing: "sentences run
# longer" lands where "sentence_length_median is higher" does not.
FEATURE_COMPARATIVES = {
    "sentence_length_q1": ("longer", "shorter"),
    "sentence_length_median": ("longer", "shorter"),
    "sentence_length_q3": ("longer", "shorter"),
    "sentence_length_p90": ("longer", "shorter"),
    "sentence_length_cv": ("more varied", "more uniform"),
    "share_short_sentences": ("more common", "rarer"),
    "share_long_sentences": ("more common", "rarer"),
    "opener_conjunction_rate": ("more common", "rarer"),
    "opener_pronoun_rate": ("more common", "rarer"),
    "opener_adverb_rate": ("more common", "rarer"),
    "opener_concentration": ("more repetitive", "more varied"),
    "contraction_rate": ("more common", "rarer"),
    "first_person_singular_per_1k": ("more common", "rarer"),
    "first_person_plural_per_1k": ("more common", "rarer"),
    "second_person_per_1k": ("more common", "rarer"),
    "question_rate_per_1k": ("more common", "rarer"),
    "exclamation_rate_per_1k": ("more common", "rarer"),
    "em_dash_per_1k": ("more common", "rarer"),
    "ellipsis_per_1k": ("more common", "rarer"),
    "parenthetical_per_1k": ("more common", "rarer"),
    "semicolon_per_1k": ("more common", "rarer"),
    "colon_per_1k": ("more common", "rarer"),
    "comma_per_sentence": ("more common", "rarer"),
    "fragment_rate": ("more common", "rarer"),
    "paragraph_sentences_median": ("longer", "shorter"),
    "paragraph_sentences_q3": ("longer", "shorter"),
    "opening_sentence_length": ("longer", "shorter"),
    "closing_sentence_length": ("longer", "shorter"),
    "lowercase_start_rate": ("more common", "rarer"),
    "allcaps_per_1k": ("more common", "rarer"),
    "emoji_per_1k": ("more common", "rarer"),
    "mattr": ("wider", "narrower"),
    "named_entity_per_1k": ("more common", "rarer"),
    "discourse_marker_per_1k": ("more common", "rarer"),
    "modal_per_1k": ("more common", "rarer"),
    "hedge_per_1k": ("more common", "rarer"),
}


def comparative(name, signed):
    """The word for a feature moving in a direction.

    Args:
        name (str): A feature name.
        signed (float): Any signed quantity; only its sign is used.

    Returns:
        str: The comparative, defaulting to "higher"/"lower" for an unknown
            feature so a newly added one is still describable.
    """
    above, below = FEATURE_COMPARATIVES.get(name, ("higher", "lower"))
    return above if signed > 0 else below


# Sentences at or below this many words are "short"; at or above the other, "long".
# Both thresholds are reader-facing: they appear in rule prose as "under six
# words" and "past 25", so they are named constants rather than inline numbers.
SHORT_SENTENCE_WORDS = 6
LONG_SENTENCE_WORDS = 25

# MTLD's conventional type-token ratio floor (McCarthy and Jarvis, 2010). A
# factor ends each time the running ratio drops to this value.
MTLD_THRESHOLD = 0.72

# MATTR's window, in words. 100 is the usual choice and is short enough that a
# 2,000 word sample still yields many windows.
MATTR_WINDOW = 100

_CLITIC = re.compile(r"^(?:n't|'s|'re|'ve|'ll|'d|'m|’s|’re|’ve|’ll|’d|’m|’t)$", re.I)

# Auxiliaries that could have been contracted but were not. Counting these is
# what turns a contraction count into a contraction *rate*: "never contracts" and
# "has no auxiliaries to contract" are different findings.
_CONTRACTIBLE_AUX = {
    "am", "is", "are", "was", "were", "have", "has", "had",
    "will", "would", "shall", "should", "not",
}

_HEDGES = {
    "maybe", "perhaps", "possibly", "probably", "arguably", "somewhat",
    "fairly", "rather", "quite", "seem", "appear", "suggest", "tend",
    "roughly", "approximately", "apparently", "presumably", "supposedly",
}

_FIRST_SINGULAR = {"i", "me", "my", "mine", "myself"}
_FIRST_PLURAL = {"we", "us", "our", "ours", "ourselves"}
_SECOND = {"you", "your", "yours", "yourself", "yourselves"}

_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001faff"
    "\U0001f000-\U0001f2ff"
    "\U00002600-\U000027bf"
    "\U0000fe0f"
    "]"
)

_EM_DASH = "—"
_EN_DASH = "–"
_ELLIPSIS_CHAR = "…"


@dataclass(frozen=True)
class FeatureSet:
    """One feature vector, for a document or for a single passage.

    Attributes:
        scalars (dict): Every name in :data:`FEATURE_NAMES` mapped to a float.
            Complete and in order, so two feature sets are always comparable.
        detail (dict): Non-numeric findings the renderer needs -- literal
            openers, the dash form in use, the raw sentence-length list.
        word_count (int): Words the features were computed over.
        sentence_count (int): Sentences the features were computed over.
        paragraph_count (int): Paragraphs the features were computed over.
    """

    scalars: dict = field(default_factory=dict)
    detail: dict = field(default_factory=dict)
    word_count: int = 0
    sentence_count: int = 0
    paragraph_count: int = 0

    def vector(self):
        """list[float]: The scalars in :data:`FEATURE_NAMES` order."""
        return [self.scalars[name] for name in FEATURE_NAMES]


def _percentile(values, fraction):
    """Linear-interpolated percentile, so quartiles are stable on short samples.

    Args:
        values (list[float]): Values, not necessarily sorted.
        fraction (float): 0.0 to 1.0.

    Returns:
        float: The percentile, or 0.0 for an empty input.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = fraction * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return float(ordered[low])
    return float(ordered[low] + (ordered[high] - ordered[low]) * (position - low))


def mtld(words):
    """Measure of Textual Lexical Diversity, averaged in both directions.

    **Not part of the shipped feature vector.** MTLD and MATTR were the two
    candidates to replace raw type-token ratio, and the choice was made by
    measuring both on the golden samples: across a 2,000 word and a 20,000 word
    slice of the same author, MATTR moved by at most 5.7% and MTLD by up to
    36.9%, against the 10% bar the spec set. MATTR ships; this function stays so
    the comparison can be re-run rather than taken on trust.

    Raw type-token ratio falls as a text grows, which makes it useless for
    comparing a short sample with a long one -- and copyme is given both. MTLD
    instead counts how many words it takes for diversity to fall to a fixed
    threshold, then reports the mean length of those stretches.

    Args:
        words (list[str]): Lowercased words in order.

    Returns:
        float: The MTLD value. Higher means more diverse. 0.0 for empty input.
    """
    if not words:
        return 0.0

    def one_direction(sequence):
        factors = 0.0
        types = set()
        tokens = 0
        for word in sequence:
            types.add(word)
            tokens += 1
            if len(types) / tokens <= MTLD_THRESHOLD:
                factors += 1
                types = set()
                tokens = 0
        if tokens:
            # A trailing partial factor counts in proportion to how far it got
            # towards the threshold, so the measure does not jump when one more
            # word is added.
            ratio = len(types) / tokens
            remaining = 1.0 - ratio
            span = 1.0 - MTLD_THRESHOLD
            factors += remaining / span if span else 0.0
        if factors == 0:
            return float(len(sequence))
        return len(sequence) / factors

    forward = one_direction(words)
    backward = one_direction(list(reversed(words)))
    return round((forward + backward) / 2, 2)


def mattr(words, window=MATTR_WINDOW):
    """Moving-average type-token ratio.

    The same stability idea as :func:`mtld` by a simpler route: take the ratio in
    every window of fixed length and average them, so the denominator never
    grows with the sample.

    Args:
        words (list[str]): Lowercased words in order.
        window (int): Window length in words.

    Returns:
        float: The mean ratio, 0.0 to 1.0.
    """
    if not words:
        return 0.0
    if len(words) <= window:
        return round(len(set(words)) / len(words), 4)

    counts = Counter(words[:window])
    total = len(counts)
    windows = 1
    for index in range(window, len(words)):
        leaving = words[index - window]
        counts[leaving] -= 1
        if counts[leaving] == 0:
            del counts[leaving]
        counts[words[index]] += 1
        total += len(counts)
        windows += 1
    return round(total / windows / window, 4)


def _is_finite_verb(token):
    """Whether a token is a finite verb, which is what makes a clause a sentence."""
    if token.pos_ not in ("VERB", "AUX"):
        return False
    forms = token.morph.get("VerbForm")
    if forms:
        return "Fin" in forms
    # The small English model does not always populate morph; the Penn tags for
    # finite forms are a reliable fallback.
    return token.tag_ in ("VBD", "VBP", "VBZ", "MD")


def _opener_pos(sentence):
    """The part of speech that opens a sentence, skipping punctuation.

    Returns:
        tuple[str, str] | None: ``(pos, lowercased text)``, or None for a
            sentence with no word in it.
    """
    for token in sentence:
        if token.is_punct or token.is_space:
            continue
        return token.pos_, token.text.lower()
    return None


def _sentences(span):
    """Sentences inside a span that contain at least one word."""
    out = []
    for sentence in span.sents:
        if any(not token.is_punct and not token.is_space for token in sentence):
            out.append(sentence)
    return out


def _paragraph_sentence_counts(span, paragraphs):
    """Sentences per paragraph, for the paragraphs inside ``span``.

    Args:
        span (spacy.tokens.Span): The region being measured.
        paragraphs (list[tuple[int, int]]): Document paragraph offsets.

    Returns:
        list[int]: One count per paragraph that falls inside the span.
    """
    counts = []
    for start, end in paragraphs:
        if start < span.start_char or end > span.end_char:
            continue
        inner = span.doc.char_span(start, end, alignment_mode="expand")
        if inner is None:
            continue
        counts.append(len(_sentences(inner)))
    return [count for count in counts if count]


def extract(span, paragraphs=None):
    """Compute the full feature set for one span of a parsed document.

    Args:
        span (spacy.tokens.Span): The region to measure. Pass ``doc[:]`` for the
            whole document, or a passage's span for one passage.
        paragraphs (list[tuple[int, int]], optional): Paragraph offsets for the
            document, as returned by :func:`copyme.passages.paragraph_spans`.
            Computed from the span's own text when omitted, which is correct for
            a passage and wasteful for a document.

    Returns:
        FeatureSet: Every scalar in :data:`FEATURE_NAMES`, plus the detail the
            renderer needs.
    """
    text = span.text
    if paragraphs is None:
        paragraphs = [
            (span.start_char + start, span.start_char + end)
            for start, end in paragraph_spans(text)
        ]

    words = [token for token in span if not token.is_punct and not token.is_space]
    lowered = [token.text.lower() for token in words]
    word_count = len(words)
    sentences = _sentences(span)
    sentence_count = len(sentences)

    # Every rate is per 1,000 words; guarding the divisor once keeps the rest of
    # the function free of conditionals.
    per_1k = (1000.0 / word_count) if word_count else 0.0
    per_sentence = (1.0 / sentence_count) if sentence_count else 0.0

    lengths = [
        sum(1 for token in sentence if not token.is_punct and not token.is_space)
        for sentence in sentences
    ]
    mean_length = (sum(lengths) / len(lengths)) if lengths else 0.0
    if len(lengths) > 1 and mean_length:
        variance = sum((length - mean_length) ** 2 for length in lengths) / (len(lengths) - 1)
        cv = math.sqrt(variance) / mean_length
    else:
        cv = 0.0

    openers = [_opener_pos(sentence) for sentence in sentences]
    openers = [opener for opener in openers if opener is not None]
    opener_words = Counter(word for _, word in openers)
    opener_pos = Counter(pos for pos, _ in openers)
    opener_total = len(openers) or 1

    contracted = sum(1 for token in span if _CLITIC.match(token.text))
    # An auxiliary that is already contracted is not also a missed opportunity
    # to contract: in "isn't", `is` carries the clitic rather than standing
    # uncontracted beside it. Counting it in both halves of the ratio would cap
    # the rate below 1.0 for a writer who contracts everything.
    expandable = sum(
        1
        for index, token in enumerate(span)
        if token.text.lower() in _CONTRACTIBLE_AUX
        and not token.is_punct
        and not token.is_space
        and not (
            index + 1 < len(span) and _CLITIC.match(span[index + 1].text)
        )
    )
    contraction_sites = contracted + expandable

    questions = sum(1 for sentence in sentences if sentence.text.rstrip().endswith("?"))
    exclamations = sum(1 for sentence in sentences if sentence.text.rstrip().endswith("!"))

    em_dashes = text.count(_EM_DASH)
    en_dashes = text.count(_EN_DASH)
    spaced_hyphens = len(re.findall(r"\s-{1,2}\s", text))
    ellipses = text.count(_ELLIPSIS_CHAR) + len(re.findall(r"\.\s?\.\s?\.", text))

    fragments = sum(
        1 for sentence in sentences
        if not any(_is_finite_verb(token) for token in sentence)
    )

    paragraph_counts = _paragraph_sentence_counts(span, paragraphs)

    first_sentences = []
    last_sentences = []
    for start, end in paragraphs:
        inner = span.doc.char_span(start, end, alignment_mode="expand")
        if inner is None:
            continue
        inner_sentences = _sentences(inner)
        if not inner_sentences:
            continue
        first_sentences.append(inner_sentences[0])
        last_sentences.append(inner_sentences[-1])

    def mean_words(group):
        if not group:
            return 0.0
        return sum(
            sum(1 for token in sentence if not token.is_punct and not token.is_space)
            for sentence in group
        ) / len(group)

    lowercase_starts = sum(
        1 for pos_word in openers if pos_word[1] and pos_word[1][0].islower()
    )
    # An all-caps word is emphasis only if it is a real word, so single letters
    # and acronym-length runs are excluded.
    allcaps = sum(
        1 for token in words
        if len(token.text) > 2 and token.text.isupper() and token.text.isalpha()
    )

    entities = sum(1 for entity in span.ents)
    markers = sum(1 for word in lowered if word in DISCOURSE_MARKERS)
    modals = sum(1 for token in words if token.tag_ == "MD")
    hedges = sum(1 for token in words if token.lemma_.lower() in _HEDGES)

    scalars = {
        "sentence_length_q1": round(_percentile(lengths, 0.25), 3),
        "sentence_length_median": round(_percentile(lengths, 0.5), 3),
        "sentence_length_q3": round(_percentile(lengths, 0.75), 3),
        "sentence_length_p90": round(_percentile(lengths, 0.9), 3),
        "sentence_length_cv": round(cv, 4),
        "share_short_sentences": round(
            sum(1 for length in lengths if length <= SHORT_SENTENCE_WORDS) * per_sentence, 4
        ),
        "share_long_sentences": round(
            sum(1 for length in lengths if length >= LONG_SENTENCE_WORDS) * per_sentence, 4
        ),
        "opener_conjunction_rate": round(
            (opener_pos["CCONJ"] + opener_pos["SCONJ"]) / opener_total, 4
        ),
        "opener_pronoun_rate": round(opener_pos["PRON"] / opener_total, 4),
        "opener_adverb_rate": round(opener_pos["ADV"] / opener_total, 4),
        "opener_concentration": round(
            (opener_words.most_common(1)[0][1] / opener_total) if opener_words else 0.0, 4
        ),
        "contraction_rate": round(
            (contracted / contraction_sites) if contraction_sites else 0.0, 4
        ),
        "first_person_singular_per_1k": round(
            sum(1 for word in lowered if word in _FIRST_SINGULAR) * per_1k, 2
        ),
        "first_person_plural_per_1k": round(
            sum(1 for word in lowered if word in _FIRST_PLURAL) * per_1k, 2
        ),
        "second_person_per_1k": round(
            sum(1 for word in lowered if word in _SECOND) * per_1k, 2
        ),
        "question_rate_per_1k": round(questions * per_1k, 2),
        "exclamation_rate_per_1k": round(exclamations * per_1k, 2),
        "em_dash_per_1k": round((em_dashes + en_dashes + spaced_hyphens) * per_1k, 2),
        "ellipsis_per_1k": round(ellipses * per_1k, 2),
        "parenthetical_per_1k": round(text.count("(") * per_1k, 2),
        "semicolon_per_1k": round(text.count(";") * per_1k, 2),
        "colon_per_1k": round(text.count(":") * per_1k, 2),
        "comma_per_sentence": round(text.count(",") * per_sentence, 3),
        "fragment_rate": round(fragments * per_sentence, 4),
        "paragraph_sentences_median": round(_percentile(paragraph_counts, 0.5), 3),
        "paragraph_sentences_q3": round(_percentile(paragraph_counts, 0.75), 3),
        "opening_sentence_length": round(mean_words(first_sentences), 2),
        "closing_sentence_length": round(mean_words(last_sentences), 2),
        "lowercase_start_rate": round(lowercase_starts / opener_total, 4),
        "allcaps_per_1k": round(allcaps * per_1k, 2),
        "emoji_per_1k": round(len(_EMOJI.findall(text)) * per_1k, 2),
        "mattr": mattr(lowered),
        "named_entity_per_1k": round(entities * per_1k, 2),
        "discourse_marker_per_1k": round(markers * per_1k, 2),
        "modal_per_1k": round(modals * per_1k, 2),
        "hedge_per_1k": round(hedges * per_1k, 2),
    }

    if em_dashes:
        dash_form = "em dash"
    elif en_dashes:
        dash_form = "en dash"
    elif spaced_hyphens:
        dash_form = "spaced hyphen"
    else:
        dash_form = None

    detail = {
        "top_openers": opener_words.most_common(10),
        "opener_pos": dict(opener_pos),
        "dash_form": dash_form,
        "sentence_lengths": lengths,
        "paragraph_sentence_counts": paragraph_counts,
        "contraction_sites": contraction_sites,
    }

    return FeatureSet(
        scalars=scalars,
        detail=detail,
        word_count=word_count,
        sentence_count=sentence_count,
        paragraph_count=len(paragraph_counts),
    )


def document_features(doc, text=None):
    """Feature set for a whole parsed document.

    Args:
        doc (spacy.tokens.Doc): The parsed document.
        text (str, optional): The original text. Defaults to ``doc.text``.

    Returns:
        FeatureSet: The document-level vector.
    """
    text = doc.text if text is None else text
    return extract(doc[:], paragraph_spans(text))


def passage_features(doc, passages, text=None):
    """Feature set for each passage, keyed by the passage's index.

    Args:
        doc (spacy.tokens.Doc): The parsed document.
        passages (list[copyme.passages.Passage]): The segmented passages.
        text (str, optional): The original text. Defaults to ``doc.text``.

    Returns:
        dict[int, FeatureSet]: One entry per passage, in index order.
    """
    text = doc.text if text is None else text
    paragraphs = paragraph_spans(text)
    out = {}
    for passage in passages:
        span = doc.char_span(passage.start, passage.end, alignment_mode="expand")
        if span is None:
            continue
        inner = [
            (start, end)
            for start, end in paragraphs
            if start >= passage.start and end <= passage.end
        ]
        out[passage.index] = extract(span, inner or None)
    return out
