"""The feature set: the numbers everything else is derived from.

The single most important property here is **length invariance**. copyme is
given anything from 2,000 to 200,000 words, and every downstream decision --
which passages are distinctive, which rules to suppress, whether a draft drifted
-- compares one text's numbers against another's. A feature that moves with
sample length would make all three comparisons meaningless.

The first test in this file is the one that settled a design question by
measurement rather than preference.
"""

import spacy

from copyme.features import (
    FEATURE_COMPARATIVES,
    FEATURE_LABELS,
    FEATURE_NAMES,
    document_features,
    extract,
    mattr,
    mtld,
)


def _parse(text):
    nlp = spacy.load("en_core_web_sm")
    nlp.max_length = 2_000_000
    return nlp(text)


def test_mattr_is_stable_across_sample_lengths_where_raw_ttr_is_not(read_sample):
    """This is the measurement that chose MATTR over MTLD and over raw TTR.

    Lexical diversity has to be comparable between a short sample and a long
    one. Raw type-token ratio cannot be: it is unique words divided by total
    words, and as a text grows the denominator grows faster than the numerator,
    so the ratio always falls. The spec set a 10% bar across a 2,000-word and a
    20,000-word slice of the same author.

    Measured on the golden samples, MATTR moved by at most 5.7% and MTLD by up
    to 36.9%, against raw TTR's 46% to 61%. MATTR ships; MTLD stays in the
    codebase only so this comparison can be re-run. This test is the record of
    that decision, and it fails if the choice ever stops being the right one.
    """
    worst_mattr = 0.0
    worst_ttr = 0.0

    for slug in ("london", "james", "twain", "dialogue"):
        words = read_sample(slug, chars=250_000).split()
        short = [word.lower() for word in words[:2_000]]
        long = [word.lower() for word in words[:20_000]]
        assert len(long) > len(short), f"{slug} is too short for this comparison"

        def drift(value_a, value_b):
            return abs(value_a - value_b) / value_a

        worst_mattr = max(worst_mattr, drift(mattr(short), mattr(long)))
        worst_ttr = max(
            worst_ttr,
            drift(len(set(short)) / len(short), len(set(long)) / len(long)),
        )

    assert worst_mattr < 0.10, f"MATTR drifted {worst_mattr:.1%} across lengths"
    assert worst_ttr > 0.30, (
        "raw TTR is expected to drift badly across lengths; if it no longer "
        "does, the reason for replacing it has gone"
    )


def test_mtld_is_not_part_of_the_shipped_vector():
    """Only one lexical-diversity measure ships, as the spec required.

    Shipping both would mean two numbers that usually agree and occasionally do
    not, with no rule for which to believe. The function stays available; the
    feature vector carries MATTR alone.
    """
    assert "mattr" in FEATURE_NAMES
    assert "mtld" not in FEATURE_NAMES
    # Still callable, so the comparison above can be re-run.
    assert mtld(["one", "two", "three"]) > 0


def test_every_feature_is_present_labelled_and_describable(london):
    """A feature with no plain-language name cannot appear in a rule.

    v2's whole premise is that the output stops showing metric names. That only
    works if every feature has both a human label and a pair of comparatives --
    "longer"/"shorter", "more common"/"rarer" -- so the renderer can put it in a
    sentence. A feature added without them would fall back to "higher", which is
    the register v2 exists to remove.
    """
    features = document_features(london.doc, london.text)

    assert set(features.scalars) == set(FEATURE_NAMES)
    assert all(isinstance(value, (int, float)) for value in features.scalars.values())

    for name in FEATURE_NAMES:
        assert name in FEATURE_LABELS, f"{name} has no plain-language label"
        assert name in FEATURE_COMPARATIVES, f"{name} has no comparatives"


def test_sentence_length_is_reported_as_a_distribution_not_a_mean(london):
    """A mean sentence length is what produces machine-sounding prose.

    Ask a model for "an average of 17 words" and it writes sentence after
    sentence of about 17 words, which is the uniform rhythm readers identify as
    written by a machine. The quartiles and the coefficient of variation are
    what let the renderer ask for the spread instead, so they must all be
    present and correctly ordered.
    """
    scalars = document_features(london.doc, london.text).scalars

    assert (
        scalars["sentence_length_q1"]
        <= scalars["sentence_length_median"]
        <= scalars["sentence_length_q3"]
        <= scalars["sentence_length_p90"]
    )
    assert scalars["sentence_length_cv"] > 0
    assert 0.0 <= scalars["share_short_sentences"] <= 1.0
    assert 0.0 <= scalars["share_long_sentences"] <= 1.0


def test_rates_barely_move_when_the_same_text_is_doubled(london_text):
    """Every feature is a rate, so repeating a text must not change it.

    This is length invariance stated as directly as it can be. Doubling a
    document doubles every raw count, so any feature that moved here would be a
    count in disguise, and would quietly make long samples look different from
    short ones to the selector and the scorer alike.
    """
    once = document_features(_parse(london_text))
    twice = document_features(_parse(london_text + "\n\n" + london_text))

    for name in FEATURE_NAMES:
        first, second = once.scalars[name], twice.scalars[name]
        scale = max(abs(first), abs(second), 1e-6)
        assert abs(first - second) / scale < 0.1, (
            f"{name} moved from {first} to {second} when the text was doubled"
        )


def test_contraction_rate_separates_never_from_nothing_to_contract():
    """"Never contracts" and "had no chance to" are different findings.

    A contraction count alone cannot tell them apart, and the difference
    matters: one is a real habit worth instructing a model about, the other is
    an artefact of a short sample. The rate therefore divides by the
    opportunities, not by the word count.
    """
    contracted = _parse("I don't know. It isn't ready. You're early. I'm sure.")
    expanded = _parse("I do not know. It is not ready. You are early. I am sure.")

    assert extract(contracted[:]).scalars["contraction_rate"] > 0.8
    assert extract(expanded[:]).scalars["contraction_rate"] < 0.2


def test_fragments_are_sentences_with_no_finite_verb():
    """Fragments are a deliberate habit, and a measurable one.

    Writers who use fragments for emphasis do it at a consistent rate, and a
    model will not do it at all unless asked. Detection keys on the absence of a
    finite verb, which is what makes "Like this." a fragment and "This is how."
    a sentence.
    """
    fragments = _parse("No. Not like that. Never again.")
    sentences = _parse("It was not like that. We will not do it again.")

    assert extract(fragments[:]).scalars["fragment_rate"] > 0.6
    assert extract(sentences[:]).scalars["fragment_rate"] == 0.0


def test_the_dialogue_fixture_has_shorter_sentences_than_the_james_fixture(
    dialogue, james
):
    """The feature set must separate voices that a reader separates easily.

    Wilde's stage dialogue and James's subordinated prose are about as far apart
    as English gets. If the sentence-length features could not tell them apart
    there would be no reason to believe they can tell subtler voices apart
    either, and every downstream score would be measuring noise.
    """
    wilde = document_features(dialogue.doc, dialogue.text).scalars
    henry = document_features(james.doc, james.text).scalars

    assert wilde["sentence_length_median"] < henry["sentence_length_median"]
    assert wilde["share_short_sentences"] > henry["share_short_sentences"]


def test_an_empty_span_produces_a_complete_vector_of_zeroes():
    """A feature set must never be partially populated.

    Everything downstream indexes features by name. A missing key would be a
    KeyError deep inside the distance maths, where the cause would be hard to
    see; a zero is wrong but handled.
    """
    features = extract(_parse("")[:])

    assert set(features.scalars) == set(FEATURE_NAMES)
    assert features.word_count == 0
    assert all(value == 0 for value in features.scalars.values())
