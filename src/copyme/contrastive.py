"""Tell the model where it is going to go wrong, before it does.

The one prompting technique with direct published evidence on Claude is to show
an off-voice attempt beside the real thing with a one-line explanation of the
gap. The explanations carried most of the gain, not the examples of failure --
which is the whole reason the static tier works at all.

Two tiers.

**Static**, the default. The gap between the author's feature vector and the
generic baseline already says where a model will drift, because the baseline *is*
what the model does unprompted. Predicting the drift therefore costs no API call,
has no model dependency, and cannot go stale against a model it never saw.

**Live.** Ask the target model to write, score what comes back, and report where
it actually drifted rather than where it was predicted to. More accurate about
one model and, per the research, transferring poorly to any other -- which is why
it is opt-in and why the model it ran against is recorded.

Two constraints hold in both tiers:

- The Compact preset carries **only the correction text, never the failed
  draft**, because smaller models sometimes imitate the bad example instead of
  avoiding it.
- No API key reaches a profile, a cache file, an export footer or a log line.
  The footer records the model name and nothing else.
"""

from .baseline import SUPPRESSION_THRESHOLD
from .features import FEATURE_LABELS, comparative

# At most this many notes, ranked by how far the author sits from the baseline.
# The 2025 reader study found naming specific "AI-ish" habits measurably helped,
# but three is where the token budget stops paying for itself.
MAX_NOTES = 3

# A feature has to be at least this far from the baseline to be worth warning
# about. Higher than the rule-suppression threshold: a note is a bigger
# investment of attention than a rule, so it has a higher bar.
NOTE_THRESHOLD = 1.0


class LiveTierUnavailableError(RuntimeError):
    """Raised when the live tier is asked for and cannot run.

    Carries the reason, so a caller can degrade to the static tier and tell the
    user *why* rather than silently producing something different from what was
    asked for.
    """


def _drift_phrase(name, z):
    """Describe the direction a model will drift in, for one feature.

    The note is written from the model's point of view -- what *it* will do -- not
    the author's, because that is what makes it recognisable as a correction
    rather than a restatement of the rules.
    """
    label = FEATURE_LABELS.get(name, name)
    # The author sits above the baseline, so a model left alone will come in
    # below it, and the other way round.
    return f"{label} will come out {comparative(name, -z)} than it should"


def static_notes(features, baseline, rules, limit=MAX_NOTES, threshold=NOTE_THRESHOLD):
    """Predict where a model will drift, from the author-to-baseline delta.

    Args:
        features (copyme.features.FeatureSet): The author's document features.
        baseline (copyme.baseline.Baseline): The generic-prose baseline.
        rules (list[copyme.rules.Rule]): The rendered rules. A note is only
            emitted for a feature that also has a rule, so every warning has a
            corresponding instruction to follow.
        limit (int): Most notes to emit.
        threshold (float): Minimum distance from the baseline, in standard
            deviations.

    Returns:
        list[str]: Notes, largest delta first. Empty where the author is close
            enough to generic prose that there is nothing to predict, in which
            case the prompt omits the section rather than printing an empty
            heading.
    """
    ruled = {rule.feature for rule in rules}

    ranked = []
    for name, value in features.scalars.items():
        if name not in ruled:
            continue
        z = baseline.z(name, value)
        if abs(z) < max(threshold, SUPPRESSION_THRESHOLD):
            continue
        ranked.append((abs(z), name, z))

    # Largest delta first; the feature name breaks ties so the order is fixed
    # for a fixed profile.
    ranked.sort(key=lambda row: (-row[0], row[1]))

    notes = []
    for _, name, z in ranked[:limit]:
        rule = next(rule for rule in rules if rule.feature == name)
        notes.append(
            f"**Likely drift:** {_drift_phrase(name, z)}. "
            f"The author's level is {rule.magnitude}. "
            f"Correct towards the author, not towards the middle."
        )
    return notes


def _held_out(profile, count=2):
    """Passages the selector ranked but did not choose.

    Using unselected passages is what stops the live tier measuring the model's
    ability to copy an exemplar it was just given.

    Args:
        profile (copyme.profile.Profile): A built profile.
        count (int): How many to hold out.

    Returns:
        list[copyme.exemplars.Exemplar]: Held-out passages, best-ranked first.
    """
    chosen = {exemplar.passage_index for exemplar in profile.exemplars}
    return [
        exemplar for exemplar in profile.ranking
        if exemplar.passage_index not in chosen
    ][:count]


def live_notes(profile, model_call, score_fn, model="claude-sonnet-5", count=2):
    """Find where the target model actually drifts, by asking it to write.

    Runs once at profile time. The result is cached in the profile's JSON, so no
    later render costs an API call.

    Args:
        profile (copyme.profile.Profile): The profile to test, already built
            with its static notes.
        model_call (callable): Called as ``model_call(prompt, max_words)`` and
            expected to return the model's text. Injected rather than
            constructed here so the unit tests can run the whole tier with no
            network and no key.
        score_fn (callable): Called as ``score_fn(text, profile)``, returning a
            :class:`copyme.scorer.ScoreReport`. Injected for the same reason.
        model (str): Recorded on the result. Never a key, only the name.
        count (int): How many held-out passages to test against.

    Returns:
        tuple[list[str], dict]: The notes, and a record of what the tier did --
            the model name, how many drafts were scored, and the mean in-band
            share. The record goes into provenance; the notes go into the prompt.

    Raises:
        LiveTierUnavailableError: If there is nothing to hold out.
    """
    held = _held_out(profile, count)
    if not held:
        raise LiveTierUnavailableError(
            "The sample has no passages left over after selection, so the live "
            "tier has nothing to test against. Use a longer sample or a smaller "
            "exemplar budget."
        )

    from .exports import build_pre_prompt

    prompt = build_pre_prompt(profile, size=profile.size, format="system_prompt")

    notes = []
    in_band = []
    for exemplar in held:
        words = max(60, len(exemplar.text.split()))
        draft = model_call(
            f"{prompt}\n\nWrite about {words} words in this voice. "
            f"Subject: whatever the following passage is about, but do not "
            f"reuse its wording.\n\n{exemplar.text[:400]}",
            words,
        )
        if not draft or not draft.strip():
            continue
        report = score_fn(draft, profile)
        in_band.append(report.in_band)
        worst = [drift for drift in report.drifts if drift.verdict != "in band"]
        if not worst:
            continue
        worst.sort(key=lambda drift: -abs(drift.generated - drift.author))
        summary = "; ".join(drift.note for drift in worst[:3])
        notes.append(
            f"**Measured drift ({model}):** {summary}. "
            f"This is what the model produced from these instructions, not a "
            f"prediction. Correct towards the author."
        )

    record = {
        "model": model,
        "drafts_scored": len(in_band),
        "mean_in_band": round(sum(in_band) / len(in_band), 4) if in_band else None,
    }
    return notes[:MAX_NOTES], record


def anthropic_model_call(model="claude-sonnet-5", api_key=None):
    """Build a ``model_call`` for :func:`live_notes` against the Claude API.

    The key is read from the environment by the SDK and is never stored,
    returned or logged here.

    Args:
        model (str): The model id.
        api_key (str, optional): Passed through to the client. Prefer leaving it
            unset and letting ``ANTHROPIC_API_KEY`` be read from the
            environment.

    Returns:
        callable: A ``model_call(prompt, max_words)``.

    Raises:
        LiveTierUnavailableError: If the SDK is not installed or no key is
            configured. The message names the missing piece so the caller can
            degrade to the static tier with a stated reason.
    """
    import os

    try:
        import anthropic
    except ImportError as error:
        raise LiveTierUnavailableError(
            "The live contrastive tier needs the 'anthropic' package, which is "
            "not installed. Install it, or use --contrastive static."
        ) from error

    if not (api_key or os.environ.get("ANTHROPIC_API_KEY")):
        raise LiveTierUnavailableError(
            "The live contrastive tier needs ANTHROPIC_API_KEY in the "
            "environment. Set it, or use --contrastive static."
        )

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def call(prompt, max_words):
        response = client.messages.create(
            model=model,
            # Roughly four tokens to three words, with headroom.
            max_tokens=min(4096, int(max_words * 2) + 200),
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )

    return call
