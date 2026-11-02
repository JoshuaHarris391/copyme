"""Download the golden-sample fixtures from Project Gutenberg.

The fixtures are the evidence base for every snapshot test and for the blind
evaluation protocol, so how they were obtained has to be reproducible. This
script is that record: it names the source edition for each sample, strips the
Gutenberg licence header and footer, and writes the body to
``tests/fixtures/<slug>.txt`` alongside a ``<slug>.source.json`` provenance file.

Run it only when a fixture needs to be added or refreshed. The downloaded text
is committed, so the test suite never touches the network.

Usage:
    poetry run python3 scripts/fetch_fixtures.py
    poetry run python3 scripts/fetch_fixtures.py --only london
"""

import argparse
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# Four voices, chosen so the feature vector has to separate genuinely different
# habits rather than genuinely different subjects. The first three are the blind
# protocol's authors: all died more than 70 years ago, so the texts are out of
# copyright in both the UK and the US. The fourth is shaped like the input copyme
# actually receives -- short turns, heavy dialogue -- and exists to keep
# segmentation honest. It is never blind-tested, because no reader "knows" it the
# way a reader knows London or James.
SOURCES = {
    "london": {
        "title": "The Call of the Wild",
        "author": "Jack London",
        "gutenberg_id": 215,
        "voice": "spare and plain",
        "why": "Short declaratives, concrete nouns, little hedging.",
        "blind_tested": True,
    },
    "james": {
        "title": "The Turn of the Screw",
        "author": "Henry James",
        "gutenberg_id": 209,
        "voice": "ornate",
        "why": "Long subordinated sentences, heavy parenthesis.",
        "blind_tested": True,
    },
    "twain": {
        "title": "Adventures of Huckleberry Finn",
        "author": "Mark Twain",
        "gutenberg_id": 76,
        "voice": "conversational",
        "why": "First person, idiomatic, fragments and asides.",
        "blind_tested": True,
    },
    "dialogue": {
        "title": "The Importance of Being Earnest",
        "author": "Oscar Wilde",
        "gutenberg_id": 844,
        "voice": "short-turn dialogue",
        "why": (
            "One-line paragraphs and near-continuous dialogue: the closest "
            "public-domain analogue to the chat and persona text copyme is "
            "mostly given. Used for segmentation robustness, not for the "
            "blind protocol."
        ),
        "blind_tested": False,
    },
}

URL = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"

_START = re.compile(r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.I)
_END = re.compile(r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.I)


def strip_boilerplate(raw):
    """Return the work itself, without Gutenberg's licence header and footer.

    The markers have been stable for years but are not guaranteed, so a missing
    marker is reported rather than silently leaving the licence text in a
    fixture, where it would be measured as part of the author's style.

    Args:
        raw (str): The downloaded file contents.

    Returns:
        str: The body text, stripped of leading and trailing whitespace.

    Raises:
        ValueError: If either boundary marker is absent.
    """
    start = _START.search(raw)
    end = _END.search(raw)
    if start is None or end is None:
        raise ValueError(
            "Gutenberg boundary markers not found; refusing to write a fixture "
            "that may contain licence text."
        )
    return raw[start.end():end.start()].strip()


def word_count(text):
    """Count whitespace-separated words, which is close enough for provenance."""
    return len(text.split())


def fetch(slug, meta):
    """Download one fixture and write it with its provenance file.

    Args:
        slug (str): Fixture name, used for the filenames.
        meta (dict): The entry from :data:`SOURCES`.

    Returns:
        int: The fixture's word count.
    """
    url = URL.format(id=meta["gutenberg_id"])
    print(f"{slug}: fetching {url}")
    with urllib.request.urlopen(url, timeout=60) as response:
        raw = response.read().decode("utf-8-sig", errors="replace")

    body = strip_boilerplate(raw)
    words = word_count(body)

    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / f"{slug}.txt").write_text(body + "\n", encoding="utf-8")
    (FIXTURES / f"{slug}.source.json").write_text(
        json.dumps(
            {
                **meta,
                "slug": slug,
                "source_url": url,
                "source": "Project Gutenberg",
                "licence": "Public domain in the UK and the US",
                "retrieved": date.today().isoformat(),
                "word_count": words,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{slug}: {words:,} words")
    return words


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="Fetch a single fixture by slug.")
    args = parser.parse_args(argv)

    wanted = {args.only: SOURCES[args.only]} if args.only else SOURCES
    for slug, meta in wanted.items():
        words = fetch(slug, meta)
        if meta["blind_tested"] and words < 20_000:
            print(
                f"  warning: {slug} is under the 20,000-word floor the blind "
                f"protocol assumes",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
