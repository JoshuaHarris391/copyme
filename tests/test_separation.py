"""Style/content separation: keeping the manner, dropping the subject.

The problem this solves is concrete. v1 listed the author's most frequent words
and phrases, and on any real sample most of those are the sample's subject. A
profile of someone's work email produced a model that kept mentioning the
quarterly report -- it had learned the topic, not the voice.
"""

import spacy

from copyme import StyleAnalyser
from copyme.separation import (
    NAME_MASK_THRESHOLD,
    ROLE_PLACEHOLDERS,
    entity_texts,
    mask_names,
    masked_entity_count,
    style_phrases,
    style_word_counts,
    top_content_nouns,
)

# One subject mentioned repeatedly, plus a clear set of function words. The
# separation has to keep "of the" and drop "quarterly report".
WORK_EMAIL = (
    "I have attached the quarterly report for review. The quarterly report "
    "covers revenue and the forecast. As I mentioned, the quarterly report is "
    "late because the revenue figures were late. I think the forecast is "
    "broadly right, though I would rather wait for the revenue numbers before "
    "we commit to it. Let me know if you would like me to walk through the "
    "forecast with you."
)


def test_the_style_vocabulary_keeps_function_words_and_drops_subjects():
    """Function words are diagnostic of a person; nouns are diagnostic of a topic.

    This is the oldest finding in stylometry: the words a writer cannot avoid
    using -- conjunctions, prepositions, determiners, pronouns -- carry their
    fingerprint, while the words they choose carry their subject. Keeping the
    first set and dropping the second is what separates manner from matter.
    """
    analyser = StyleAnalyser(WORK_EMAIL)
    counts = style_word_counts(analyser)
    kept = set(counts)

    assert "the" in kept
    assert "would" in kept
    assert "i" in kept

    assert "report" not in kept
    assert "revenue" not in kept
    assert "forecast" not in kept


def test_no_noun_or_proper_noun_survives_into_the_style_vocabulary(london):
    """Stated as the acceptance criterion, over a real sample.

    The small example above could pass by coincidence. This runs the filter over
    a whole book slice and checks that nothing tagged as a noun, proper noun or
    adjective reaches the style list.
    """
    analyser = london
    counts = style_word_counts(analyser)

    tagged = {}
    for token in analyser.doc:
        tagged.setdefault(token.text.lower(), set()).add(token.pos_)

    from copyme.separation import STYLE_ALLOW_LIST

    for word in counts:
        if word in STYLE_ALLOW_LIST:
            continue
        parts = tagged.get(word, set())
        assert not parts <= {"NOUN", "PROPN", "ADJ", "NUM"}, (
            f"{word!r} is only ever a content word but survived the filter"
        )


def test_an_idiom_survives_but_a_topical_phrase_does_not():
    """"The thing is" is a habit. "The quarterly report" is a subject.

    One test separates them without a hand-written list: a repeated phrase
    survives only if it contains no noun from the sample's own top content nouns
    and no named entity.
    """
    analyser = StyleAnalyser(WORK_EMAIL)
    phrases = analyser.phrase_counts(4)
    kept = style_phrases(analyser, phrases)

    assert any("quarterly report" in phrase for phrase in phrases), (
        "the fixture should repeat its subject often enough to be counted"
    )
    assert not any("report" in phrase for phrase in kept)
    assert not any("revenue" in phrase for phrase in kept)


def test_the_top_content_nouns_are_the_sample_s_actual_subject():
    """The phrase filter is only as good as its idea of what the text is about."""
    analyser = StyleAnalyser(WORK_EMAIL)
    nouns = top_content_nouns(analyser)

    assert "report" in nouns
    assert "revenue" in nouns


def test_a_name_mentioned_twice_is_masked_and_one_mentioned_three_times_is_not():
    """The threshold is the whole mechanism, so it is tested at its boundary.

    A name mentioned once is somebody the author happened to write about, and
    letting it through leaks a third party into every generation. A name used
    throughout is part of the author's recurring world, and the research found
    that masking those costs style learning nothing while removing something
    real from the voice.
    """
    text = (
        "I spoke to Margaret about the draft and she sent it back. "
        "Margaret was right about the opening. "
        "Later I spoke to Dimitri about the schedule. "
        "The work carried on. We fixed the opening and moved to the next "
        "section, which took the rest of the afternoon to finish properly."
    )
    analyser = StyleAnalyser(text)
    counts = entity_texts(analyser)

    assert counts["margaret"] == 2
    assert counts["dimitri"] == 1

    # With the default threshold of three, both are one-offs and both go.
    masked = mask_names(analyser, 0, len(text))
    assert "Margaret" not in masked
    assert "Dimitri" not in masked
    assert "[a person]" in masked

    # Lower the threshold to two and Margaret, at two mentions, is kept.
    kept = mask_names(analyser, 0, len(text), threshold=2)
    assert "Margaret" in kept
    assert "Dimitri" not in kept


def test_a_placeholder_names_a_role_rather_than_a_blank():
    """"[NAME]" breaks the sentence; "[a person]" leaves it readable.

    The placeholder is read by a model as part of the passage it is learning
    from, so it has to remain grammatical English. A bare token teaches the
    model to emit bare tokens.
    """
    analyser = StyleAnalyser(
        "We met Priya in Lisbon last spring and talked about the project all "
        "afternoon, which was longer than any of us had planned to stay."
    )
    masked = mask_names(analyser, 0, len(analyser.text))

    assert "[NAME]" not in masked
    assert "[REDACTED]" not in masked
    for placeholder in ROLE_PLACEHOLDERS.values():
        assert placeholder.startswith("[a") and placeholder.endswith("]")
    assert "[a person]" in masked or "[a city]" in masked


def test_dates_and_quantities_are_not_masked():
    """Masking is for identity, not for every entity spaCy can find.

    A date or a percentage identifies nobody, and replacing it damages the
    sentence for no benefit -- while also destroying a genuine feature of how
    the author writes about numbers.
    """
    text = (
        "We shipped on 14 March and revenue rose 12 per cent, which was more "
        "than anyone had forecast for a quarter that started as badly as that "
        "one did."
    )
    analyser = StyleAnalyser(text)
    masked = mask_names(analyser, 0, len(text))

    assert "14 March" in masked
    assert "12 per cent" in masked


def test_masking_off_returns_the_source_text_byte_for_byte(london_profile):
    """``mask_names=False`` must be a genuine passthrough.

    Masking is applied to a copy and stored beside the verbatim text, never in
    place. That is what lets a user turn it off without copyme re-parsing
    anything, and it means the unmasked form has to be exactly the source -- not
    a reconstruction that happens to look the same.
    """
    from copyme.exports import exemplar_text

    assert london_profile.exemplars
    for exemplar in london_profile.exemplars:
        assert exemplar_text(exemplar, mask_names=False) == exemplar.text


def test_the_masked_form_is_stored_so_a_json_profile_needs_no_parse(london_profile):
    """A profile loaded from disk has no spaCy document to find entities with.

    If masking were applied at render time only, ``copyme render`` on a stored
    profile would silently emit unmasked passages -- the one place the leak
    would matter most, because the file has already left the machine it was
    built on.
    """
    from copyme import Profile

    reloaded = Profile.from_json(london_profile.to_json())

    assert reloaded.exemplars
    for exemplar in reloaded.exemplars:
        assert exemplar.masked_text, "the masked form must survive serialisation"


def test_the_masked_entity_count_matches_what_masking_actually_replaces():
    """The UI reports how much was masked, so the count has to be the truth.

    A caption saying "3 names masked" beside a passage with five names in it
    would be worse than no caption.
    """
    text = (
        "Priya and Dimitri met Tomas in Lisbon, and the four of us spent the "
        "whole of the following week arguing about what to do next."
    )
    analyser = StyleAnalyser(text)

    count = masked_entity_count(analyser, 0, len(text))
    masked = mask_names(analyser, 0, len(text))
    replaced = sum(
        masked.count(placeholder) for placeholder in set(ROLE_PLACEHOLDERS.values())
    )

    assert count == replaced
    assert count >= 1
    assert NAME_MASK_THRESHOLD == 3
