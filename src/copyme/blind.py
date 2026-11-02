"""Run the blind pairwise test, which is the only thing that settles the claim.

copyme's claim is that a model given a profile writes recognisably like the
author. Nothing in this package tests that. :mod:`copyme.scorer` checks whether
generated text hits the author's measurements, which is a different and weaker
question: copyme chose those 36 features, so grading itself against them is
circular. It confirms the plumbing, not the voice.

The blind test asks people instead. A reader sees two passages, one genuinely by
the author and one written by a model following the profile, and picks the real
one without being told which is which. The score is the **pick rate**: the share
of judgements that correctly identified the author.

A lower pick rate is better. 50% is a coin flip and the ceiling of what
imitation can achieve; 100% means readers spot the imitation every time.
``docs/specs/04-live-loop-and-evaluation.md`` sets the release gate at
:data:`RELEASE_GATE`.

Two design decisions here are the ones that make the result mean anything.

**The packet and the answer key are separate objects.** A :class:`Packet` holds
the passages with no record of which side is real, and the :class:`AnswerKey`
holds that separately. The organiser distributes the packet and keeps the key.
Blindness is therefore structural: a reader cannot find the answers by opening
the file they were given, which is not true of any single-file format. The
shuffle seed lives in the key for the same reason -- in the packet it would let a
reader regenerate the assignment.

**Every result carries a confidence interval.** 10 pairs and 3 readers is 30
judgements, and a pick rate of 70% from 30 judgements has a 95% interval of
roughly 52% to 84%. Reporting 70% against a 70% gate without that interval would
be the most misleading thing this module could do, so :func:`tally` refuses to
return a verdict without one.
"""

import json
import math
import random
from dataclasses import dataclass, field

# The aggregate pick rate at or below which the spec considers the voice
# convincing enough to release. From spec 04.
RELEASE_GATE = 0.70

# A fair coin. A pick rate whose interval includes this cannot be distinguished
# from readers guessing.
CHANCE = 0.50

# The protocol's minimum. Fewer than this and the result is one or two people's
# taste rather than a measurement.
MIN_READERS = 3

# Pairs per author the protocol asks for. Not enforced -- a smaller run is still
# worth recording -- but reported against.
TARGET_PAIRS_PER_AUTHOR = 10

# 95% two-sided normal quantile, for the Wilson interval.
Z_95 = 1.959964

SIDES = ("left", "right")


class BlindTestError(ValueError):
    """A packet, key or ballot that cannot be used as given."""


@dataclass(frozen=True)
class BlindPair:
    """One side-by-side comparison, with no record of which side is real.

    This is what a reader sees. It deliberately has no ``real_side`` field:
    that lives in :class:`AnswerKey`, so a reader holding the packet holds no
    answers.

    Attributes:
        pair_id: Stable identifier, used to match a pick back to the key.
        author: Whose voice is being imitated. Shown to the reader, because the
            protocol asks readers who know the author.
        variant: Which prompt produced the generated side, such as ``"v2"`` or
            ``"v1"``. **Not** shown to the reader; it is there so the tally can
            compare prompt versions.
        left: The passage shown on the left.
        right: The passage shown on the right.
    """

    pair_id: str
    author: str
    variant: str
    left: str
    right: str

    def side(self, name):
        """Return the passage on the named side.

        Args:
            name (str): ``"left"`` or ``"right"``.

        Returns:
            str: That side's passage.

        Raises:
            BlindTestError: If the side is not one of :data:`SIDES`.
        """
        if name not in SIDES:
            raise BlindTestError(f"{name!r} is not a side; expected one of {SIDES}")
        return self.left if name == "left" else self.right


@dataclass(frozen=True)
class Packet:
    """The passages to be judged, in a form safe to hand to a reader.

    Attributes:
        pairs (list[BlindPair]): The comparisons, in presentation order.
        packet_id (str): Identifier the ballots and the key refer back to, so a
            ballot cannot be tallied against the wrong packet.
        note (str): Free text for the reader, such as what they are being asked.
    """

    pairs: list
    packet_id: str
    note: str = ""

    @property
    def authors(self):
        """Return the authors represented, in first-appearance order.

        Returns:
            list[str]: Author names.
        """
        seen = []
        for pair in self.pairs:
            if pair.author not in seen:
                seen.append(pair.author)
        return seen

    def to_dict(self):
        """Return a JSON-safe dictionary. Carries no answers.

        Returns:
            dict: The packet, ready for :func:`json.dumps`.
        """
        return {
            "kind": "copyme.blind.packet",
            "packet_id": self.packet_id,
            "note": self.note,
            "pairs": [
                {
                    "pair_id": pair.pair_id,
                    "author": pair.author,
                    "variant": pair.variant,
                    "left": pair.left,
                    "right": pair.right,
                }
                for pair in self.pairs
            ],
        }

    @classmethod
    def from_dict(cls, payload):
        """Rebuild a packet from :meth:`to_dict` output.

        Args:
            payload (dict): A parsed packet file.

        Returns:
            Packet: The packet.

        Raises:
            BlindTestError: If the payload is not a packet or has no pairs.
        """
        if payload.get("kind") != "copyme.blind.packet":
            raise BlindTestError(
                "This file is not a blind-test packet. Expected a file whose "
                "'kind' is 'copyme.blind.packet'."
            )
        pairs = [
            BlindPair(
                pair_id=row["pair_id"],
                author=row["author"],
                variant=row.get("variant", "unknown"),
                left=row["left"],
                right=row["right"],
            )
            for row in payload.get("pairs", [])
        ]
        if not pairs:
            raise BlindTestError("This packet contains no pairs.")
        return cls(
            pairs=pairs,
            packet_id=payload.get("packet_id", ""),
            note=payload.get("note", ""),
        )


@dataclass(frozen=True)
class AnswerKey:
    """Which side of each pair is the real author. The organiser keeps this.

    Attributes:
        real_sides (dict): ``pair_id`` to ``"left"`` or ``"right"``.
        packet_id (str): The packet this key unlocks.
        seed (int): The shuffle seed. Kept here rather than in the packet so a
            reader cannot regenerate the assignment.
    """

    real_sides: dict
    packet_id: str
    seed: int = 0

    def to_dict(self):
        """Return a JSON-safe dictionary.

        Returns:
            dict: The key, ready for :func:`json.dumps`.
        """
        return {
            "kind": "copyme.blind.key",
            "packet_id": self.packet_id,
            "seed": self.seed,
            "real_sides": dict(self.real_sides),
        }

    @classmethod
    def from_dict(cls, payload):
        """Rebuild a key from :meth:`to_dict` output.

        Args:
            payload (dict): A parsed key file.

        Returns:
            AnswerKey: The key.

        Raises:
            BlindTestError: If the payload is not an answer key.
        """
        if payload.get("kind") != "copyme.blind.key":
            raise BlindTestError(
                "This file is not a blind-test answer key. If you uploaded the "
                "packet by mistake, the key is the other file."
            )
        return cls(
            real_sides=dict(payload.get("real_sides", {})),
            packet_id=payload.get("packet_id", ""),
            seed=int(payload.get("seed", 0)),
        )


@dataclass(frozen=True)
class Ballot:
    """One reader's picks.

    Attributes:
        reader (str): Who judged. A label, not an identity: initials are fine.
        picks (dict): ``pair_id`` to the side the reader believed was real.
            A pair the reader skipped is simply absent, and is not counted
            against them.
        packet_id (str): The packet judged.
    """

    reader: str
    picks: dict
    packet_id: str = ""

    def to_dict(self):
        """Return a JSON-safe dictionary.

        Returns:
            dict: The ballot, ready for :func:`json.dumps`.
        """
        return {
            "kind": "copyme.blind.ballot",
            "packet_id": self.packet_id,
            "reader": self.reader,
            "picks": dict(self.picks),
        }

    @classmethod
    def from_dict(cls, payload):
        """Rebuild a ballot from :meth:`to_dict` output.

        Args:
            payload (dict): A parsed ballot file.

        Returns:
            Ballot: The ballot.

        Raises:
            BlindTestError: If the payload is not a ballot.
        """
        if payload.get("kind") != "copyme.blind.ballot":
            raise BlindTestError("This file is not a blind-test ballot.")
        return cls(
            reader=payload.get("reader", ""),
            picks=dict(payload.get("picks", {})),
            packet_id=payload.get("packet_id", ""),
        )


@dataclass(frozen=True)
class Tally:
    """A pick rate with everything needed to judge whether to believe it.

    Attributes:
        judgements (int): Picks counted. Skipped pairs are excluded.
        correct (int): Picks that found the real author.
        pick_rate (float): ``correct / judgements``. Lower is better.
        interval (tuple): 95% Wilson interval for the pick rate.
        readers (int): Distinct readers who submitted a pick.
        by_author (dict): Author to ``(pick_rate, judgements)``.
        by_variant (dict): Prompt variant to ``(pick_rate, judgements)``.
        enough_readers (bool): Whether at least :data:`MIN_READERS` took part.
        indistinguishable (bool): Whether the interval reaches down to chance,
            meaning readers cannot be shown to have done better than guessing.
        verdict (str): One sentence stating the result and its reliability.
    """

    judgements: int
    correct: int
    pick_rate: float
    interval: tuple
    readers: int
    by_author: dict = field(default_factory=dict)
    by_variant: dict = field(default_factory=dict)
    enough_readers: bool = False
    indistinguishable: bool = False
    verdict: str = ""

    @property
    def meets_gate(self):
        """Whether the interval sits wholly at or below the release gate.

        This is deliberately strict. A point estimate below the gate with an
        interval reaching above it has not met the gate; it has failed to
        measure precisely enough to say.

        Returns:
            bool: True only if the upper bound is at or below
                :data:`RELEASE_GATE`.
        """
        return self.judgements > 0 and self.interval[1] <= RELEASE_GATE


def wilson_interval(correct, total, z=Z_95):
    """Return a Wilson score interval for a proportion.

    Used rather than the textbook normal approximation because the normal one
    misbehaves exactly where a blind test lives: small samples and proportions
    near 0 or 1, where it can produce bounds below 0 or above 1.

    Args:
        correct (int): Successes.
        total (int): Trials.
        z (float): Normal quantile. Defaults to 95% two-sided.

    Returns:
        tuple[float, float]: Lower and upper bounds, clamped to [0, 1]. Returns
            ``(0.0, 1.0)`` for no trials, because no trials means no knowledge.
    """
    if total <= 0:
        return (0.0, 1.0)

    proportion = correct / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    spread = (
        z
        / denominator
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
    )
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def build_packet(items, packet_id, seed=None, note="", shuffle_order=True):
    """Assemble a packet and its answer key from real/generated passage pairs.

    Each item contributes one comparison. Which side the real passage lands on
    is decided by a seeded coin flip, so the assignment is reproducible from the
    key but not guessable from the packet.

    Args:
        items (list[dict]): One per comparison, each with ``author``,
            ``real`` and ``generated`` text, and optionally ``variant`` and
            ``pair_id``.
        packet_id (str): Identifier for this packet.
        seed (int | None): Shuffle seed. A random one is chosen when omitted,
            and recorded in the key.
        note (str): Instructions for the reader.
        shuffle_order (bool): Whether to shuffle the order the pairs are
            presented in, so an author's pairs are not all consecutive.

    Returns:
        tuple[Packet, AnswerKey]: The packet to distribute and the key to keep.

    Raises:
        BlindTestError: If no item has both a real and a generated passage.
    """
    if seed is None:
        seed = random.randrange(2**31)
    rng = random.Random(seed)

    pairs = []
    real_sides = {}
    for index, item in enumerate(items, start=1):
        real = (item.get("real") or "").strip()
        generated = (item.get("generated") or "").strip()
        if not real or not generated:
            continue

        # The author and variant are part of the default id because packets get
        # merged -- one per author, combined for a reader who knows several --
        # and bare positional ids collide the moment two packets meet. A
        # collision loses judgements rather than erroring, so it is worth
        # avoiding by construction as well as checking for in `tally`.
        slug = _slug(item.get("author", "unknown"))
        pair_id = item.get("pair_id") or f"{slug}-{item.get('variant', 'v2')}-{index:03d}"
        real_side = rng.choice(SIDES)
        real_sides[pair_id] = real_side
        pairs.append(
            BlindPair(
                pair_id=pair_id,
                author=item.get("author", "unknown"),
                variant=item.get("variant", "v2"),
                left=real if real_side == "left" else generated,
                right=generated if real_side == "left" else real,
            )
        )

    if not pairs:
        raise BlindTestError(
            "No usable pairs: every comparison needs both a real passage and a "
            "generated one."
        )

    _reject_duplicate_ids(pairs)

    if shuffle_order:
        rng.shuffle(pairs)

    return (
        Packet(pairs=pairs, packet_id=packet_id, note=note),
        AnswerKey(real_sides=real_sides, packet_id=packet_id, seed=seed),
    )


def tally(packet, key, ballots):
    """Score a set of ballots against the key, with a confidence interval.

    Args:
        packet (Packet): The packet that was judged.
        key (AnswerKey): Its answer key.
        ballots (list[Ballot]): One per reader.

    Returns:
        Tally: The pick rate, its interval, the breakdowns and a verdict.

    Raises:
        BlindTestError: If the key is for a different packet. This is a real
            mistake rather than a technicality: tallying against the wrong key
            would produce a number near chance and look like a finding.
    """
    if packet.packet_id and key.packet_id and packet.packet_id != key.packet_id:
        raise BlindTestError(
            f"This key is for packet {key.packet_id!r}, but the packet is "
            f"{packet.packet_id!r}. Tallying them together would produce a "
            f"meaningless number."
        )

    _reject_duplicate_ids(packet.pairs)

    pairs = {pair.pair_id: pair for pair in packet.pairs}
    correct = 0
    judgements = 0
    readers = set()
    author_counts = {}
    variant_counts = {}

    for ballot in ballots:
        for pair_id, pick in ballot.picks.items():
            pair = pairs.get(pair_id)
            if pair is None or pick not in SIDES:
                # A pick for a pair this packet does not contain, or a value
                # that is not a side. Ignored rather than raised: a part-filled
                # or hand-edited ballot should still contribute its good rows.
                continue

            judgements += 1
            readers.add(ballot.reader)
            hit = 1 if key.real_sides.get(pair_id) == pick else 0
            correct += hit

            for bucket, name in ((author_counts, pair.author), (variant_counts, pair.variant)):
                total, right = bucket.get(name, (0, 0))
                bucket[name] = (total + 1, right + hit)

    pick_rate = correct / judgements if judgements else 0.0
    interval = wilson_interval(correct, judgements)
    enough_readers = len(readers) >= MIN_READERS
    indistinguishable = judgements > 0 and interval[0] <= CHANCE

    return Tally(
        judgements=judgements,
        correct=correct,
        pick_rate=pick_rate,
        interval=interval,
        readers=len(readers),
        by_author={
            name: (right / total, total) for name, (total, right) in sorted(author_counts.items())
        },
        by_variant={
            name: (right / total, total) for name, (total, right) in sorted(variant_counts.items())
        },
        enough_readers=enough_readers,
        indistinguishable=indistinguishable,
        verdict=_verdict(
            judgements, pick_rate, interval, len(readers), enough_readers, indistinguishable
        ),
    )


def _slug(text):
    """Reduce a name to lowercase letters, digits and hyphens for use in an id.

    Args:
        text (str): Any name.

    Returns:
        str: The slug, or ``"unknown"`` if nothing usable remains.
    """
    kept = "".join(char.lower() if char.isalnum() else "-" for char in text)
    return "-".join(part for part in kept.split("-") if part) or "unknown"


def _reject_duplicate_ids(pairs):
    """Refuse a packet whose pair ids are not unique.

    Picks are matched to pairs by id, so two pairs sharing one id means every
    judgement on the first is silently credited to the second. The tally still
    produces a plausible-looking number, which is why this is an error rather
    than a warning.

    Args:
        pairs (list[BlindPair]): The packet's pairs.

    Raises:
        BlindTestError: If any id appears more than once, naming the ids.
    """
    seen = set()
    duplicates = set()
    for pair in pairs:
        if pair.pair_id in seen:
            duplicates.add(pair.pair_id)
        seen.add(pair.pair_id)

    if duplicates:
        duplicates = sorted(duplicates)
        raise BlindTestError(
            f"This packet has repeated pair ids ({', '.join(duplicates)}). "
            f"Picks are matched to pairs by id, so judgements would be "
            f"credited to the wrong comparison. Give each pair its own id -- "
            f"if you merged packets, rebuild them with distinct ids."
        )


def _verdict(judgements, pick_rate, interval, readers, enough_readers, indistinguishable):
    """Compose one sentence that states the result and how far to trust it.

    The ordering matters. Sample size is checked before the gate, because a
    gate verdict from eight judgements is noise wearing a conclusion's clothes,
    and a reader of the report should be told that first.

    Args:
        judgements (int): Picks counted.
        pick_rate (float): Share correct.
        interval (tuple): The Wilson interval.
        readers (int): Distinct readers.
        enough_readers (bool): Whether the protocol's minimum was met.
        indistinguishable (bool): Whether the interval reaches chance.

    Returns:
        str: The verdict sentence.
    """
    if judgements == 0:
        return "No picks were recorded, so there is nothing to report."

    low, high = interval
    figures = (
        f"Readers identified the real author in {pick_rate:.0%} of "
        f"{judgements} judgements (95% interval {low:.0%} to {high:.0%})"
    )

    if not enough_readers:
        return (
            f"{figures}, from {readers} reader(s). The protocol asks for at "
            f"least {MIN_READERS}, so this is indicative only, not a result."
        )

    if high <= RELEASE_GATE:
        return (
            f"{figures}. That sits wholly at or below the {RELEASE_GATE:.0%} "
            f"gate, so the gate is met."
        )

    if pick_rate <= RELEASE_GATE:
        return (
            f"{figures}. The estimate is at or below the {RELEASE_GATE:.0%} "
            f"gate but the interval reaches {high:.0%}, so there are too few "
            f"judgements to call it either way."
        )

    if indistinguishable:
        return (
            f"{figures}. That is above the {RELEASE_GATE:.0%} gate, but the "
            f"interval still reaches down to chance, so the sample is too "
            f"small to conclude anything."
        )

    return (
        f"{figures}. That is above the {RELEASE_GATE:.0%} gate: readers can "
        f"tell the imitation from the real thing."
    )


def packet_from_json(text):
    """Parse a packet from JSON text, with a readable error for bad input.

    Args:
        text (str | bytes): The file contents.

    Returns:
        Packet: The packet.

    Raises:
        BlindTestError: If the text is not JSON, or not a packet.
    """
    return Packet.from_dict(_parse(text, "packet"))


def key_from_json(text):
    """Parse an answer key from JSON text.

    Args:
        text (str | bytes): The file contents.

    Returns:
        AnswerKey: The key.

    Raises:
        BlindTestError: If the text is not JSON, or not a key.
    """
    return AnswerKey.from_dict(_parse(text, "answer key"))


def ballot_from_json(text):
    """Parse a ballot from JSON text.

    Args:
        text (str | bytes): The file contents.

    Returns:
        Ballot: The ballot.

    Raises:
        BlindTestError: If the text is not JSON, or not a ballot.
    """
    return Ballot.from_dict(_parse(text, "ballot"))


def _parse(text, what):
    """Parse JSON, naming what was expected when it fails.

    Args:
        text (str | bytes): The file contents.
        what (str): What the caller was looking for, for the error message.

    Returns:
        dict: The parsed object.

    Raises:
        BlindTestError: If the text is not JSON, or not a JSON object.
    """
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BlindTestError(f"This is not a valid JSON {what}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BlindTestError(f"A blind-test {what} must be a JSON object.")
    return payload
