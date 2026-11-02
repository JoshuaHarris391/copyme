"""Regenerate ``src/copyme/data/baseline.json`` from the baseline corpus.

This is a maintenance task, not a user step. The baseline defines what a model
writes unprompted, which is the null hypothesis every rule is tested against, so
it changes only when the corpus is refreshed.

The script reads every ``*.txt`` in ``tests/fixtures/baseline_corpus/``, splits
each file on a line containing only ``---``, parses each passage, computes the v2
feature set over it, and writes the per-feature mean and standard deviation.
Only numbers reach the output file.

It also reports the stability check the spec asks for: feature spreads computed
over the first half of the corpus against the second half. While those differ by
more than 5%, the corpus is too small for the spreads to be trusted.

Usage:
    poetry run python3 scripts/build_baseline.py
    poetry run python3 scripts/build_baseline.py --bump
    poetry run python3 scripts/build_baseline.py --check
"""

import argparse
import json
import statistics
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from copyme.features import FEATURE_NAMES, extract  # noqa: E402
from copyme.passages import paragraph_spans  # noqa: E402

CORPUS = ROOT / "tests" / "fixtures" / "baseline_corpus"
OUTPUT = ROOT / "src" / "copyme" / "data" / "baseline.json"

# How far the first half's spreads may differ from the second half's before the
# corpus is considered large enough. From spec 03's open question.
STABILITY_TOLERANCE = 0.05


def read_passages():
    """Return every passage in the corpus, in a stable order.

    Returns:
        list[str]: The passages. Files are read in sorted order so two runs on
            the same corpus produce byte-identical output.
    """
    passages = []
    for path in sorted(CORPUS.glob("*.txt")):
        for block in path.read_text(encoding="utf-8").split("\n---\n"):
            block = block.strip()
            if block:
                passages.append(block)
    return passages


def feature_rows(passages, nlp):
    """Compute the feature vector for each passage.

    Args:
        passages (list[str]): Corpus passages.
        nlp: A loaded spaCy pipeline.

    Returns:
        list[dict]: One scalar dictionary per passage.
    """
    rows = []
    for index, text in enumerate(passages, start=1):
        doc = nlp(text)
        features = extract(doc[:], paragraph_spans(text))
        rows.append(features.scalars)
        print(f"  passage {index}/{len(passages)}: {features.word_count} words")
    return rows


def summarise(rows):
    """Reduce per-passage vectors to a mean and a spread per feature.

    Args:
        rows (list[dict]): Per-passage scalar dictionaries.

    Returns:
        tuple[dict, dict]: ``(means, spreads)``, both keyed by feature name.
    """
    means = {}
    spreads = {}
    for name in FEATURE_NAMES:
        values = [float(row[name]) for row in rows if name in row]
        if not values:
            means[name] = 0.0
            spreads[name] = 0.0
            continue
        means[name] = round(statistics.fmean(values), 6)
        spreads[name] = round(
            statistics.stdev(values) if len(values) > 1 else 0.0, 6
        )
    return means, spreads


def stability(rows):
    """Compare the spreads of the corpus halves.

    The question this answers is whether the corpus is large enough. If adding
    the second half materially changed the spreads, it is not.

    Args:
        rows (list[dict]): Per-passage scalar dictionaries.

    Returns:
        tuple[float, list[str]]: The worst relative difference, and the names of
            the features that exceeded :data:`STABILITY_TOLERANCE`.
    """
    if len(rows) < 4:
        return float("inf"), ["corpus too small to split"]

    middle = len(rows) // 2
    _, first = summarise(rows[:middle])
    _, second = summarise(rows[middle:])

    worst = 0.0
    unstable = []
    for name in FEATURE_NAMES:
        a, b = first[name], second[name]
        scale = max(abs(a), abs(b))
        if scale == 0:
            continue
        difference = abs(a - b) / scale
        worst = max(worst, difference)
        if difference > STABILITY_TOLERANCE:
            unstable.append(f"{name} ({difference:.0%})")
    return worst, unstable


def next_version(bump):
    """Return the version string to write.

    Args:
        bump (bool): Whether to increment the major number. Bumping is the
            signal that the numbers changed materially, so every profile built
            against the old baseline is distinguishable.

    Returns:
        str: The version.
    """
    current = 0
    if OUTPUT.exists():
        try:
            current = int(str(json.loads(OUTPUT.read_text()).get("version", "0")).split(".")[0])
        except (json.JSONDecodeError, ValueError):
            current = 0
    return str(current + 1 if bump or current == 0 else current)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bump",
        action="store_true",
        help="Increment the baseline version. Use when the corpus changed.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report the stability check and write nothing.",
    )
    args = parser.parse_args(argv)

    passages = read_passages()
    if not passages:
        print(f"No passages found in {CORPUS}", file=sys.stderr)
        return 1

    provenance_path = CORPUS / "provenance.json"
    provenance = (
        json.loads(provenance_path.read_text(encoding="utf-8"))
        if provenance_path.exists()
        else {"status": "provisional"}
    )

    print(f"Reading {len(passages)} passages from {CORPUS}")
    import spacy

    nlp = spacy.load("en_core_web_sm")
    rows = feature_rows(passages, nlp)
    means, spreads = summarise(rows)

    worst, unstable = stability(rows)
    print(f"\nStability: worst spread difference between halves is {worst:.0%}")
    if unstable:
        print(
            f"  {len(unstable)} features above the {STABILITY_TOLERANCE:.0%} "
            f"tolerance; the corpus is too small for these spreads to be "
            f"trusted:\n    " + "\n    ".join(unstable[:10])
        )
        if len(unstable) > 10:
            print(f"    ... and {len(unstable) - 10} more")

    if args.check:
        return 0

    payload = {
        "version": next_version(args.bump),
        "status": provenance.get("status", "provisional"),
        "generated": date.today().isoformat(),
        "passages": len(rows),
        "corpus": {
            "source": provenance.get("source"),
            "model": provenance.get("model"),
            "approximate_words": provenance.get("approximate_words"),
        },
        "stability": {
            "worst_half_difference": round(worst, 4) if worst != float("inf") else None,
            "tolerance": STABILITY_TOLERANCE,
            "features_above_tolerance": len(unstable),
        },
        "features": list(FEATURE_NAMES),
        "means": means,
        "spreads": spreads,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"\nWrote {OUTPUT} at version {payload['version']} ({payload['status']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
