"""Segmentation: turning one parsed document into candidate exemplars.

Exemplar selection can only be as good as what it gets to choose between. These
tests pin the two rules that are in tension with each other -- keep every passage
inside a size window, and never split a paragraph -- and record exactly how that
tension is resolved when a single paragraph is simply too long.
"""

import spacy

from copyme.passages import (
    MAX_PASSAGE_TOKENS,
    MIN_CANDIDATE_TOKENS,
    MIN_PASSAGE_TOKENS,
    candidates,
    classify_paragraph,
    newlines_are_paragraph_boundaries,
    paragraph_spans,
    segment,
)

HARD_WRAPPED = """The first paragraph runs across several lines because the
source was wrapped at a fixed width, so these newlines mean nothing at
all about where a thought ends.

The second paragraph is separated by a blank line, which is the real
boundary here.
"""

CHAT_SHAPED = """hey, are you around?
I wanted to ask about the thing from yesterday.
No rush though.
Let me know when you get a chance.
"""


def _parse(text):
    nlp = spacy.load("en_core_web_sm")
    return nlp(text)


def test_hard_wrapped_prose_treats_only_blank_lines_as_boundaries():
    """A book's line breaks are an artefact of its line width, not its meaning.

    Project Gutenberg texts, pasted emails and anything that has been through a
    fixed-width editor wrap mid-sentence. If copyme treated those newlines as
    paragraph breaks it would split sentences in half and then measure the
    halves, reporting a paragraph length of one short line for an author who
    writes long paragraphs.
    """
    assert newlines_are_paragraph_boundaries(HARD_WRAPPED) is False
    assert len(paragraph_spans(HARD_WRAPPED)) == 2


def test_chat_shaped_text_treats_every_newline_as_a_boundary():
    """In a chat log each line is a complete turn, so each line is a paragraph.

    This is the input shape copyme is mostly given -- messages, notes, persona
    files -- and getting it wrong would merge a whole conversation into one
    "paragraph". The two shapes are told apart by where lines end: a wrapped
    line stops mid-sentence, a turn stops on a full stop or a question mark.
    """
    assert newlines_are_paragraph_boundaries(CHAT_SHAPED) is True
    assert len(paragraph_spans(CHAT_SHAPED)) == 4


def test_a_quoted_opening_marks_dialogue_and_a_bullet_marks_a_list():
    """Dialogue and lists are labelled so they are never split apart.

    Half an exchange stops reading as an exchange and half a list is not a list,
    so these two labels are what earns a block the right to overshoot the size
    ceiling rather than be cut in the middle.
    """
    assert classify_paragraph('"Where have you been?" he asked.') == "dialogue"
    assert classify_paragraph("- the first item") == "list"
    assert classify_paragraph("1. the first item") == "list"
    assert classify_paragraph("Ordinary prose, with no marker.") == "prose"


def test_every_passage_clears_the_floor_except_the_last(london):
    """A passage below the floor is too short to show a rhythm.

    120 tokens is roughly 90 words: enough for several sentences, so a reader --
    or a model -- can see how the author varies length and where they break. The
    final passage is exempt because a document rarely ends on an exact multiple
    of anything.
    """
    passages = segment(london.doc, london.text)
    assert len(passages) > 5

    short = [
        passage for passage in passages[:-1]
        if passage.token_count < MIN_PASSAGE_TOKENS
    ]
    assert short == [], f"{len(short)} passages fell below the floor"


def test_passages_stay_under_the_ceiling_unless_a_single_block_exceeds_it(james):
    """Where the window and the no-splitting rule conflict, splitting loses.

    Henry James writes paragraphs longer than the 400-token ceiling. copyme
    cannot both keep such a paragraph whole and keep it under the ceiling, and
    splitting it would destroy the thing being measured, so the passage is
    emitted whole and flagged ``oversized``. This test records that choice:
    every passage over the ceiling must carry the flag, so an overshoot is
    always visible rather than silent.
    """
    passages = segment(james.doc, james.text)
    over = [p for p in passages if p.token_count > MAX_PASSAGE_TOKENS]

    assert over, "the James fixture is expected to contain oversized paragraphs"
    assert all(passage.oversized for passage in over)
    assert all(
        not passage.oversized
        for passage in passages
        if passage.token_count <= MAX_PASSAGE_TOKENS
    )


def test_no_passage_starts_or_ends_mid_paragraph(london):
    """Passage boundaries must coincide with paragraph boundaries.

    If a passage began mid-paragraph the exemplar would open on a half thought,
    which reads as a mistake to a human and teaches a model to start writing
    mid-sentence.
    """
    passages = segment(london.doc, london.text)
    boundaries = paragraph_spans(london.text)
    starts = {start for start, _ in boundaries}
    ends = {end for _, end in boundaries}

    for passage in passages:
        assert passage.start in starts
        assert passage.end in ends


def test_short_blocks_are_excluded_as_candidates_but_still_counted():
    """A tiny block cannot be an exemplar, but it is still part of the author.

    This matters for a sample made entirely of one-line messages. Dropping the
    short blocks outright would mean the author's own totals were computed from
    a filtered subset of their writing -- so copyme would be comparing them
    against a version of themselves it invented.
    """
    text = "Short line one.\nShort line two.\nShort line three.\n"
    doc = _parse(text)
    passages = segment(doc, text)

    assert passages, "short lines must still produce passages"
    assert all(p.token_count < MIN_CANDIDATE_TOKENS for p in passages)
    assert candidates(passages) == []
    # The text is still fully represented: the offsets cover it end to end.
    assert passages[0].start == 0
    assert passages[-1].end == len(text.rstrip())


def test_offsets_point_back_at_the_original_text(dialogue):
    """A passage must be findable in the source it came from.

    The offsets are what let copyme show an exemplar in context and mask the
    names in it later without parsing anything a second time. If they drifted,
    masking would redact the wrong span.
    """
    passages = segment(dialogue.doc, dialogue.text)
    for passage in passages[:20]:
        assert dialogue.text[passage.start:passage.end] == passage.text


def test_segmentation_is_deterministic(london):
    """The same text must always segment the same way.

    Exemplar snapshots are reviewed as diffs. If segmentation wandered between
    runs, every snapshot would churn and the review would stop meaning
    anything.
    """
    first = segment(london.doc, london.text)
    second = segment(london.doc, london.text)
    assert [(p.start, p.end) for p in first] == [(p.start, p.end) for p in second]
