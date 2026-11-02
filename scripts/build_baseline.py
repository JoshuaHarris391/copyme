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
    poetry run python3 scripts/build_baseline.py --verify
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
    """Compare the spreads of the corpus halves, feature by feature.

    The question this answers is whether the corpus is large enough for each
    feature's spread to be trusted. If adding the second half materially changed
    a spread, it is not -- and because the spread is the denominator of every
    z-score, an unreliable spread means unreliable rule suppression for that one
    feature.

    The report carries the means and spreads, not only the percentage, because
    the percentage alone is misleading for a rare feature. A feature occurring
    0.05 times per 1,000 words can show a 34% difference between halves while
    moving by almost nothing in absolute terms, and such a feature needs far
    more data to converge than a common one does. Whether that matters is a
    judgement about the feature, so the numbers needed to make it are printed.

    Args:
        rows (list[dict]): Per-passage scalar dictionaries.

    Returns:
        tuple[float, list[dict]]: The worst relative difference, and a record
            per feature that exceeded :data:`STABILITY_TOLERANCE`, worst first.
    """
    if len(rows) < 4:
        return float("inf"), [{"feature": "corpus too small to split"}]

    middle = len(rows) // 2
    means, overall = summarise(rows)
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
            unstable.append(
                {
                    "feature": name,
                    "relative_difference": round(difference, 4),
                    "mean": means[name],
                    "spread": overall[name],
                    "spread_first_half": a,
                    "spread_second_half": b,
                }
            )
    unstable.sort(key=lambda row: -row["relative_difference"])
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


# How far a recomputed mean or spread may sit from the committed one before
# --verify calls it a mismatch. Tight enough to catch a corpus that changed
# without a rebuild, loose enough to survive a spaCy patch release nudging a
# tag or a sentence boundary.
VERIFY_TOLERANCE = 1e-4


def verify(rows, means, spreads):
    """Check the committed baseline still matches what the corpus produces.

    The gap this closes: ``baseline.json`` is a build artefact that is committed
    by hand, so the corpus and the file it was computed from can drift apart
    silently. Nothing else notices. A passage added to the corpus without a
    rebuild leaves every z-score in the tool computed against numbers that no
    longer describe the corpus, and rule suppression quietly uses a stale null
    hypothesis.

    This recomputes the whole thing and compares. It is the check a maintainer
    would otherwise have to remember to run after step 4 of the refresh
    procedure.

    Args:
        rows (list[dict]): Per-passage scalar dictionaries from the corpus.
        means (dict): Feature means just recomputed from ``rows``.
        spreads (dict): Feature spreads just recomputed from ``rows``.

    Returns:
        int: 0 if the committed file matches, 1 if it is missing or disagrees.
    """
    if not OUTPUT.exists():
        print(f"\n{OUTPUT} does not exist. Run without --verify to build it.", file=sys.stderr)
        return 1

    committed = json.loads(OUTPUT.read_text(encoding="utf-8"))
    problems = []

    if committed.get("passages") != len(rows):
        problems.append(
            f"passage count: corpus has {len(rows)}, "
            f"baseline.json records {committed.get('passages')}"
        )

    for label, recomputed in (("mean", means), ("spread", spreads)):
        stored = committed.get(f"{label}s", {})
        for name in FEATURE_NAMES:
            if name not in stored:
                problems.append(f"{label} for {name} is missing from baseline.json")
                continue
            expected, actual = recomputed[name], stored[name]
            scale = max(abs(expected), abs(actual), 1e-9)
            if abs(expected - actual) / scale > VERIFY_TOLERANCE:
                problems.append(
                    f"{label} for {name}: corpus gives {expected:.6f}, "
                    f"baseline.json records {actual:.6f}"
                )

    if problems:
        print(
            f"\nbaseline.json does not match the corpus ({len(problems)} "
            f"discrepancies). Rebuild it with --bump:\n",
            file=sys.stderr,
        )
        for problem in problems[:20]:
            print(f"    {problem}", file=sys.stderr)
        if len(problems) > 20:
            print(f"    ... and {len(problems) - 20} more", file=sys.stderr)
        return 1

    print(
        f"\nbaseline.json matches the corpus: {len(rows)} passages, "
        f"{len(FEATURE_NAMES)} features, version {committed.get('version')}"
    )
    return 0


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
    parser.add_argument(
        "--verify",
        action="store_true",
        help=(
            "Recompute from the corpus and exit non-zero if the committed "
            "baseline.json disagrees. Writes nothing."
        ),
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
            f"  {len(unstable)} of {len(FEATURE_NAMES)} features above the "
            f"{STABILITY_TOLERANCE:.0%} tolerance. Their spreads are not yet "
            f"converged, so rule suppression on these is less reliable than on "
            f"the rest:\n"
        )
        print(f"    {'feature':32} {'diff':>6} {'mean':>10} {'spread':>10}")
        for row in unstable:
            print(
                f"    {row['feature']:32} {row['relative_difference']:6.0%} "
                f"{row['mean']:10.4f} {row['spread']:10.4f}"
            )

    if args.check:
        return 0

    if args.verify:
        return verify(rows, means, spreads)

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
            "unstable_features": unstable,
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
