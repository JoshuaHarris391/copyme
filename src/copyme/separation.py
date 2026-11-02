"""Keep the manner, drop the subject.

A profile of someone's work email used to produce a model that kept mentioning
the quarterly report. The cause was simple: the vocabulary block listed the
author's most frequent words, and on any real sample most of those words are the
sample's subject, not the author's style.

Three filters, all re-derived from the parse the analyser already holds.

**Function and manner words survive; content words do not.** What is left is the
author's connectives and qualifiers, which is what stylometry has always found
diagnostic of a person rather than a topic.

**Idioms survive; topical phrases do not.** "The thing is" and "which is to say"
are habits. "The quarterly report" is a subject.

**One-off names are masked.** A name mentioned once is somebody the author
happened to write about. A name mentioned throughout is part of their world, and
the research found that masking those costs style learning nothing while
removing something real from the voice.

## What masking is and is not

Masking is **best-effort, not a redaction guarantee.** It can only replace what
``en_core_web_sm`` recognises as an entity, and that model's recall on personal
names is well short of complete -- an unusual given name, or one sitting at the
start of a sentence where any capitalised word is plausible, is often missed.
Raising recall would mean shipping a larger model, which is a dependency
decision rather than a code one.

So masking reduces incidental leakage of third parties from a sample; it is not
a control anyone should rely on to anonymise a document. Where a sample must not
contain a name, the name should not be in the sample. The UI says how many
entities were masked in each passage precisely so a user can see that the number
is smaller than they might assume.
"""

from collections import Counter

# Parts of speech that describe *how* someone writes. Conjunctions and
# adpositions carry sentence construction; determiners, pronouns and particles
# carry register; adverbs carry stance; interjections carry voice.
STYLE_POS = frozenset({"CCONJ", "SCONJ", "ADP", "DET", "PRON", "PART", "ADV", "INTJ", "AUX"})

# Parts of speech that name subjects. Dropped even when frequent.
CONTENT_POS = frozenset({"NOUN", "PROPN", "VERB", "ADJ", "NUM", "X", "SYM"})

# Content-word exceptions: these are stance and intensity rather than subject,
# and they are among the most recognisable things about how a person writes.
STYLE_ALLOW_LIST = frozenset(
    {
        "very", "quite", "rather", "fairly", "somewhat", "really", "actually",
        "honestly", "frankly", "clearly", "obviously", "apparently", "perhaps",
        "maybe", "probably", "possibly", "certainly", "definitely", "absolutely",
        "basically", "literally", "totally", "utterly", "slightly", "terribly",
        "awfully", "pretty", "jolly", "bloody", "simply", "merely", "just",
        "think", "suppose", "reckon", "guess", "seem", "mean", "know", "say",
    }
)

# How many content nouns define "the subject of this sample", for the phrase
# filter. Deep enough to catch a sample's recurring subjects, shallow enough
# that an ordinary noun used once does not disqualify an idiom.
TOP_CONTENT_NOUNS = 50

# A named entity appearing fewer than this many times is a one-off and is
# masked. At or above it, the name is part of the author's recurring world.
NAME_MASK_THRESHOLD = 3

# Role placeholders by spaCy entity label. These are roles, not tokens: a model
# reading "[a city]" can still write the sentence, where "[NAME]" breaks it.
#
# The labels absent from this map are deliberately not masked. A date, a
# quantity or a percentage identifies nobody, and replacing them damages the
# sentence for nothing.
ROLE_PLACEHOLDERS = {
    "PERSON": "[a person]",
    "ORG": "[an organisation]",
    "GPE": "[a city]",
    "LOC": "[a place]",
    "FAC": "[a building]",
    "NORP": "[a group]",
    "PRODUCT": "[a product]",
    "WORK_OF_ART": "[a book]",
    "EVENT": "[an event]",
    "LANGUAGE": "[a language]",
}


def style_word_counts(analyser):
    """Count only the words that describe manner rather than subject.

    Args:
        analyser (copyme.StyleAnalyser): A parsed analyser.

    Returns:
        collections.Counter: Lowercased style words mapped to their counts.
    """
    counts = Counter()
    for token in analyser.doc:
        if token.is_punct or token.is_space:
            continue
        lowered = token.text.lower()
        if token.pos_ in STYLE_POS or lowered in STYLE_ALLOW_LIST:
            if token.ent_type_:
                # A pronoun inside an entity span is part of a name, not a
                # function word.
                continue
            counts[lowered] += 1
    return counts


def top_content_nouns(analyser, limit=TOP_CONTENT_NOUNS):
    """The nouns that define what this sample is about.

    Args:
        analyser (copyme.StyleAnalyser): A parsed analyser.
        limit (int): How many to return.

    Returns:
        set[str]: Lowercased lemmas.
    """
    counts = Counter()
    for token in analyser.doc:
        if token.pos_ in ("NOUN", "PROPN"):
            counts[token.lemma_.lower()] += 1
    return {noun for noun, _ in counts.most_common(limit)}


def entity_texts(analyser):
    """Named entities and how often each appears.

    Returns:
        collections.Counter: Lowercased entity text mapped to its count, for
            the labels in :data:`ROLE_PLACEHOLDERS` only.
    """
    counts = Counter()
    for entity in analyser.doc.ents:
        if entity.label_ in ROLE_PLACEHOLDERS:
            counts[entity.text.lower()] += 1
    return counts


def style_phrases(analyser, phrase_counts, content_nouns=None):
    """Keep the phrases that are idioms and drop the ones that are subjects.

    A repeated phrase survives only if it contains no noun from the sample's top
    content nouns and no named entity. That single test separates "I mean" from
    "the quarterly report" without a hand-written list.

    Args:
        analyser (copyme.StyleAnalyser): A parsed analyser.
        phrase_counts (collections.Counter): Repeated phrases and their counts,
            from :meth:`copyme.StyleAnalyser.phrase_counts`.
        content_nouns (set[str], optional): Defaults to
            :func:`top_content_nouns`.

    Returns:
        collections.Counter: The surviving phrases, counts unchanged.
    """
    content_nouns = top_content_nouns(analyser) if content_nouns is None else content_nouns
    entities = {text for text in entity_texts(analyser)}
    entity_words = set()
    for text in entities:
        entity_words.update(text.split())

    kept = Counter()
    for phrase, count in phrase_counts.items():
        words = phrase.lower().split()
        if any(word in content_nouns for word in words):
            continue
        if any(word in entity_words for word in words):
            continue
        kept[phrase] = count
    return kept


def mask_names(analyser, start, end, threshold=NAME_MASK_THRESHOLD, counts=None):
    """Return the text between two offsets with one-off names replaced.

    Masking happens here, at render time, and never to the stored passage. That
    is what lets ``mask_names=False`` return the source text byte for byte
    without re-parsing anything.

    Args:
        analyser (copyme.StyleAnalyser): A parsed analyser.
        start (int): Character offset into the original text.
        end (int): Character offset one past the end.
        threshold (int): Occurrences at or above which a name is kept.
        counts (collections.Counter, optional): Entity counts for the whole
            sample, from :func:`entity_texts`. Passed in when masking many
            passages, so the counts are computed once.

    Returns:
        str: The masked text.
    """
    counts = entity_texts(analyser) if counts is None else counts
    text = analyser.text[start:end]

    replacements = []
    for entity in analyser.doc.ents:
        if entity.start_char < start or entity.end_char > end:
            continue
        placeholder = ROLE_PLACEHOLDERS.get(entity.label_)
        if placeholder is None:
            continue
        if counts.get(entity.text.lower(), 0) >= threshold:
            continue
        replacements.append((entity.start_char - start, entity.end_char - start, placeholder))

    # Replace from the end so earlier offsets stay valid.
    for begin, finish, placeholder in sorted(replacements, reverse=True):
        text = text[:begin] + placeholder + text[finish:]
    return text


def masked_entity_count(analyser, start, end, threshold=NAME_MASK_THRESHOLD, counts=None):
    """How many entities masking would replace in a span. For the UI's caption."""
    counts = entity_texts(analyser) if counts is None else counts
    total = 0
    for entity in analyser.doc.ents:
        if entity.start_char < start or entity.end_char > end:
            continue
        if entity.label_ not in ROLE_PLACEHOLDERS:
            continue
        if counts.get(entity.text.lower(), 0) < threshold:
            total += 1
    return total
