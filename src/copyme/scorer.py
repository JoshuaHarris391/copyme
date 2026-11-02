"""Tell the user whether it worked.

No version of copyme has ever done this. A user pasted a pre-prompt, read the
model's output and judged by feel. Scoring is nearly free -- copyme can already
profile any text -- and it turns the tool from "here is a prompt" into "here is a
prompt, and here is what drifted".

``score`` is **pure**: no model, no network, no file writes, no cache. That is a
test, not an intention, because the scorer is the one part of copyme a user might
run in a loop.

Two things the report deliberately does not claim, stated in its own footer:

- Passing every band is not the same as sounding right. The bands cover the
  habits copyme can measure, and a passage can satisfy all of them and still
  read wrongly.
- The blind test stays the arbiter. This is an instrument, not a verdict.
"""

import re
from dataclasses import dataclass

from .features import FEATURE_LABELS, comparative, document_features

# A shared run of at least this many consecutive words counts as reproduction
# rather than imitation, and is flagged. Twelve is long enough that ordinary
# English collocations do not trip it and short enough to catch a lifted
# sentence.
COPY_SPAN_WORDS = 12

# Relative gap below which a drift line is not worth printing even when the
# value technically sits outside its band. Keeps the report readable when a
# band is tight because the author is consistent.
MIN_REPORTABLE_GAP = 0.05

FOOTER = (
    "This measures the habits copyme can measure. A passage can pass every "
    "band and still not sound right, and agreement on these numbers can "
    "coexist with prose far more predictable than the author's. A blind read "
    "stays the arbiter."
)

_WORD = re.compile(r"[\w']+")


@dataclass(frozen=True)
class Drift:
    """One feature's comparison between the author and the generated text.

    Attributes:
        feature (str): The feature name.
        author (float): The author's value.
        generated (float): The generated text's value.
        verdict (str): ``"in band"``, ``"too high"`` or ``"too low"``.
        note (str): A phrase written as a correction, such as "sentences 40%
            longer than the author".
    """

    feature: str
    author: float
    generated: float
    verdict: str
    note: str


@dataclass(frozen=True)
class ScoreReport:
    """What a generated text did against a profile.

    Attributes:
        drifts (list[Drift]): One per rule in the profile, in the profile's
            order.
        in_band (float): Share of rules met, 0.0 to 1.0. Exactly 1.0 when no
            drift has a verdict other than "in band".
        copied_spans (list[str]): Runs of :data:`COPY_SPAN_WORDS` or more
            consecutive words shared with the sample.
        summary (str): Three lines for a human, written as a correction.
        footer (str): :data:`FOOTER`. Present in every report and every render.
    """

    drifts: list
    in_band: float
    copied_spans: list
    summary: str
    footer: str = FOOTER

    def to_dict(self):
        """Serialise for ``copyme score --json``."""
        return {
            "in_band": self.in_band,
            "drifts": [
                {
                    "feature": drift.feature,
                    "author": drift.author,
                    "generated": drift.generated,
                    "verdict": drift.verdict,
                    "note": drift.note,
                }
                for drift in self.drifts
            ],
            "copied_spans": list(self.copied_spans),
            "summary": self.summary,
            "footer": self.footer,
        }

    def render(self):
        """str: The report as text, footer included."""
        lines = [self.summary, ""]
        for drift in self.drifts:
            marker = " " if drift.verdict == "in band" else "!"
            lines.append(
                f"{marker} {FEATURE_LABELS.get(drift.feature, drift.feature)}: "
                f"{drift.generated:g} against the author's {drift.author:g} "
                f"({drift.verdict})"
            )
        if self.copied_spans:
            lines += ["", f"Copied from the sample ({len(self.copied_spans)}):"]
            lines += [f'  "{span}"' for span in self.copied_spans]
        lines += ["", self.footer]
        return "\n".join(lines)


def _word_sequence(text):
    """Lowercased words, for the copying check."""
    return [match.group(0).lower() for match in _WORD.finditer(text)]


def find_copied_spans(generated, sources, span=COPY_SPAN_WORDS, limit=10):
    """Find runs of words the generated text shares with the sample.

    This enforces the no-reproduction instruction the prompt carries but could
    not previously check. It compares word sequences rather than characters, so
    a change in punctuation or line breaking does not hide a lifted sentence.

    Args:
        generated (str): The model's output.
        sources (list[str]): The passages the model was shown, and any other
            sample text available.
        span (int): The run length that counts as copying.
        limit (int): Most spans to return.

    Returns:
        list[str]: The copied runs, longest first, de-duplicated.
    """
    if span <= 0:
        return []

    source_spans = set()
    for source in sources:
        words = _word_sequence(source)
        for start in range(len(words) - span + 1):
            source_spans.add(" ".join(words[start:start + span]))

    if not source_spans:
        return []

    generated_words = _word_sequence(generated)
    hits = []
    index = 0
    while index <= len(generated_words) - span:
        window = " ".join(generated_words[index:index + span])
        if window not in source_spans:
            index += 1
            continue
        # Extend the match as far as it goes, so one lifted sentence is reported
        # once at full length rather than as a dozen overlapping windows.
        end = index + span
        while end < len(generated_words):
            candidate = " ".join(generated_words[end - span + 1:end + 1])
            if candidate not in source_spans:
                break
            end += 1
        hits.append(" ".join(generated_words[index:end]))
        index = end

    seen = set()
    unique = []
    for hit in sorted(hits, key=lambda text: -len(text.split())):
        if hit in seen:
            continue
        seen.add(hit)
        unique.append(hit)
    return unique[:limit]


def _note(feature, author, generated, verdict):
    """Phrase a drift as the correction it would become.

    The summary feeds the contrastive block directly, so it is written in the
    form a correction takes -- "sentences 40% longer" -- rather than as a
    measurement. A summary phrased as a measurement would have to be rewritten
    before it could be used, and would drift out of step when it was.
    """
    label = FEATURE_LABELS.get(feature, feature)
    if verdict == "in band":
        return f"{label} matches"

    if author:
        change = abs(generated - author) / abs(author)
        if change >= 0.1:
            return (
                f"{label} {change:.0%} "
                f"{comparative(feature, generated - author)} than the author"
            )
    return f"{label} {comparative(feature, generated - author)} than the author"


def score(generated, against, sources=None):
    """Score a generated text against a profile.

    Args:
        generated (str): The model's output.
        against (copyme.profile.Profile): The profile to compare with. Its
            rules' bands are the thresholds.
        sources (list[str], optional): Text to check for copying. Defaults to
            the profile's exemplars, which is what the model was shown.

    Returns:
        ScoreReport: The comparison. ``in_band`` is 1.0 when no rule drifted.
    """
    import spacy

    from .analyser import nlp

    doc = nlp(generated) if not isinstance(generated, spacy.tokens.Doc) else generated
    features = document_features(doc, doc.text)

    drifts = []
    met = 0
    for rule in against.rules:
        author_value = float(against.features.get(rule.feature, 0.0))
        value = float(features.scalars.get(rule.feature, 0.0))
        low, high = rule.band

        if low <= value <= high:
            verdict = "in band"
            met += 1
        elif value > high:
            verdict = "too high"
        else:
            verdict = "too low"

        drifts.append(
            Drift(
                feature=rule.feature,
                author=round(author_value, 4),
                generated=round(value, 4),
                verdict=verdict,
                note=_note(rule.feature, author_value, value, verdict),
            )
        )

    in_band = round(met / len(drifts), 4) if drifts else 1.0

    if sources is None:
        sources = [exemplar.text for exemplar in against.exemplars]
    copied = find_copied_spans(generated if isinstance(generated, str) else doc.text, sources)

    worst = [drift for drift in drifts if drift.verdict != "in band"]
    worst.sort(key=lambda drift: -abs(drift.generated - drift.author))

    if not worst:
        headline = "In band on every rule."
    else:
        headline = "; ".join(drift.note for drift in worst[:3]) + "."
    summary = "\n".join(
        [
            headline,
            f"{in_band:.0%} of {len(drifts)} rules met.",
            (
                f"{len(copied)} copied span(s) of {COPY_SPAN_WORDS}+ words."
                if copied
                else "No copied spans."
            ),
        ]
    )

    return ScoreReport(
        drifts=drifts,
        in_band=in_band,
        copied_spans=copied,
        summary=summary,
    )
