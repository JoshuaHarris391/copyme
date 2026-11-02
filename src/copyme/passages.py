"""Segment a parsed document into candidate passages.

Exemplar selection needs something to choose between. This module turns one
parsed document into a list of :class:`Passage` objects sized for a prompt --
long enough to show a rhythm, short enough that a budget buys several of them.

Everything here re-derives from the ``spacy.tokens.Doc`` the analyser already
holds. The parse is the expensive half of copyme and is done once; segmentation
must stay cheap enough to run on every slider move.

Each passage keeps its character offsets into the original text, so an exemplar
can later be shown with surrounding context, or have its names masked, without
re-parsing anything.
"""

import re
from dataclasses import dataclass

# The target window, in spaCy tokens. Below the floor a passage is too short to
# show a sentence rhythm; above the ceiling one exemplar eats a whole Compact
# budget.
MIN_PASSAGE_TOKENS = 120
MAX_PASSAGE_TOKENS = 400

# What segmentation aims for inside the window. Closing a passage the moment it
# clears the floor would leave almost every passage at 120-odd tokens, which
# both wastes an exemplar budget and shows less of the author's
# paragraph-to-paragraph rhythm than a longer passage does. Aiming near the
# middle of the window fixes both.
TARGET_PASSAGE_TOKENS = 300

# Shorter than this and a block is not worth offering as an exemplar at all. It
# still counts towards the author's document-level totals -- a sample made
# entirely of one-line paragraphs must not be re-measured on a subset of itself.
MIN_CANDIDATE_TOKENS = 40

# A paragraph is dialogue if it opens with one of these, which is how both
# fiction and chat transcripts mark a turn.
_QUOTE_OPENERS = ('"', "'", "“", "‘", "«", "—")

# A paragraph is a list item if it opens with a bullet or an enumerator.
_LIST_OPENER = re.compile(r"^\s*(?:[-*•·–]\s+|\(?\d{1,3}[.)]\s+|[a-z][.)]\s+)")

# Blank-line separated blocks: the paragraph boundary in prose.
_BLANK_LINE = re.compile(r"\n[ \t]*\n")

# Sentence-final punctuation, allowing for a closing quote or bracket after it.
_LINE_ENDS_A_SENTENCE = re.compile(r"[.!?…][\"'”’)\]]*\s*$")


@dataclass(frozen=True)
class Passage:
    """One candidate exemplar, with its place in the source text.

    Attributes:
        index (int): Position in the document, counting from zero. Stable for a
            given text, so a selection can be recorded and reproduced.
        start (int): Character offset of the first character, into the original
            text passed to the analyser.
        end (int): Character offset one past the last character.
        text (str): The passage as it appears in the source, verbatim.
        token_count (int): spaCy tokens, excluding whitespace. Punctuation is
            counted, because a model's tokeniser counts it too.
        kind (str): ``"prose"``, ``"dialogue"`` or ``"list"``. Dialogue and list
            runs are never split, so their passages may exceed the window.
        is_candidate (bool): Whether the passage may be offered as an exemplar.
            Passages under :data:`MIN_CANDIDATE_TOKENS` are excluded.
        oversized (bool): Whether the passage exceeds
            :data:`MAX_PASSAGE_TOKENS`. Only ever true where the window and the
            no-splitting rule conflict: an indivisible block that is simply
            longer than the ceiling.
    """

    index: int
    start: int
    end: int
    text: str
    token_count: int
    kind: str
    is_candidate: bool
    oversized: bool

    @property
    def word_count(self):
        """int: Whitespace-separated words, for reporting to a human."""
        return len(self.text.split())


def newlines_are_paragraph_boundaries(text, sample_lines=400):
    """Decide once per document whether a single newline ends a paragraph.

    Two input shapes have to work. Prose from a book or an export is often
    hard-wrapped, so the newlines inside a paragraph are an artefact of the line
    width and mean nothing. Chat logs, notes and persona files put one complete
    utterance on each line, so there every newline is a real boundary.

    Telling them apart by looking at where lines end is reliable and cheap: a
    hard-wrapped line stops mid-sentence, while an utterance stops on a full
    stop, a question mark or a closing quote.

    The decision is made for the whole document rather than per block, so
    segmentation stays deterministic and a mixed document cannot be split one
    way at the top and another way at the bottom.

    Args:
        text (str): The original text.
        sample_lines (int): How many interior lines to inspect. The answer
            stabilises long before the end of a large document.

    Returns:
        bool: True if single newlines should be treated as paragraph breaks.
    """
    interior = []
    for block in _BLANK_LINE.split(text):
        lines = [line for line in block.split("\n") if line.strip()]
        # Only the lines with a following line tell us anything: the last line of
        # a block ends the paragraph either way.
        interior.extend(lines[:-1])
        if len(interior) >= sample_lines:
            break

    interior = interior[:sample_lines]
    if not interior:
        return False

    finished = sum(1 for line in interior if _LINE_ENDS_A_SENTENCE.search(line))
    return finished / len(interior) >= 0.6


def paragraph_spans(text):
    """Return ``(start, end)`` character offsets for each paragraph.

    Args:
        text (str): The original text.

    Returns:
        list[tuple[int, int]]: Offsets of each non-empty paragraph, in order.
    """
    separator = re.compile(r"\n+") if newlines_are_paragraph_boundaries(text) else _BLANK_LINE

    spans = []
    cursor = 0
    for match in separator.finditer(text):
        spans.append((cursor, match.start()))
        cursor = match.end()
    spans.append((cursor, len(text)))

    trimmed = []
    for start, end in spans:
        body = text[start:end]
        stripped = body.strip()
        if not stripped:
            continue
        offset = body.index(stripped)
        trimmed.append((start + offset, start + offset + len(stripped)))
    return trimmed


def classify_paragraph(paragraph):
    """Label a paragraph ``"dialogue"``, ``"list"`` or ``"prose"``.

    The label decides whether the paragraph may be merged with its neighbours
    into a window-sized passage, or has to be kept whole. A dialogue exchange
    split down the middle stops reading as an exchange, and half a list is not a
    list, so both are kept intact even when that overshoots the ceiling.

    Args:
        paragraph (str): The paragraph text.

    Returns:
        str: The kind label.
    """
    stripped = paragraph.lstrip()
    if not stripped:
        return "prose"
    if _LIST_OPENER.match(stripped):
        return "list"
    if stripped.startswith(_QUOTE_OPENERS):
        return "dialogue"
    return "prose"


def _token_count(doc, start, end):
    """Count non-whitespace spaCy tokens between two character offsets."""
    span = doc.char_span(start, end, alignment_mode="expand")
    if span is None:
        return 0
    return sum(1 for token in span if not token.is_space)


def _units(doc, text, spans):
    """Group paragraphs into indivisible units.

    A prose paragraph is its own unit. A run of consecutive dialogue or list
    paragraphs becomes one unit, because the run is the thing that has to stay
    whole, not each line of it.

    Returns:
        list[dict]: Each with ``start``, ``end``, ``tokens``, ``kind`` and
            ``whole`` (whether the unit may never be split or merged apart).
    """
    units = []
    for start, end in spans:
        kind = classify_paragraph(text[start:end])
        tokens = _token_count(doc, start, end)
        if (
            units
            and kind in ("dialogue", "list")
            and units[-1]["kind"] == kind
        ):
            previous = units[-1]
            previous["end"] = end
            previous["tokens"] = _token_count(doc, previous["start"], end)
            continue
        units.append(
            {
                "start": start,
                "end": end,
                "tokens": tokens,
                "kind": kind,
                "whole": kind in ("dialogue", "list"),
            }
        )
    return units


def segment(doc, text=None):
    """Split a parsed document into candidate passages.

    Paragraphs are merged in order until each passage reaches
    :data:`MIN_PASSAGE_TOKENS`, and closed before it would pass
    :data:`MAX_PASSAGE_TOKENS`. No passage ever splits a paragraph: where a
    single paragraph, dialogue run or list run is longer than the ceiling on its
    own, it is emitted whole and marked ``oversized``.

    Args:
        doc (spacy.tokens.Doc): The parsed document.
        text (str, optional): The original text. Defaults to ``doc.text``, which
            is what the analyser parsed.

    Returns:
        list[Passage]: Every passage in document order, including the
            non-candidates, so document-level totals stay complete.
    """
    text = doc.text if text is None else text
    spans = paragraph_spans(text)
    units = _units(doc, text, spans)

    passages = []
    batch = []

    def close():
        """Emit the accumulated units as one passage."""
        if not batch:
            return
        start = batch[0]["start"]
        end = batch[-1]["end"]
        tokens = sum(unit["tokens"] for unit in batch)
        kinds = {unit["kind"] for unit in batch}
        kind = kinds.pop() if len(kinds) == 1 else "prose"
        passages.append(
            Passage(
                index=len(passages),
                start=start,
                end=end,
                text=text[start:end],
                token_count=tokens,
                kind=kind,
                is_candidate=tokens >= MIN_CANDIDATE_TOKENS,
                oversized=tokens > MAX_PASSAGE_TOKENS,
            )
        )
        batch.clear()

    for unit in units:
        running = sum(item["tokens"] for item in batch)

        # An indivisible unit longer than the ceiling absorbs whatever has
        # accumulated so far rather than leaving it stranded as a passage below
        # the floor. The unit is over the ceiling either way, so the extra
        # paragraph costs nothing that is not already lost.
        if unit["tokens"] > MAX_PASSAGE_TOKENS:
            batch.append(unit)
            close()
            continue

        if running + unit["tokens"] > MAX_PASSAGE_TOKENS:
            if running >= MIN_PASSAGE_TOKENS:
                close()
            # Otherwise the choice is between a passage over the ceiling and one
            # under the floor. Overshooting is the lesser fault: a long exemplar
            # still shows the author's rhythm, while a 60-token one does not.

        batch.append(unit)
        if sum(item["tokens"] for item in batch) >= TARGET_PASSAGE_TOKENS:
            close()

    close()
    return passages


def candidates(passages):
    """Return only the passages eligible to become exemplars."""
    return [passage for passage in passages if passage.is_candidate]
