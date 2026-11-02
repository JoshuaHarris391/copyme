"""Choose which of the author's real passages go into the prompt.

This is the module v2 rests on. The evidence is that a model imitates a voice
from examples of that voice far better than from a description of it, so the
prompt's payload is the author's own writing and the measurements exist to decide
*which* of their writing.

Three scores, from the spec:

**Typicality** -- how close a passage sits to the author's own centre. An outlier
teaches the model a voice the author uses once.

**Distinctiveness** -- how far it sits from generic model prose. A passage the
model would have written anyway spends budget teaching it nothing.

**Diversity** -- how unlike the already-chosen passages it is. Ten near-copies of
the author's best paragraph cover one register out of several.

The three are combined with weights that are **parameters, not findings**. They
are intuitions until the blind protocol measures them.
"""

import math
from dataclasses import dataclass

from .baseline import load_baseline
from .features import (
    FEATURE_LABELS,
    FEATURE_NAMES,
    comparative,
    document_features,
    passage_features,
)
from .passages import candidates as candidate_passages
from .passages import segment

# Starting weights for typicality, distinctiveness and diversity. Exposed as a
# parameter on every entry point precisely because they are unmeasured.
DEFAULT_WEIGHTS = (0.4, 0.4, 0.2)

# A passage denser in names and places than this percentile of the author's own
# passages is about something specific, and will pull the model towards that
# subject rather than that manner.
ENTITY_PERCENTILE = 0.75

# Where the author writes about one subject throughout, the check above would
# reject nearly everything. Past this share of rejections it relaxes, and the
# profile records that it did.
ENTITY_RELAXATION_TRIGGER = 0.5
RELAXED_ENTITY_PERCENTILE = 0.95

# Selection never returns fewer than this many exemplars where the budget allows
# any at all, nor more than this many however large the budget.
DEFAULT_MIN_EXEMPLARS = 3
DEFAULT_MAX_EXEMPLARS = 30

# How far the greedy order is computed, independent of how many exemplars the
# caller asked for.
#
# Ranking only as deep as the selection would make a Standard profile
# unresizable -- there would be nothing to add when it was re-rendered at Full --
# and would leave the live contrastive tier with no held-out passages to test
# the model against. Both need the order to extend past the chosen set, so it is
# always computed to the largest preset plus a margin.
RANKING_DEPTH = DEFAULT_MAX_EXEMPLARS + 4

# A feature has to be this many of the author's own standard deviations from the
# baseline before it is worth naming in a reason.
_REASON_Z = 1.0


@dataclass(frozen=True)
class Exemplar:
    """One selected passage, with its scores and the reason it was chosen.

    Attributes:
        passage_index (int): Index of the source passage in the document.
        start (int): Character offset into the original text.
        end (int): Character offset one past the end.
        text (str): The passage, verbatim.
        masked_text (str): The same passage with one-off names replaced by role
            placeholders. Stored beside the verbatim text rather than applied at
            render time, because a profile loaded from JSON has no parse to find
            entities with -- and because keeping both means turning masking off
            is a choice of field, never a re-parse. Filled in by
            :func:`copyme.profile.build_v2_profile`; empty until then.
        token_count (int): spaCy tokens, used for budgeting.
        rank (int): Position in the greedy selection order, from zero. Budget
            truncation is a prefix of this order, which is what makes a larger
            budget a superset of a smaller one.
        typicality (float): Normalised 0 to 1, higher is more typical.
        distinctiveness (float): Normalised 0 to 1, higher is less generic.
        diversity (float): Normalised 0 to 1 at the moment of selection.
        combined (float): The weighted score it was selected on.
        reason (str): One line, for the user. **Never sent to the model.**
    """

    passage_index: int
    start: int
    end: int
    text: str
    token_count: int
    rank: int
    typicality: float
    distinctiveness: float
    diversity: float
    combined: float
    reason: str
    masked_text: str = ""


@dataclass(frozen=True)
class Selection:
    """The outcome of a selection, including what it had to compromise on.

    Attributes:
        exemplars (list[Exemplar]): Chosen, in greedy order.
        ranking (list[Exemplar]): The full greedy order before the budget was
            applied, so a larger budget can be served without re-selecting.
        entity_relaxed (bool): Whether the content check had to be relaxed
            because the author writes about one subject throughout.
        candidate_count (int): How many passages were eligible.
        budget_tokens (int): The budget requested.
        used_tokens (int): The budget actually spent. May exceed the budget
            where reaching ``min_n`` required it.
        author_spreads (dict): The author's own standard deviation per feature,
            across their passages. The rules renderer sets its bands from this.
        document_features (copyme.features.FeatureSet | None): The
            document-level feature set, computed here and passed on so the
            profile does not recompute it.
    """

    exemplars: list
    ranking: list
    entity_relaxed: bool
    candidate_count: int
    budget_tokens: int
    used_tokens: int
    author_spreads: dict = None
    document_features: object = None


def _percentile(values, fraction):
    """Linear-interpolated percentile over an unsorted list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = fraction * (len(ordered) - 1)
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return float(ordered[low])
    return float(ordered[low] + (ordered[high] - ordered[low]) * (position - low))


def _standardise(rows):
    """Convert per-passage feature values into z-scores within the document.

    Standardising against the author's *own* spread is what stops one feature
    dominating the geometry. A rate per 1,000 words and a ratio between zero and
    one are not comparable as raw numbers; as multiples of their own variation
    they are.

    Args:
        rows (dict): Passage index to scalar feature dictionary.

    Returns:
        tuple[dict, dict]: ``(vectors, spreads)`` -- passage index to z-vector in
            :data:`FEATURE_NAMES` order, and the author's own standard deviation
            per feature. The spreads are returned because the rules renderer
            needs them to set each band to this author's natural variation
            rather than a flat percentage, and computing them twice would mean
            walking every passage twice.
    """
    means = {}
    spreads = {}
    for name in FEATURE_NAMES:
        values = [float(scalars[name]) for scalars in rows.values()]
        if not values:
            means[name], spreads[name] = 0.0, 0.0
            continue
        mean = sum(values) / len(values)
        means[name] = mean
        if len(values) > 1:
            variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
            spreads[name] = math.sqrt(variance)
        else:
            spreads[name] = 0.0

    vectors = {}
    for index, scalars in rows.items():
        vectors[index] = [
            ((float(scalars[name]) - means[name]) / spreads[name])
            if spreads[name] > 1e-9
            else 0.0
            for name in FEATURE_NAMES
        ]
    return vectors, spreads


def _distance(left, right):
    """Root-mean-square distance between two z-vectors.

    Dividing by the number of features rather than summing keeps the value
    interpretable as "average standard deviations apart", which the reason text
    relies on.
    """
    if not left:
        return 0.0
    total = sum((a - b) ** 2 for a, b in zip(left, right))
    return math.sqrt(total / len(left))


def _normalise(scores):
    """Min-max a score dictionary onto 0 to 1.

    The three axes are measured in different units -- distance from a centroid,
    distance from the baseline, distance from the chosen set -- so weighting them
    only means something once they share a scale.

    Args:
        scores (dict): Key to raw score.

    Returns:
        dict: Key to normalised score. All 1.0 where every input is equal, since
            no key is then preferable to any other.
    """
    if not scores:
        return {}
    values = list(scores.values())
    low, high = min(values), max(values)
    if high - low < 1e-12:
        return {key: 1.0 for key in scores}
    return {key: (value - low) / (high - low) for key, value in scores.items()}


def _reason(exemplar_scores, passage, scalars, baseline, author_scalars, first_of_kind):
    """Compose the one-line explanation shown to the user.

    Built from whichever signals are actually strong for this passage, so the
    line says something specific or says the plain thing. It is assembled from
    the same numbers the selection used, which is what keeps it honest.

    Args:
        exemplar_scores (tuple): ``(typicality, distinctiveness, diversity)``,
            each normalised 0 to 1.
        passage (copyme.passages.Passage): The passage.
        scalars (dict): The passage's features.
        baseline (copyme.baseline.Baseline): The generic-prose baseline.
        author_scalars (dict): The document's features, for comparison.
        first_of_kind (bool): Whether this is the first passage of its kind in
            the selection, which is the clearest form of coverage.

    Returns:
        str: A non-empty reason, at most three clauses.
    """
    typicality, distinctiveness, diversity = exemplar_scores
    clauses = []

    if typicality >= 0.7:
        clauses.append("typical of the author")
    elif typicality <= 0.3:
        clauses.append("an outlier, kept for range")

    if distinctiveness >= 0.6:
        # Name the single feature furthest from generic prose: a reason that
        # names the habit is actionable, where "unlike generic prose" is not.
        furthest = None
        furthest_z = 0.0
        for name in FEATURE_NAMES:
            if name not in scalars:
                continue
            z = baseline.z(name, scalars[name])
            if abs(z) > abs(furthest_z):
                furthest, furthest_z = name, z
        if furthest is not None and abs(furthest_z) >= _REASON_Z:
            label = FEATURE_LABELS.get(furthest, furthest)
            clauses.append(
                f"{label} well {comparative(furthest, furthest_z)} than generic prose"
            )
        else:
            clauses.append("unlike generic prose")

    if first_of_kind and passage.kind != "prose":
        clauses.append(f"the first {passage.kind} passage selected")
    elif diversity >= 0.7:
        clauses.append("covers a register the others do not")

    if not clauses:
        clauses.append("fills out the author's range")
    return "; ".join(clauses[:3])


def select_exemplars(
    analyser,
    budget_tokens,
    min_n=DEFAULT_MIN_EXEMPLARS,
    max_n=DEFAULT_MAX_EXEMPLARS,
    weights=DEFAULT_WEIGHTS,
    baseline=None,
):
    """Choose exemplars from a parsed sample, to a token budget.

    The full greedy order is computed first and the budget then truncates it as a
    prefix. That is deliberate: it makes a larger budget's selection a strict
    superset of a smaller one's, matching the invariant the vocabulary
    percentile already holds. The cost is that a little budget can go unused
    where the next passage in the order does not fit, which is preferred to a
    selection that reshuffles whenever the slider moves.

    Args:
        analyser (copyme.StyleAnalyser): An analyser that has already parsed.
        budget_tokens (int): Tokens available for the exemplar block.
        min_n (int): Fewest exemplars to return where the budget allows any.
        max_n (int): Most to return, whatever the budget.
        weights (tuple[float, float, float]): Typicality, distinctiveness and
            diversity. A zero disables that axis.
        baseline (copyme.baseline.Baseline, optional): Defaults to the packaged
            baseline.

    Returns:
        Selection: The chosen exemplars and the full ranking behind them.
    """
    baseline = load_baseline() if baseline is None else baseline
    weight_typicality, weight_distinctiveness, weight_diversity = weights

    passages = segment(analyser.doc, analyser.text)
    eligible = candidate_passages(passages)
    if not eligible:
        return Selection([], [], False, 0, budget_tokens, 0, {}, None)

    per_passage = passage_features(analyser.doc, eligible, analyser.text)
    author = document_features(analyser.doc, analyser.text)
    eligible = [passage for passage in eligible if passage.index in per_passage]
    if not eligible:
        return Selection([], [], False, 0, budget_tokens, 0, {}, None)

    rows = {passage.index: per_passage[passage.index].scalars for passage in eligible}
    vectors, author_spreads = _standardise(rows)

    # The centroid of z-scored passages is the origin by construction, so
    # typicality is simply the negative distance from it.
    origin = [0.0] * len(FEATURE_NAMES)
    typicality_raw = {
        index: -_distance(vectors[index], origin) for index in vectors
    }
    distinctiveness_raw = {
        index: baseline.distance_from(rows[index]) for index in rows
    }

    # Content check: a passage denser in names than the author's own threshold is
    # about a subject, and imports it.
    entity_values = [rows[index]["named_entity_per_1k"] for index in rows]
    threshold = _percentile(entity_values, ENTITY_PERCENTILE)
    rejected = [index for index in rows if rows[index]["named_entity_per_1k"] > threshold]
    entity_relaxed = False
    if len(rejected) > ENTITY_RELAXATION_TRIGGER * len(rows):
        entity_relaxed = True
        threshold = _percentile(entity_values, RELAXED_ENTITY_PERCENTILE)
    allowed = [
        passage for passage in eligible
        if rows[passage.index]["named_entity_per_1k"] <= threshold
    ]
    if not allowed:
        allowed = list(eligible)
        entity_relaxed = True

    typicality = _normalise({p.index: typicality_raw[p.index] for p in allowed})
    distinctiveness = _normalise({p.index: distinctiveness_raw[p.index] for p in allowed})

    # Diversity has to land on the same 0-to-1 scale as the other two axes, which
    # needs a yardstick for "far apart". The exact largest pairwise distance
    # would cost a comparison for every pair of passages; twice the largest
    # distance from the centroid is an upper bound on it by the triangle
    # inequality, costs one pass, and is deterministic.
    span = 2.0 * max(_distance(vectors[p.index], origin) for p in allowed) or 1.0

    by_index = {passage.index: passage for passage in allowed}
    remaining = set(by_index)
    # Distance from each remaining passage to the nearest already-chosen one,
    # updated as each is chosen. Recomputing it from scratch each round would
    # make selection quadratic in the number of passages, which a long sample
    # would feel.
    nearest = {index: None for index in by_index}
    ranking = []
    kinds_seen = set()

    ranking_depth = max(max_n, RANKING_DEPTH)
    while remaining and len(ranking) < ranking_depth:
        best_index = None
        best_score = None
        best_parts = None
        for index in sorted(remaining):
            # Nothing selected yet means nothing is crowded.
            crowding = nearest[index]
            diversity = 1.0 if crowding is None else min(1.0, crowding / span)
            score = (
                weight_typicality * typicality[index]
                + weight_distinctiveness * distinctiveness[index]
                + weight_diversity * diversity
            )
            # Ties break on the lower index, so a fixed sample always produces a
            # fixed order.
            if best_score is None or score > best_score + 1e-12:
                best_index, best_score, best_parts = index, score, diversity

        passage = by_index[best_index]
        first_of_kind = passage.kind not in kinds_seen
        kinds_seen.add(passage.kind)
        ranking.append(
            Exemplar(
                passage_index=passage.index,
                start=passage.start,
                end=passage.end,
                text=passage.text,
                token_count=passage.token_count,
                rank=len(ranking),
                typicality=round(typicality[best_index], 4),
                distinctiveness=round(distinctiveness[best_index], 4),
                diversity=round(best_parts, 4),
                combined=round(best_score, 4),
                reason=_reason(
                    (typicality[best_index], distinctiveness[best_index], best_parts),
                    passage,
                    rows[best_index],
                    baseline,
                    author.scalars,
                    first_of_kind,
                ),
            )
        )
        remaining.discard(best_index)
        for index in remaining:
            gap = _distance(vectors[index], vectors[best_index])
            if nearest[index] is None or gap < nearest[index]:
                nearest[index] = gap

    selected = []
    used = 0
    for exemplar in ranking:
        fits = used + exemplar.token_count <= budget_tokens
        if not fits and len(selected) >= min_n:
            break
        # Below the floor the budget is deliberately overspent rather than
        # returning a selection too thin to show a voice. `used_tokens` records
        # what was actually spent, so a caller can see the overrun.
        selected.append(exemplar)
        used += exemplar.token_count
        if len(selected) >= max_n:
            break

    return Selection(
        exemplars=selected,
        ranking=ranking,
        entity_relaxed=entity_relaxed,
        candidate_count=len(allowed),
        budget_tokens=budget_tokens,
        used_tokens=used,
        author_spreads=author_spreads,
        document_features=author,
    )
