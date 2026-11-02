"""Turn a profile into a blind-test packet, by asking the model to write.

This is the step that used to be done by hand. The organiser rendered a prompt,
pasted it into a chat, asked for a passage, copied the reply back, and pasted it
beside a passage they had also copied by hand -- sixty times over for a full run.
``docs/evals/`` held no runs for exactly that reason.

Everything needed was already here and unconnected: :func:`held_out` picks the
author's passages the selector did not use, :mod:`copyme.exports` renders the
prompt, and :func:`copyme.blind.build_packet` does the seeded side assignment and
the packet/key separation. This module joins them up.

Two things keep the result honest.

**The real side is always a held-out passage.** A passage that is in the prompt
is one the model was just shown, and scoring it against its own exemplar
measures copying rather than imitation. :func:`held_out` returns only passages
the selector ranked and did not choose, so the author's side of every comparison
is writing the model has never seen.

**The model call is injected.** Nothing here opens a socket. The whole module --
hold out, render, generate, assemble -- is covered by unit tests with no network
and no API key, which leaves only the HTTP call itself untested. The live
contrastive tier takes the same approach for the same reason.
"""

from .blind import BlindTestError, build_packet
# Private to `blind`, but the id-slugging rule belongs to the packet format
# rather than to this module. Borrowing it is what keeps ids built here and ids
# built by `build_packet`'s own default in the same shape.
from .blind import _slug

# Shortest draft worth asking for. Below about sixty words a passage cannot show
# a sentence rhythm, so a reader would be judging two fragments.
TARGET_WORD_FLOOR = 60

# How much of the held-out passage is shown to the model as the subject. Enough
# to say what the passage is about; short enough that the model is not being
# handed a page of the author's prose to echo.
SUBJECT_CHARS = 400

# What the reader is asked. Carried in the packet so a packet judged later, or by
# someone else, asks the same question.
DEFAULT_NOTE = "Pick the passage you believe is genuinely by the author."


def held_out(profile, count=None):
    """Return the author's passages the selector ranked but did not choose.

    These are the only passages fit to be the real side of a comparison. A
    chosen exemplar is in the prompt, so a model asked to write on its subject is
    being tested on recall, not on voice.

    Args:
        profile (copyme.profile.Profile): A built profile.
        count (int, optional): How many to return, best-ranked first. All of
            them when omitted, which is what makes this the ceiling on how many
            rounds a profile affords.

    Returns:
        list[copyme.exemplars.Exemplar]: Held-out passages, best-ranked first.
            Empty when the selection consumed every candidate passage, which a
            short sample at a large size will do.
    """
    chosen = {exemplar.passage_index for exemplar in profile.exemplars}
    spare = [
        exemplar
        for exemplar in profile.ranking
        if exemplar.passage_index not in chosen
    ]
    return spare if count is None else spare[:count]


def imitation_prompt(pre_prompt, exemplar):
    """Compose the instruction that asks the model to write in the voice.

    Shared with the live contrastive tier rather than written twice, so the two
    provably send the same instruction. If they drifted apart, the tier that
    predicts drift and the test that measures it would be measuring different
    things, and the comparison between them would mean nothing.

    The target length comes from the held-out passage, because a generated
    passage noticeably shorter or longer than the real one is a giveaway that
    has nothing to do with voice.

    Args:
        pre_prompt (str): The rendered profile, usually the ``system_prompt``
            export.
        exemplar (copyme.exemplars.Exemplar): The held-out passage whose subject
            the model is asked to write about.

    Returns:
        tuple[str, int]: The prompt, and the target word count it asks for.
    """
    words = max(TARGET_WORD_FLOOR, len(exemplar.text.split()))
    prompt = (
        f"{pre_prompt}\n\nWrite about {words} words in this voice. "
        f"Subject: whatever the following passage is about, but do not "
        f"reuse its wording.\n\n{exemplar.text[:SUBJECT_CHARS]}"
    )
    return prompt, words


def generate_pairs(
    profile,
    model_call,
    rounds,
    author,
    variant="v2",
    size=None,
    mask_names=None,
    on_progress=None,
):
    """Generate one real/generated pair per held-out passage.

    Args:
        profile (copyme.profile.Profile): The profile under test.
        model_call (callable): Called as ``model_call(prompt, max_words)``,
            returning the model's text. Injected so this runs in a test with no
            network and no key.
        rounds (int): How many pairs to ask for. Silently capped at the number of
            held-out passages available -- asking for more than the sample
            affords is a reasonable thing for a user to do, and the shortfall is
            reported in the returned record rather than raised.
        author (str): Whose voice it is. Shown to the reader.
        variant (str): Which prompt produced the generated side. Never shown to
            the reader; it is what lets :func:`copyme.blind.tally` compare prompt
            versions.
        size (str, optional): Which size to render the prompt at. Defaults to the
            profile's own. A smaller size chooses fewer exemplars and therefore
            holds more passages out, which is how a profile that affords no
            rounds at Standard affords several at Compact.
        mask_names (bool, optional): Whether to mask one-off names in the
            prompt. Defaults to the profile's own setting.
        on_progress (callable, optional): Called as
            ``on_progress(done, total, label)`` before each call and once at the
            end. Generation is the slow part, so the caller needs to be able to
            say so.

    Returns:
        tuple[list[dict], dict]: The items, in the shape
            :func:`copyme.blind.build_packet` consumes, and a record of what the
            run did: ``rounds_requested``, ``rounds_built``,
            ``held_out_available`` and ``skipped``.

    Raises:
        BlindTestError: If the profile holds nothing out, naming the two fixes.
    """
    available = held_out(profile)
    if not available:
        raise BlindTestError(
            "This profile has no passages left over after selection, so there "
            "is nothing to compare against that the model has not already been "
            "shown. Test a smaller size -- Compact chooses fewer passages and "
            "so holds more out -- or profile a longer sample."
        )

    passages = available[: max(1, int(rounds))]
    total = len(passages)

    # Imported here rather than at module scope: exports reaches back to profile,
    # which reaches contrastive, which imports this module. The live contrastive
    # tier defers the same import for the same reason.
    from .exports import build_pre_prompt

    pre_prompt = build_pre_prompt(
        profile, size=size, format="system_prompt", mask_names=mask_names
    )

    items = []
    skipped = 0
    for position, exemplar in enumerate(passages, start=1):
        if on_progress:
            on_progress(position - 1, total, f"Writing passage {position} of {total}")

        prompt, words = imitation_prompt(pre_prompt, exemplar)
        draft = model_call(prompt, words)
        if not draft or not draft.strip():
            # A refusal or an empty response. Dropped rather than raised: losing
            # one round of ten is worth less than losing the run.
            skipped += 1
            continue

        items.append(
            {
                "author": author,
                "variant": variant,
                # The author's text verbatim, never the masked form. Masking is
                # for the prompt, where a one-off name could leak; a placeholder
                # on the real side of a comparison would tell the reader which
                # side it was.
                "real": exemplar.text,
                "generated": draft.strip(),
                # Keyed on the passage, not on position, so two runs over the
                # same profile produce ids that mean the same thing and ids that
                # do not collide when their packets are merged.
                "pair_id": f"{_slug(author)}-{variant}-p{exemplar.passage_index:03d}",
            }
        )

    if on_progress:
        on_progress(total, total, "Done")

    return items, {
        "rounds_requested": int(rounds),
        "rounds_built": len(items),
        "held_out_available": len(available),
        "skipped": skipped,
    }


def build_live_run(
    profile,
    model_call,
    rounds,
    author,
    packet_id,
    variant="v2",
    size=None,
    mask_names=None,
    seed=None,
    model="",
    note=DEFAULT_NOTE,
    on_progress=None,
):
    """Generate a whole run and assemble it into a packet and an answer key.

    The whole run is generated before any of it is judged. That is what makes
    blindness structural rather than a matter of discipline: the key is complete
    and seeded before the reader sees the first comparison, and the side
    assignment is :func:`copyme.blind.build_packet`'s unmodified seeded coin
    flip.

    Args:
        profile (copyme.profile.Profile): The profile under test.
        model_call (callable): As :func:`generate_pairs`.
        rounds (int): How many comparisons to generate.
        author (str): Whose voice it is.
        packet_id (str): Identifier the key and the ballots refer back to.
        variant (str): Which prompt produced the generated side.
        size (str, optional): Which size to render the prompt at.
        mask_names (bool, optional): Whether to mask one-off names.
        seed (int, optional): Shuffle seed. A random one is chosen when omitted
            and recorded in the key.
        model (str): The model's name, for the record. Never a key.
        note (str): What the reader is being asked.
        on_progress (callable, optional): As :func:`generate_pairs`.

    Returns:
        tuple: ``(Packet, AnswerKey, dict)`` -- the comparisons, the answers, and
            a record of the run.

    Raises:
        BlindTestError: If the profile holds nothing out, or if every draft came
            back empty.
    """
    items, record = generate_pairs(
        profile,
        model_call,
        rounds,
        author,
        variant=variant,
        size=size,
        mask_names=mask_names,
        on_progress=on_progress,
    )

    packet, key = build_packet(items, packet_id=packet_id, seed=seed, note=note)

    record.update(
        {
            "model": model,
            "size": (size or profile.size).lower(),
            "profile_hash": profile.hash,
            "variant": variant,
            "author": author,
        }
    )
    return packet, key, record
