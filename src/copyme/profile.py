"""The ``Profile``: the only thing exports and the scorer know about.

Everything upstream -- segmentation, features, selection, rule rendering -- exists
to produce one of these. Everything downstream reads one and nothing else. That
boundary is the point: adding a sixth export target must never require touching
the selector or the renderer, and the scorer must be able to work from a profile
loaded off disk a year later with no sample and no parse.

A profile serialises to JSON and back without loss, so a profile built once can
be re-rendered at any size without re-parsing.
"""

import hashlib
import json
from dataclasses import dataclass, field, replace

from .baseline import load_baseline
from .exemplars import DEFAULT_WEIGHTS, Exemplar, select_exemplars
from .features import FEATURE_NAMES, document_features
from .rules import Rule, render_rules

# The three size presets, in tokens.
#
# `total` is the whole pre-prompt; `exemplars` is the share of it the exemplar
# block may spend. The gap covers the instruction block, the rules, the
# known-failure notes and the voice card, which together run to a few hundred
# tokens at Compact and a couple of thousand at Full.
SIZE_PRESETS = {
    "compact": {
        "total": 2_000,
        "exemplars": 1_200,
        "min_n": 3,
        "max_n": 5,
        "use": "a system prompt field",
    },
    "standard": {
        "total": 8_000,
        "exemplars": 5_000,
        "min_n": 8,
        "max_n": 15,
        "use": "pasting into a chat",
    },
    "full": {
        "total": 30_000,
        "exemplars": 20_000,
        "min_n": 15,
        "max_n": 30,
        "use": "long-context models and Claude Projects",
    },
}

DEFAULT_SIZE = "standard"


def _copyme_version():
    """The installed package version, for the provenance footer.

    Read from the installed distribution rather than a constant in the package,
    so the version in an export can never disagree with the version that
    produced it.
    """
    try:
        from importlib.metadata import version

        return version("copyme")
    except Exception:  # pragma: no cover - only in a broken installation
        return "unknown"


# The word count below which a sample does not support a confident profile.
# Selection needs passages to choose between, and under this there are not
# enough of them for distinctiveness or diversity to mean much.
RECOMMENDED_MINIMUM_WORDS = 2_000

# The word count above which a profile is reliable rather than merely
# recognisable.
COMFORTABLE_WORDS = 10_000


class UnknownSizeError(ValueError):
    """Raised for a size that is not one of :data:`SIZE_PRESETS`."""


def resolve_size(size):
    """Return the preset for ``size``.

    Args:
        size (str): ``"compact"``, ``"standard"`` or ``"full"``.

    Returns:
        dict: The preset.

    Raises:
        UnknownSizeError: If the name is not a preset.
    """
    key = (size or DEFAULT_SIZE).lower()
    if key not in SIZE_PRESETS:
        raise UnknownSizeError(
            f"Unknown size {size!r}. Choose one of: "
            f"{', '.join(sorted(SIZE_PRESETS))}."
        )
    return SIZE_PRESETS[key]


@dataclass(frozen=True)
class Profile:
    """A complete, frozen style profile.

    Attributes:
        features (dict): The document-level scalar feature vector.
        detail (dict): Non-numeric findings -- literal openers, the dash form.
        rules (tuple[Rule, ...]): Rendered rules, most distinctive first.
        exemplars (tuple[Exemplar, ...]): The selected passages, in order.
        ranking (tuple[Exemplar, ...]): The full greedy order, so a larger size
            can be rendered from this profile without re-selecting.
        known_failures (tuple[str, ...]): Contrastive notes. Empty where the
            author is close enough to generic prose that there is no predictable
            drift to warn about.
        vocabulary (dict): ``style_words`` and ``idioms``, both filtered to
            manner rather than subject.
        metrics (dict): The nine v1 quantitative metrics and the qualitative
            assessments. Kept for the user and the JSON export; **not** prompt
            content any more.
        provenance (dict): Everything needed to tell two profiles apart: the
            copyme version, the sample's word count, the baseline version, the
            model the live contrastive tier ran against, the selection weights,
            and whether the content check had to be relaxed.
        size (str): The preset this profile was built for.
    """

    features: dict = field(default_factory=dict)
    detail: dict = field(default_factory=dict)
    rules: tuple = ()
    exemplars: tuple = ()
    ranking: tuple = ()
    known_failures: tuple = ()
    vocabulary: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    size: str = DEFAULT_SIZE

    @property
    def word_count(self):
        """int: Words in the sample this profile was built from."""
        return int(self.provenance.get("word_count", 0))

    @property
    def thin(self):
        """bool: Whether the sample was too small for a confident profile."""
        return self.word_count < RECOMMENDED_MINIMUM_WORDS

    @property
    def hash(self):
        """str: A short, stable digest of the profile's substance.

        Computed over the features, the rules and which passages were chosen --
        not over the provenance, so re-rendering the same profile at a different
        size does not change its identity.
        """
        payload = json.dumps(
            {
                "features": {name: self.features.get(name) for name in FEATURE_NAMES},
                "rules": [[rule.feature, rule.prose] for rule in self.rules],
                "exemplars": [exemplar.passage_index for exemplar in self.exemplars],
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    def at_size(self, size):
        """Return the same profile rendered for a different size.

        Re-selects from the stored ranking rather than from the sample, so this
        needs no parse and no analyser. That is what lets the CLI re-render a
        profile loaded from JSON.

        Args:
            size (str): A preset name.

        Returns:
            Profile: A new profile with the exemplars the new size affords.
        """
        preset = resolve_size(size)
        budget = preset["exemplars"]
        chosen = []
        used = 0
        for exemplar in self.ranking:
            fits = used + exemplar.token_count <= budget
            if not fits and len(chosen) >= preset["min_n"]:
                break
            chosen.append(exemplar)
            used += exemplar.token_count
            if len(chosen) >= preset["max_n"]:
                break
        return replace(self, exemplars=tuple(chosen), size=size.lower())

    def to_dict(self):
        """Serialise to a JSON-ready dictionary."""
        return {
            "schema": "copyme/profile/2",
            "size": self.size,
            # Derived, not stored: it changes with the size a profile is
            # rendered at, so keeping it out of `provenance` is what lets
            # to_dict -> from_dict round trip exactly.
            "profile_hash": self.hash,
            "features": dict(self.features),
            "detail": _jsonable(self.detail),
            "rules": [
                {
                    "feature": rule.feature,
                    "direction": rule.direction,
                    "magnitude": rule.magnitude,
                    "comparison": rule.comparison,
                    "prose": rule.prose,
                    "band": list(rule.band),
                    "salience": rule.salience,
                }
                for rule in self.rules
            ],
            "exemplars": [_exemplar_to_dict(item) for item in self.exemplars],
            "ranking": [_exemplar_to_dict(item) for item in self.ranking],
            "known_failures": list(self.known_failures),
            "vocabulary": _jsonable(self.vocabulary),
            "metrics": _jsonable(self.metrics),
            "provenance": dict(self.provenance),
        }

    def to_json(self, indent=2):
        """str: The profile as JSON."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, payload):
        """Rebuild a profile from :meth:`to_dict` output.

        Args:
            payload (dict): A serialised profile.

        Returns:
            Profile: An equal profile. ``to_dict`` then ``from_dict`` round
                trips without loss.
        """
        return cls(
            features=dict(payload.get("features", {})),
            detail=dict(payload.get("detail", {})),
            rules=tuple(
                Rule(
                    feature=row["feature"],
                    direction=row["direction"],
                    magnitude=row["magnitude"],
                    comparison=row["comparison"],
                    prose=row["prose"],
                    band=tuple(row["band"]),
                    salience=row.get("salience", 0.0),
                )
                for row in payload.get("rules", [])
            ),
            exemplars=tuple(_exemplar_from_dict(row) for row in payload.get("exemplars", [])),
            ranking=tuple(_exemplar_from_dict(row) for row in payload.get("ranking", [])),
            known_failures=tuple(payload.get("known_failures", [])),
            vocabulary=dict(payload.get("vocabulary", {})),
            metrics=dict(payload.get("metrics", {})),
            provenance=dict(payload.get("provenance", {})),
            size=payload.get("size", DEFAULT_SIZE),
        )

    @classmethod
    def from_json(cls, text):
        """Rebuild a profile from a JSON string."""
        return cls.from_dict(json.loads(text))


def _exemplar_to_dict(exemplar):
    return {
        "passage_index": exemplar.passage_index,
        "start": exemplar.start,
        "end": exemplar.end,
        "text": exemplar.text,
        "token_count": exemplar.token_count,
        "rank": exemplar.rank,
        "typicality": exemplar.typicality,
        "distinctiveness": exemplar.distinctiveness,
        "diversity": exemplar.diversity,
        "combined": exemplar.combined,
        "reason": exemplar.reason,
        "masked_text": exemplar.masked_text,
    }


def _exemplar_from_dict(row):
    return Exemplar(
        passage_index=row["passage_index"],
        start=row["start"],
        end=row["end"],
        text=row["text"],
        token_count=row["token_count"],
        rank=row.get("rank", 0),
        typicality=row.get("typicality", 0.0),
        distinctiveness=row.get("distinctiveness", 0.0),
        diversity=row.get("diversity", 0.0),
        combined=row.get("combined", 0.0),
        reason=row.get("reason", ""),
        masked_text=row.get("masked_text", ""),
    )


def _jsonable(value):
    """Convert tuples and Counters to JSON-safe equivalents, recursively.

    The feature detail holds tuples of ``(word, count)`` and the vocabulary
    holds Counters; both survive a JSON round trip only once flattened, and the
    round-trip equality test is an acceptance criterion.
    """
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def build_v2_profile(
    analyser,
    legacy=None,
    size=DEFAULT_SIZE,
    exemplar_budget=None,
    weights=DEFAULT_WEIGHTS,
    mask_names=True,
    contrastive="static",
    model="claude-sonnet-5",
    vocabulary_percentile=None,
    max_phrase_words=None,
    baseline=None,
):
    """Assemble a :class:`Profile` from a parsed analyser.

    The expensive work -- the spaCy parse -- has already happened by the time this
    is called, and nothing here repeats it.

    Args:
        analyser (copyme.StyleAnalyser): A parsed analyser.
        legacy (dict, optional): The v1 profile dictionary, stored under
            ``metrics`` so nothing is taken away from the user.
        size (str): A preset name, used when ``exemplar_budget`` is not given.
        exemplar_budget (int, optional): Tokens for the exemplar block,
            overriding the preset.
        weights (tuple): Selection weights.
        mask_names (bool): Recorded here and applied at render time.
        contrastive (str | None): ``"static"``, ``"live"`` or None.
        model (str): Recorded, and used by the live tier.
        vocabulary_percentile (float, optional): Recorded in provenance.
        max_phrase_words (int, optional): Recorded in provenance.
        baseline (copyme.baseline.Baseline, optional): Defaults to the packaged
            baseline.

    Returns:
        Profile: The frozen profile.
    """
    from .contrastive import static_notes  # Imported here to keep the cycle open.
    from .separation import (
        entity_texts,
        mask_names as mask_one_off_names,
        style_phrases,
        style_word_counts,
    )

    baseline = load_baseline() if baseline is None else baseline
    preset = resolve_size(size)
    budget = preset["exemplars"] if exemplar_budget is None else int(exemplar_budget)

    analyser.report_progress("exemplars", 0.0)
    selection = select_exemplars(
        analyser,
        budget_tokens=budget,
        min_n=preset["min_n"],
        max_n=preset["max_n"],
        weights=weights,
        baseline=baseline,
    )
    analyser.report_progress("exemplars", 1.0)

    # A sample too short to yield a single candidate passage still gets a
    # profile: the features and rules are computable without exemplars, and a
    # rules-only profile is more use than an error. The instruction block says
    # the sample was thin.
    features = selection.document_features
    if features is None:
        features = document_features(analyser.doc, analyser.text)

    rules = render_rules(
        features,
        baseline=baseline,
        author_spreads=selection.author_spreads or {},
    )
    analyser.report_progress("rules", 1.0)

    known_failures = ()
    if contrastive in ("static", "live"):
        known_failures = tuple(static_notes(features, baseline, rules))

    # Mask the whole ranking, not only the selected exemplars, so re-rendering
    # at a larger size never needs the analyser back.
    entity_counts = entity_texts(analyser)
    masked_ranking = tuple(
        replace(
            exemplar,
            masked_text=mask_one_off_names(
                analyser, exemplar.start, exemplar.end, counts=entity_counts
            ),
        )
        for exemplar in selection.ranking
    )
    masked_by_index = {item.passage_index: item for item in masked_ranking}
    masked_exemplars = tuple(
        masked_by_index[exemplar.passage_index] for exemplar in selection.exemplars
    )

    style_words = style_word_counts(analyser)
    phrase_source = (
        analyser.phrase_counts(max_phrase_words)
        if max_phrase_words
        else analyser.repeated_counts
    )
    idioms = style_phrases(analyser, phrase_source)

    vocabulary = {
        "style_words": [word for word, _ in style_words.most_common(40)],
        "idioms": [phrase for phrase, _ in idioms.most_common(20)],
    }

    provenance = {
        "copyme_version": _copyme_version(),
        "word_count": analyser.word_count,
        "sentence_count": analyser.sentence_count,
        "baseline_version": baseline.version,
        "baseline_status": baseline.status,
        "selection_weights": list(weights),
        "exemplar_budget": budget,
        "exemplars_used_tokens": selection.used_tokens,
        "candidate_passages": selection.candidate_count,
        "entity_check_relaxed": selection.entity_relaxed,
        "mask_names": bool(mask_names),
        "contrastive": contrastive,
        "contrastive_model": model if contrastive == "live" else None,
        "vocabulary_percentile": vocabulary_percentile,
        "max_phrase_words": max_phrase_words,
        "lexical_diversity_measure": "mattr",
    }

    return Profile(
        features=dict(features.scalars),
        detail=_jsonable(features.detail),
        rules=tuple(rules),
        exemplars=masked_exemplars,
        ranking=masked_ranking,
        known_failures=known_failures,
        vocabulary=vocabulary,
        metrics=_jsonable(legacy or {}),
        provenance=provenance,
        size=size.lower(),
    )
