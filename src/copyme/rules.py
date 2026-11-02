"""Turn measurements into instructions a model can follow.

The pre-prompt used to carry numbers and a metric dictionary. A model cannot act
on ``modal_hedging_ratio: 0.04``; it can act on "hedge rarely: when something is
uncertain, say so once and move on". This module is that translation, and it
follows five principles from the spec, in priority order.

1. **Behaviour, not metric names.** No rule names a feature.
2. **A frequency on every rule.** "Open about one sentence in five with *And*"
   -- never "opens sentences with conjunctions". Whether a habit occurs is the
   easy half; how often is the half that makes imitation convincing.
3. **Distribution over mean where it matters.** Sentence length renders from
   quartiles, because asking for a mean produces the uniform rhythm readers
   identify as machine-written.
4. **Negative rules are allowed and short.** "No semicolons."
5. **Register descriptors stay categorical but grounded.** Not
   "conversational" but "conversational: roughly one discourse marker a
   sentence".

A feature within half a standard deviation of the generic-prose baseline
produces no rule at all. The model's default is already right, and every extra
line dilutes the ones that matter.
"""

from dataclasses import dataclass

from .baseline import SUPPRESSION_THRESHOLD, load_baseline
from .features import SHORT_SENTENCE_WORDS, comparative

# How far either side of the author's value the scorer accepts, as a share of
# the value, when the author's own passage-level spread is unavailable. Wide
# enough that ordinary variation does not read as drift.
RELATIVE_TOLERANCE = 0.35

# Bands never narrow past this, so a feature whose author value is near zero
# does not produce a band nothing can land in.
_BAND_FLOOR = 0.02

# Features that are measured but deliberately produce no rule.
#
# `cohesive_harmony` is kept as a descriptor because the research gave no
# evidence a model can act on it. `function_word_frequency` is an
# authorship-attribution feature with no generation value. `named_entity_per_1k`
# describes subject matter, and importing an author's subjects is the thing the
# instruction block explicitly forbids. All three stay in the JSON profile.
NO_RULE_FEATURES = frozenset(
    {
        "cohesive_harmony",
        "function_word_frequency",
        "named_entity_per_1k",
        # Covered by the sentence-length rule, which renders from the whole
        # distribution rather than one quartile at a time.
        "sentence_length_q1",
        "sentence_length_q3",
        "sentence_length_p90",
        "share_short_sentences",
        "share_long_sentences",
        "paragraph_sentences_q3",
        "opening_sentence_length",
    }
)


@dataclass(frozen=True)
class Rule:
    """One followable instruction, with everything needed to re-render it.

    The same record becomes a line of prose in the prompt, a line on the voice
    card, and a threshold for the scorer, so none of it is restated anywhere.

    Attributes:
        feature (str): The feature it came from. Not shown to the model.
        direction (str): ``"longer"``, ``"shorter"``, ``"more"``, ``"fewer"``,
            ``"never"``, ``"always"`` or ``"match"``.
        magnitude (str): The author's level in words a person reads, such as
            "about 11 words" or "roughly once a paragraph".
        comparison (str): A second fact that stops the magnitude being read as a
            target to hit exactly, such as "a third are under six words".
        prose (str): The sentence sent to the model.
        band (tuple[float, float]): The range the scorer accepts.
        salience (float): How many baseline standard deviations the author sits
            from generic prose. Used for ordering and for the voice card's
            selection of the top rules.
    """

    feature: str
    direction: str
    magnitude: str
    comparison: str
    prose: str
    band: tuple
    salience: float


def _band(value, spread=None):
    """The range the scorer will accept for a feature.

    Preferring the author's own passage-to-passage spread, where it is known, is
    what makes "in band" mean "within this author's natural variation" rather
    than within an arbitrary percentage. A writer whose sentence length barely
    moves gets a tight band; one who swings between four words and forty gets a
    loose one, which is correct in both cases.

    Args:
        value (float): The author's value.
        spread (float, optional): The author's own standard deviation for this
            feature across their passages.

    Returns:
        tuple[float, float]: Lower and upper bound. Never extends below zero,
            because every feature here is a rate or a length.
    """
    slack = max(abs(value) * RELATIVE_TOLERANCE, spread or 0.0, _BAND_FLOOR)
    return (round(max(0.0, value - slack), 4), round(value + slack, 4))


def _ordinal_fraction(share):
    """Render a share of sentences as "one in N".

    Args:
        share (float): 0.0 to 1.0.

    Returns:
        str: Such as "one in five", or "almost every" past four fifths.
    """
    if share <= 0:
        return "none"
    if share >= 0.8:
        return "almost every"
    if share >= 0.55:
        return "more than half of"
    words = {
        2: "one in two",
        3: "one in three",
        4: "one in four",
        5: "one in five",
        6: "one in six",
        7: "one in seven",
        8: "one in eight",
        9: "one in nine",
        10: "one in ten",
    }
    denominator = round(1 / share)
    if denominator in words:
        return words[denominator]
    if denominator <= 20:
        return "one in fifteen" if denominator <= 17 else "one in twenty"
    return f"about one in {int(round(denominator / 10) * 10)}"


def _frequency(per_1k, words_per_paragraph):
    """Render a per-1,000-word rate in the most natural unit available.

    A rate means more to a reader at the scale they write at. Once a paragraph
    is easier to act on than 12.4 per thousand words, and once every three
    paragraphs is easier than 2.1.

    Args:
        per_1k (float): Occurrences per 1,000 words.
        words_per_paragraph (float): The author's paragraph length in words,
            used to pick the unit.

    Returns:
        str: Such as "about once a paragraph" or "roughly every 400 words".
    """
    if per_1k <= 0:
        return "never"

    if words_per_paragraph > 0:
        per_paragraph = per_1k * words_per_paragraph / 1000.0
        if per_paragraph >= 1.6:
            return f"about {per_paragraph:.0f} times a paragraph"
        if per_paragraph >= 0.7:
            return "about once a paragraph"
        if per_paragraph >= 0.25:
            # Rounding can land on 1, which would read "once every 1
            # paragraphs"; that is the branch above, said properly.
            gap = max(2, round(1 / per_paragraph))
            return f"about once every {gap} paragraphs"

    every = 1000.0 / per_1k
    if every >= 1000:
        return f"once every {every / 1000:.1f} thousand words"
    return f"roughly every {int(round(every / 50) * 50) or 50} words"


class _Renderer:
    """Base for the per-feature renderers.

    Each subclass owns one rule: which feature it reads, whether it has anything
    to say about a given author, and the prose it produces. Keeping them separate
    is what lets a rule's phrasing be revised without touching selection or any
    other rule.
    """

    feature = ""
    # Renderers run in this order when salience ties, so output is deterministic.
    priority = 50

    def applies(self, context):
        """Whether this renderer has something worth saying. Default: yes."""
        return True

    def render(self, context):
        """Return ``(direction, magnitude, comparison, prose)``."""
        raise NotImplementedError


class _SentenceLength(_Renderer):
    feature = "sentence_length_median"
    priority = 1

    def render(self, context):
        scalars = context["scalars"]
        q1 = int(round(scalars["sentence_length_q1"]))
        q3 = int(round(scalars["sentence_length_q3"]))
        p90 = int(round(scalars["sentence_length_p90"]))
        median = int(round(scalars["sentence_length_median"]))
        short = scalars["share_short_sentences"]

        magnitude = f"most sentences {q1} to {q3} words"
        comparison = f"one in ten runs past {p90}"
        if short >= 0.1:
            comparison += (
                f"; {_ordinal_fraction(short)} is under "
                f"{SHORT_SENTENCE_WORDS + 1} words"
            )

        prose = (
            f"Keep most sentences between {q1} and {q3} words, with a median of "
            f"about {median}. {comparison[0].upper()}{comparison[1:]}. Do not "
            f"even the lengths out: the spread is the rhythm."
        )
        return (
            comparative(self.feature, context["z"]),
            magnitude,
            comparison,
            prose,
        )


class _SentenceVariation(_Renderer):
    feature = "sentence_length_cv"
    priority = 2

    def render(self, context):
        value = context["value"]
        if context["z"] < 0:
            magnitude = f"sentence lengths cluster tightly (variation {value:.2f})"
            prose = (
                "Keep sentence lengths close to one another. This writer does "
                "not alternate long and short for effect."
            )
        else:
            magnitude = f"sentence length swings widely (variation {value:.2f})"
            prose = (
                "Swing sentence length deliberately: follow a long sentence "
                "with a short one. The unevenness is the point."
            )
        return (
            comparative(self.feature, context["z"]),
            magnitude,
            f"coefficient of variation {value:.2f}",
            prose,
        )


class _ConjunctionOpeners(_Renderer):
    feature = "opener_conjunction_rate"
    priority = 3

    def render(self, context):
        share = context["value"]
        literal = [
            word for word, _ in context["detail"].get("top_openers", [])
            if word in ("and", "but", "so", "or", "yet", "because", "though", "if", "when")
        ][:3]
        examples = ", ".join(f"*{word.capitalize()}*" for word in literal)
        magnitude = f"{_ordinal_fraction(share)} sentences"

        if context["z"] < 0:
            prose = (
                "Do not open sentences with a conjunction. Start with the "
                "subject."
            )
        else:
            prose = (
                f"Open {magnitude} with a conjunction"
                + (f" -- {examples}" if examples else "")
                + ". Not more: the habit stops reading as a habit when every "
                "sentence has it."
            )
        return (
            comparative(self.feature, context["z"]),
            magnitude,
            f"{share:.0%} of sentence openings",
            prose,
        )


class _OpenerConcentration(_Renderer):
    feature = "opener_concentration"
    priority = 20

    def applies(self, context):
        return bool(context["detail"].get("top_openers"))

    def render(self, context):
        word, count = context["detail"]["top_openers"][0]
        share = context["value"]
        magnitude = f"*{word.capitalize()}* opens {_ordinal_fraction(share)} sentences"
        if context["z"] < 0:
            prose = (
                "Vary how sentences begin. No single opening word should recur "
                "often enough to notice."
            )
        else:
            prose = (
                f"{magnitude}. Reuse it at about that rate rather than "
                f"avoiding the repetition."
            )
        return (
            comparative(self.feature, context["z"]),
            magnitude,
            f"{count} occurrences",
            prose,
        )


class _Contractions(_Renderer):
    feature = "contraction_rate"
    priority = 4

    def render(self, context):
        rate = context["value"]
        if rate >= 0.85:
            direction, magnitude = "always", "always contracts"
            prose = (
                "Always contract: *don't*, *it's*, *I'm*. An uncontracted "
                "auxiliary reads as a different person."
            )
        elif rate <= 0.08:
            direction, magnitude = "never", "never contracts"
            prose = (
                "Never contract. Write *do not* and *it is* in full, "
                "throughout."
            )
        else:
            direction = comparative(self.feature, context["z"])
            magnitude = f"contracts about {rate:.0%} of the time"
            prose = (
                f"Contract about {rate:.0%} of the time -- mixed, not "
                f"consistent. Both forms appear in the same paragraph."
            )
        return direction, magnitude, f"contraction rate {rate:.2f}", prose


class _Person(_Renderer):
    feature = "second_person_per_1k"
    priority = 5

    def render(self, context):
        frequency = _frequency(context["value"], context["words_per_paragraph"])
        magnitude = f"addresses the reader {frequency}"
        if context["z"] < 0:
            prose = (
                "Do not address the reader as *you*. Keep the writing "
                "impersonal."
            )
        else:
            prose = f"Address the reader directly as *you*, {frequency}."
        return (
            comparative(self.feature, context["z"]),
            magnitude,
            f"{context['value']:.1f} per 1,000 words",
            prose,
        )


class _FirstPerson(_Renderer):
    feature = "first_person_singular_per_1k"
    priority = 6

    def render(self, context):
        frequency = _frequency(context["value"], context["words_per_paragraph"])
        magnitude = f"writes as *I* {frequency}"
        if context["z"] < 0:
            prose = "Stay out of the first person. Do not write as *I*."
        else:
            prose = (
                f"Write in the first person, {frequency}. The writer is present "
                f"in the prose, not behind it."
            )
        return (
            comparative(self.feature, context["z"]),
            magnitude,
            f"{context['value']:.1f} per 1,000 words",
            prose,
        )


class _Questions(_Renderer):
    feature = "question_rate_per_1k"
    priority = 7

    def render(self, context):
        if context["value"] <= 0.01:
            return (
                "never",
                "never asks a question",
                "no question marks",
                "Never ask a question. Make statements.",
            )
        frequency = _frequency(context["value"], context["words_per_paragraph"])
        return (
            comparative(self.feature, context["z"]),
            f"asks a question {frequency}",
            f"{context['value']:.1f} per 1,000 words",
            f"Ask a question {frequency} -- genuine questions, not rhetorical "
            f"framing for an answer you then give.",
        )


class _Exclamations(_Renderer):
    feature = "exclamation_rate_per_1k"
    priority = 8

    def render(self, context):
        if context["value"] <= 0.01:
            return (
                "never",
                "never exclaims",
                "no exclamation marks",
                "Never use an exclamation mark.",
            )
        frequency = _frequency(context["value"], context["words_per_paragraph"])
        return (
            comparative(self.feature, context["z"]),
            f"exclaims {frequency}",
            f"{context['value']:.1f} per 1,000 words",
            f"Use an exclamation mark {frequency}, and only where the feeling "
            f"is real.",
        )


class _Punctuation(_Renderer):
    """Shared shape for the punctuation marks, which all render the same way."""

    mark = ""
    plural = ""
    priority = 10

    def names(self, context):
        """The singular and plural names of the mark, for this author.

        A hook rather than a pair of attributes because the dash renderer has to
        name the form the author actually uses, and the renderers are shared
        singletons -- writing the answer onto ``self`` would leak it into the
        next profile rendered.
        """
        return self.mark, self.plural

    def render(self, context):
        mark, plural = self.names(context)
        value = context["value"]
        if value <= 0.01:
            return (
                "never",
                f"no {plural}",
                f"no {plural} in the sample",
                f"Use no {plural}.",
            )
        article = "an" if mark[0] in "aeiou" else "a"
        frequency = _frequency(value, context["words_per_paragraph"])
        return (
            comparative(self.feature, context["z"]),
            f"{plural} {frequency}",
            f"{value:.1f} per 1,000 words",
            f"Use {article} {mark} {frequency}.",
        )


class _Dashes(_Punctuation):
    feature = "em_dash_per_1k"
    mark = "dash"
    plural = "dashes"
    priority = 9

    def names(self, context):
        form = context["detail"].get("dash_form") or "em dash"
        return form, (f"{form}es" if form.endswith("sh") else f"{form}s")

    def render(self, context):
        direction, magnitude, comparison, prose = super().render(context)
        if context["value"] > 0.01:
            form, _ = self.names(context)
            prose += f" This writer uses the {form} and no other dash form."
        return direction, magnitude, comparison, prose


class _Ellipses(_Punctuation):
    feature = "ellipsis_per_1k"
    mark = "ellipsis"
    plural = "ellipses"
    priority = 11


class _Parentheses(_Punctuation):
    feature = "parenthetical_per_1k"
    mark = "parenthesis"
    plural = "parentheses"
    priority = 12


class _Semicolons(_Punctuation):
    feature = "semicolon_per_1k"
    mark = "semicolon"
    plural = "semicolons"
    priority = 13


class _Colons(_Punctuation):
    feature = "colon_per_1k"
    mark = "colon"
    plural = "colons"
    priority = 14


class _Fragments(_Renderer):
    feature = "fragment_rate"
    priority = 15

    def render(self, context):
        share = context["value"]
        if share <= 0.01:
            return (
                "never",
                "no fragments",
                "every sentence has a finite verb",
                "Write complete sentences throughout. No fragments.",
            )
        magnitude = f"{_ordinal_fraction(share)} sentences is a fragment"
        return (
            comparative(self.feature, context["z"]),
            magnitude,
            f"{share:.0%} of sentences",
            f"Let {_ordinal_fraction(share)} sentences be a fragment -- no "
            f"finite verb, used for emphasis. Like this.",
        )


class _ParagraphLength(_Renderer):
    feature = "paragraph_sentences_median"
    priority = 16

    def render(self, context):
        median = context["value"]
        q3 = context["scalars"].get("paragraph_sentences_q3", median)
        magnitude = f"paragraphs of about {median:.0f} sentences"
        comparison = f"rarely more than {max(1, int(round(q3)))}"
        if median <= 1.4:
            prose = (
                "Write one-sentence paragraphs. Each thought stands on its own "
                "line."
            )
        else:
            prose = (
                f"Write {magnitude}, {comparison}. Break on the turn in the "
                f"thought, not at a fixed length."
            )
        return (
            comparative(self.feature, context["z"]),
            magnitude,
            comparison,
            prose,
        )


class _ClosingSentence(_Renderer):
    feature = "closing_sentence_length"
    priority = 17

    def render(self, context):
        words = context["value"]
        median = context["scalars"].get("sentence_length_median", words)
        magnitude = f"closing sentences of about {words:.0f} words"
        if words < median * 0.8:
            prose = (
                f"End a paragraph on a short line -- about {words:.0f} words, "
                f"shorter than the ones before it. Do not close with a "
                f"summarising sentence."
            )
        else:
            prose = (
                f"End a paragraph at full length, about {words:.0f} words. The "
                f"last sentence carries as much as the rest."
            )
        return (
            comparative(self.feature, context["z"]),
            magnitude,
            f"against a median sentence of {median:.0f} words",
            prose,
        )


class _LowercaseStarts(_Renderer):
    feature = "lowercase_start_rate"
    priority = 25

    def applies(self, context):
        # Only worth a line when it is a real habit rather than a stray token.
        return context["value"] >= 0.05

    def render(self, context):
        share = context["value"]
        return (
            "more",
            f"{_ordinal_fraction(share)} sentences starts lower case",
            f"{share:.0%} of sentences",
            f"Start {_ordinal_fraction(share)} sentences in lower case. It is "
            f"deliberate, not an error.",
        )


class _AllCaps(_Renderer):
    feature = "allcaps_per_1k"
    priority = 26

    def applies(self, context):
        return context["value"] >= 0.5

    def render(self, context):
        frequency = _frequency(context["value"], context["words_per_paragraph"])
        return (
            "more",
            f"a word in capitals {frequency}",
            f"{context['value']:.1f} per 1,000 words",
            f"Put a word in capitals for emphasis {frequency}.",
        )


class _Emoji(_Renderer):
    feature = "emoji_per_1k"
    priority = 27

    def applies(self, context):
        return context["value"] >= 0.3

    def render(self, context):
        frequency = _frequency(context["value"], context["words_per_paragraph"])
        return (
            "more",
            f"an emoji {frequency}",
            f"{context['value']:.1f} per 1,000 words",
            f"Use an emoji {frequency}. No more than that.",
        )


class _Vocabulary(_Renderer):
    feature = "mattr"
    priority = 18

    def render(self, context):
        value = context["value"]
        if context["z"] < 0:
            prose = (
                "Repeat words rather than reaching for synonyms. This writer "
                "reuses the same plain vocabulary."
            )
        else:
            prose = (
                "Use a wide vocabulary, and do not repeat a distinctive word "
                "within a paragraph."
            )
        return (
            comparative(self.feature, context["z"]),
            f"vocabulary range {value:.2f}",
            "moving-average type-token ratio over 100-word windows",
            prose,
        )


class _Hedging(_Renderer):
    feature = "hedge_per_1k"
    priority = 19

    def render(self, context):
        value = context["value"]
        if context["z"] < 0 or value <= 0.5:
            return (
                "fewer",
                "almost no hedging",
                f"{value:.1f} hedges per 1,000 words",
                "Hedge rarely. Where something is uncertain, say so once and "
                "move on -- no *perhaps*, *it may be that*, *arguably*.",
            )
        frequency = _frequency(value, context["words_per_paragraph"])
        return (
            "more",
            f"hedges {frequency}",
            f"{value:.1f} per 1,000 words",
            f"Hedge {frequency}. The uncertainty is genuine and stays in.",
        )


class _Modals(_Renderer):
    feature = "modal_per_1k"
    priority = 21

    def render(self, context):
        frequency = _frequency(context["value"], context["words_per_paragraph"])
        if context["z"] < 0:
            return (
                "fewer",
                "few modal verbs",
                f"{context['value']:.1f} per 1,000 words",
                "Use few modal verbs. Prefer *is* to *could be*, *does* to "
                "*would tend to*.",
            )
        return (
            "more",
            f"a modal verb {frequency}",
            f"{context['value']:.1f} per 1,000 words",
            f"Use modal verbs -- *would*, *could*, *might* -- {frequency}.",
        )


class _DiscourseMarkers(_Renderer):
    feature = "discourse_marker_per_1k"
    priority = 22

    def render(self, context):
        value = context["value"]
        per_sentence = value * context["scalars"].get("sentence_length_median", 15) / 1000.0
        if context["z"] < 0:
            return (
                "fewer",
                "few discourse markers",
                f"{value:.0f} per 1,000 words",
                "Drop the connectives. No *however*, *moreover*, *that said* "
                "-- let the sentences sit next to each other.",
            )
        register = "conversational" if value >= 30 else "lightly marked"
        return (
            "more",
            f"{register}: {value:.0f} discourse markers per 1,000 words",
            f"roughly {per_sentence:.1f} a sentence",
            f"Write {register}: about {value:.0f} discourse markers per 1,000 "
            f"words, roughly {per_sentence:.1f} a sentence -- *well*, *so*, "
            f"*I mean*, *anyway*.",
        )


# Every renderer, in the order they are consulted when salience ties.
RENDERERS = (
    _SentenceLength(),
    _SentenceVariation(),
    _ConjunctionOpeners(),
    _Contractions(),
    _Person(),
    _FirstPerson(),
    _Questions(),
    _Exclamations(),
    _Dashes(),
    _Ellipses(),
    _Parentheses(),
    _Semicolons(),
    _Colons(),
    _Fragments(),
    _ParagraphLength(),
    _ClosingSentence(),
    _Vocabulary(),
    _Hedging(),
    _OpenerConcentration(),
    _Modals(),
    _DiscourseMarkers(),
    _LowercaseStarts(),
    _AllCaps(),
    _Emoji(),
)


def _words_per_paragraph(scalars):
    """Estimate paragraph length in words, for choosing a frequency's unit."""
    sentences = scalars.get("paragraph_sentences_median", 0.0)
    length = scalars.get("sentence_length_median", 0.0)
    return sentences * length


def render_rules(features, baseline=None, author_spreads=None, threshold=None):
    """Render every rule worth stating for an author.

    Args:
        features (copyme.features.FeatureSet): The document-level feature set.
        baseline (copyme.baseline.Baseline, optional): Defaults to the packaged
            baseline.
        author_spreads (dict, optional): The author's own passage-level standard
            deviation per feature, used to set each band to their natural
            variation rather than a flat percentage.
        threshold (float, optional): How many baseline standard deviations a
            feature must differ by before it earns a rule. Defaults to
            :data:`copyme.baseline.SUPPRESSION_THRESHOLD`.

    Returns:
        list[Rule]: Ordered by salience, most distinctive first. Deterministic
            for a fixed input, including the order.
    """
    baseline = load_baseline() if baseline is None else baseline
    threshold = SUPPRESSION_THRESHOLD if threshold is None else threshold
    scalars = features.scalars
    author_spreads = author_spreads or {}

    context_base = {
        "scalars": scalars,
        "detail": features.detail,
        "words_per_paragraph": _words_per_paragraph(scalars),
    }

    rules = []
    for index, renderer in enumerate(RENDERERS):
        name = renderer.feature
        if name in NO_RULE_FEATURES or name not in scalars:
            continue

        value = float(scalars[name])
        z = baseline.z(name, value)

        # Suppression: the model already does this, so saying it spends a line
        # and buys nothing. A feature with no baseline spread has no evidence
        # either way and is suppressed too.
        if abs(z) < threshold:
            continue

        context = dict(context_base, value=value, z=z, feature=name)
        if not renderer.applies(context):
            continue

        direction, magnitude, comparison, prose = renderer.render(context)
        if not magnitude or not prose:
            continue

        rules.append(
            (
                abs(z),
                -renderer.priority,
                index,
                Rule(
                    feature=name,
                    direction=direction,
                    magnitude=magnitude,
                    comparison=comparison,
                    prose=prose,
                    band=_band(value, author_spreads.get(name)),
                    salience=round(abs(z), 4),
                ),
            )
        )

    # Most distinctive first; ties fall back to the renderer's own priority and
    # then its position, so two calls on the same profile cannot differ.
    rules.sort(key=lambda row: (-row[0], -row[1], row[2]))
    return [row[3] for row in rules]


def rule_for(rules, feature):
    """Find the rule for a feature, or None.

    Args:
        rules (list[Rule]): Rendered rules.
        feature (str): A feature name.

    Returns:
        Rule | None: The matching rule.
    """
    for rule in rules:
        if rule.feature == feature:
            return rule
    return None
