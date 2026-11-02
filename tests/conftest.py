"""Shared fixtures for the v2 test suite.

Parsing is the expensive part of copyme, and the golden samples are whole books.
Every fixture here is session-scoped and parses a **slice** of a sample rather
than the whole thing: large enough that segmentation, selection and the feature
rates behave as they do on real input, small enough that the suite stays quick.

The slice sizes are deliberate, not arbitrary:

- ``SLICE_CHARS`` is about 25,000 characters, which is roughly 4,000 words. That
  clears the 2,000-word floor at which copyme says a profile is recognisable, so
  the fixtures exercise the ordinary path rather than the thin-sample path.
- The thin fixture is deliberately under that floor, so the thin-sample
  behaviour has something to test against.
"""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# About 4,000 words: over the 2,000-word floor, under the point where the suite
# starts to feel slow.
SLICE_CHARS = 25_000

# Deliberately below the floor.
THIN_WORDS = 300


def sample_text(slug, chars=SLICE_CHARS):
    """Read the opening ``chars`` characters of a golden sample.

    Args:
        slug (str): A fixture name -- ``london``, ``james``, ``twain`` or
            ``dialogue``.
        chars (int): How much to read.

    Returns:
        str: The slice, cut back to the last blank line so a passage is never
            truncated mid-paragraph.
    """
    text = (FIXTURES / f"{slug}.txt").read_text(encoding="utf-8")[:chars]
    # Cut at a paragraph boundary: a half paragraph at the end would be measured
    # as a short paragraph and skew the paragraph-length features.
    cut = text.rfind("\n\n")
    return text[:cut] if cut > 0 else text


@pytest.fixture(scope="session")
def read_sample():
    """The :func:`sample_text` reader, for tests that need their own slices."""
    return sample_text


@pytest.fixture(scope="session")
def london_text():
    """Jack London: spare, plain, short declaratives."""
    return sample_text("london")


@pytest.fixture(scope="session")
def james_text():
    """Henry James: long subordinated sentences, heavy parenthesis."""
    return sample_text("james")


@pytest.fixture(scope="session")
def dialogue_text():
    """Oscar Wilde: short turns and near-continuous dialogue.

    This is the fixture shaped like the input copyme actually receives -- chat
    and persona text -- and it exists to keep segmentation honest about
    one-line paragraphs.
    """
    return sample_text("dialogue")


@pytest.fixture(scope="session")
def london(london_text):
    """A parsed analyser for the London slice."""
    from copyme import StyleAnalyser

    return StyleAnalyser(london_text)


@pytest.fixture(scope="session")
def james(james_text):
    """A parsed analyser for the James slice."""
    from copyme import StyleAnalyser

    return StyleAnalyser(james_text)


@pytest.fixture(scope="session")
def dialogue(dialogue_text):
    """A parsed analyser for the Wilde slice."""
    from copyme import StyleAnalyser

    return StyleAnalyser(dialogue_text)


@pytest.fixture(scope="session")
def london_profile(london):
    """A standard-size profile built from the London slice."""
    from copyme import build_profile

    return build_profile(london, size="standard")


@pytest.fixture(scope="session")
def james_profile(james):
    """A standard-size profile built from the James slice."""
    from copyme import build_profile

    return build_profile(james, size="standard")


@pytest.fixture(scope="session")
def held_out_profile(london_profile):
    """A profile with passages left over, for the live contrastive tier.

    The live tier writes against passages the selector did **not** choose, so it
    needs a profile whose selection is smaller than its ranking. A Standard
    profile of a 4,600-word slice takes every candidate passage there is, which
    is correct behaviour and leaves nothing spare -- so these tests use the
    Compact size, where three to five passages are chosen from the same ranking.
    """
    return london_profile.at_size("compact")


@pytest.fixture(scope="session")
def baseline():
    """The packaged generic-prose baseline."""
    from copyme import load_baseline

    return load_baseline()
