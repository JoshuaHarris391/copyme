"""The blind pairwise test: generate a run, judge it card by card, score it.

This page is separate from the profiler because its job is different. The
profiler measures; this settles whether the measuring was worth anything. A
reader rating comparisons should not have to paste a writing sample and wait for
spaCy, and must never see anything that reveals which passage is real.

Two modes, mapping onto the two things anyone actually does:

- **Run a blind test** -- paste the profile, let the app generate a passage per
  round, and judge them one at a time. Nothing is revealed until the run ends.
- **Tally the results** -- combine a packet, its key and the ballots from
  several readers into one number with a confidence interval.

Blindness here is structural rather than a matter of discipline. The whole run is
generated up front, so the answer key is complete and seeded before the first
comparison is shown; the key sits in session state and nothing on the judging
screen reads it. And because the reveal is held back to the end of the run, a
reader cannot learn the imitation's tells on card one and apply them to card
nine -- which would push the pick rate up for reasons that have nothing to do
with the profile.

What gets pasted is the profile **JSON**, not the rendered prompt. The JSON
carries the full passage ranking, so the page can both render the prompt to
generate with and draw real passages from the ones the prompt left out. The
rendered prompt carries only the chosen passages, and comparing against those
would measure the model's ability to echo what it was just shown.
"""

import json

import pandas as pd
import streamlit as st

# Imported as a module, not as a bound name: the tests replace
# `model_call_from_env` to run the whole page with no network and no key, and a
# `from ... import` binding would capture the original before they could.
from copyme import contrastive
from copyme.blind import (
    MIN_READERS,
    RELEASE_GATE,
    Ballot,
    BlindTestError,
    pool,
    run_file,
    run_from_json,
    tally,
)
from copyme.generate import DEFAULT_NOTE, build_live_run, held_out
from copyme.profile import SIZE_PRESETS, Profile

st.set_page_config(page_title="Blind test", page_icon="🎭")

PROFILE_SCHEMA = "copyme/profile/2"

st.title("Blind test")
st.write(
    "copyme's claim is that a model given a profile writes recognisably like "
    "the author. The scorer cannot settle that — it checks whether generated "
    "text hits the measurements copyme itself chose, which is circular. This "
    "page runs the test that can settle it: show a reader a real passage and a "
    "generated one, don't say which is which, and count how often they pick "
    "correctly."
)
st.info(
    f"**A lower score is better.** 50% is a coin flip and the best imitation "
    f"can do. 100% means readers spot the imitation every time. The release "
    f"gate is **{RELEASE_GATE:.0%} or lower**.",
    icon="🎯",
)

mode = st.radio(
    "What are you doing?",
    options=["Run a blind test", "Tally the results"],
    horizontal=True,
    # Every widget on this page carries an explicit key. Without one, Streamlit
    # derives an id from the widget's position, and this page swaps its whole
    # body between three screens -- so a positional id can be reused by a
    # different widget on the next pass, and state follows the position rather
    # than the question.
    key="blind_mode",
    help=(
        "Run a test to produce one reader's ballot. Tally combines the ballots "
        "of several readers into a result."
    ),
)


def download_json(label, payload, filename, **kwargs):
    """Offer a dictionary as a pretty-printed JSON download.

    Args:
        label (str): Button text.
        payload (dict): What to serialise.
        filename (str): Suggested filename.
        **kwargs: Passed through to ``st.download_button``.
    """
    st.download_button(
        label,
        data=json.dumps(payload, indent=2, ensure_ascii=False),
        file_name=filename,
        mime="application/json",
        **kwargs,
    )


def load_profile(text):
    """Parse pasted profile JSON, or return why it could not be read.

    Args:
        text (str): The pasted blob.

    Returns:
        tuple: ``(Profile, None)`` on success, ``(None, str)`` on failure. The
            message names what was expected, in the style of the blind-test
            file loaders, because the likeliest mistake is pasting the rendered
            prompt instead of the JSON.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, (
            f"That is not valid JSON ({exc}). Use the **json** export from the "
            f"profiler — the block labelled for the blind test — rather than "
            f"the prompt itself."
        )

    if not isinstance(payload, dict):
        return None, "A profile must be a JSON object."

    if payload.get("schema") != PROFILE_SCHEMA:
        return None, (
            f"This JSON is not a copyme profile. Expected one whose 'schema' is "
            f"'{PROFILE_SCHEMA}'. If you pasted a packet or an answer key, those "
            f"belong in the tally mode."
        )

    try:
        return Profile.from_dict(payload), None
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"This profile could not be read: {exc}"


def render_result(result):
    """Render a tally's metrics, verdict and breakdowns.

    Shared by the end of a live run and by tally mode, so a self-serve number
    and a mailed-out one are reported in exactly the same terms.

    Args:
        result (copyme.blind.Tally): The scored result.
    """
    if result.meets_gate:
        st.success(result.verdict, icon="✅")
    elif not result.enough_readers:
        st.warning(result.verdict, icon="⚠️")
    else:
        st.error(result.verdict, icon="📊")

    rate_column, interval_column, readers_column = st.columns(3)
    with rate_column:
        st.metric("Pick rate", f"{result.pick_rate:.0%}", help="Lower is better.")
    with interval_column:
        st.metric(
            "95% interval",
            f"{result.interval[0]:.0%}–{result.interval[1]:.0%}",
        )
    with readers_column:
        st.metric(
            "Readers",
            result.readers,
            delta=None if result.enough_readers else f"{MIN_READERS} wanted",
            delta_color="off",
        )

    st.caption(
        f"{result.correct} of {result.judgements} judgements identified "
        f"the real author. The interval is a Wilson 95% interval: with "
        f"samples this size it is wide, and reading the point estimate "
        f"alone is how a blind test gets over-interpreted."
    )

    if result.indistinguishable:
        st.info(
            "The interval reaches down to 50%, so readers cannot be "
            "shown to have done better than guessing.",
            icon="🪙",
        )

    if result.by_author:
        st.subheader("By author")
        st.caption(
            "Imitation can work for one voice and fail for another, "
            "which an aggregate hides."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "author": name,
                        "pick rate": f"{rate:.0%}",
                        "judgements": count,
                    }
                    for name, (rate, count) in result.by_author.items()
                ]
            ),
            hide_index=True,
        )

    if len(result.by_variant) > 1:
        st.subheader("By prompt variant")
        st.caption(
            "This is the comparison the protocol actually asks for: a "
            "bare pick rate cannot say whether v2 improved anything."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "variant": name,
                        "pick rate": f"{rate:.0%}",
                        "judgements": count,
                    }
                    for name, (rate, count) in result.by_variant.items()
                ]
            ),
            hide_index=True,
        )


def generate_run():
    """Write a whole run from the pasted profile, and seal its answer key.

    Reads its parameters back out of the keyed widgets rather than taking
    arguments, because it is called from the top of the script -- before the
    setup screen is drawn -- so that a successful run lands the user on card one
    in the same pass they pressed the button.

    Returns:
        dict | None: The run state, or ``None`` with an error already rendered.
            Returning ``None`` leaves the setup screen to draw below the error,
            with everything the user typed still in place.
    """
    profile, problem = load_profile(st.session_state.get("blind_profile_json", ""))
    if problem or profile is None:
        st.error(problem or "Paste a profile first.")
        return None

    size = st.session_state.get("blind_size", profile.size)
    author = (st.session_state.get("blind_author") or "").strip()
    reader = (st.session_state.get("blind_reader") or "").strip()
    variant = (st.session_state.get("blind_variant") or "v2").strip() or "v2"
    model = (st.session_state.get("blind_model") or "claude-sonnet-5").strip()
    rounds = int(st.session_state.get("blind_rounds", 10))

    seed_text = (st.session_state.get("blind_seed") or "").strip()
    try:
        seed = int(seed_text) if seed_text else None
    except ValueError:
        seed = None
        st.warning("The seed must be a whole number. A random one was used.")

    try:
        model_call = contrastive.model_call_from_env(model=model)
    except contrastive.LiveTierUnavailableError as exc:
        st.error(str(exc))
        return None

    with st.status("Writing the passages...", expanded=True) as status:
        progress = st.progress(0.0, text="Starting...")

        def on_progress(done, total, label):
            progress.progress(done / total if total else 1.0, text=label)

        try:
            packet, key, record = build_live_run(
                profile.at_size(size),
                model_call,
                rounds=rounds,
                author=author,
                packet_id=f"{author.lower().replace(' ', '-') or 'run'}-{variant}",
                variant=variant,
                size=size,
                seed=seed,
                model=model,
                note=DEFAULT_NOTE,
                on_progress=on_progress,
            )
        except BlindTestError as exc:
            status.update(label="Could not build the run", state="error")
            st.error(str(exc))
            return None
        except Exception as exc:  # noqa: BLE001
            # An API failure part-way through. Reported rather than swallowed: a
            # user who has just paid for six calls needs to know which step
            # broke, and that nothing was kept.
            status.update(label="The model call failed", state="error")
            st.error(
                f"Generation stopped: {exc}. Nothing was saved; try again, or "
                f"with fewer rounds."
            )
            return None

        status.update(
            label=f"Wrote {len(packet.pairs)} comparisons",
            state="complete",
            expanded=False,
        )

    st.session_state["blind_run"] = {
        "packet": packet,
        "key": key,
        "record": record,
        "reader": reader,
        "picks": {},
        "position": 0,
        "finished": False,
    }
    return st.session_state["blind_run"]


def request_run():
    """Mark that the user pressed Generate, for the body to act on.

    Every state change on this page goes through a callback like this one rather
    than through ``st.rerun()``. A callback runs *before* the script body on the
    next pass, so the body sees the new state and draws the right screen first
    time. ``st.rerun()`` would instead abandon a pass that had already drawn the
    old screen, which leaves the rendered page and the widget state briefly
    disagreeing -- and makes the page untestable, because a test driving it
    cannot tell which of the two passes it is looking at.
    """
    st.session_state["blind_pending"] = True


def move(delta):
    """Return a callback that steps the judging position by ``delta``.

    Args:
        delta (int): ``+1`` for the next card, ``-1`` for the previous one.

    Returns:
        callable: The callback.
    """

    def step():
        run = st.session_state.get("blind_run")
        if run:
            run["position"] = max(0, run["position"] + delta)

    return step


def finish_run():
    """Mark the run finished, which is the only thing that unseals the answers."""
    run = st.session_state.get("blind_run")
    if run:
        run["finished"] = True


def clear_run():
    """Drop the run and every pick widget it created.

    The pick radios are keyed by pair id, so without this their values would
    survive into the next run and a pair id that happened to repeat would start
    out already answered.
    """
    run = st.session_state.pop("blind_run", None)
    if run:
        for pair in run["packet"].pairs:
            st.session_state.pop(f"blind_pick_{pair.pair_id}", None)


# --- Run a blind test -------------------------------------------------------

if mode == "Run a blind test":
    # Popped, not read: the request is consumed by the pass that acts on it, so
    # a later rerun cannot generate a second run from the same press.
    pending = st.session_state.pop("blind_pending", False)
    run = st.session_state.get("blind_run")

    if run is None and pending:
        run = generate_run()

    # --- Set up -------------------------------------------------------------

    if run is None:
        st.subheader("1. Paste the profile — don't read it")
        st.caption(
            "In the profiler, open **For the blind test** and copy the block "
            "without reading it. It names which passages are the author's own, "
            "so reading it is how you spoil your own test. Nothing from it is "
            "shown on this page."
        )
        pasted = st.text_area(
            "The profile JSON",
            height=140,
            key="blind_profile_json",
            placeholder="Paste here. It will look like a wall of JSON — that is right.",
        )

        profile = None
        if pasted.strip():
            profile, problem = load_profile(pasted)
            if problem:
                st.error(problem)

        if profile is None:
            st.caption(
                "Waiting for a profile. Everything below appears once one is "
                "pasted."
            )
        else:
            st.subheader("2. Set up the run")
            st.caption(
                f"Profiled from **{profile.word_count:,} words**, built at "
                f"**{profile.size}**. No passage or rule from it is displayed "
                f"here."
            )

            size_column, rounds_column = st.columns(2)
            with size_column:
                size = st.selectbox(
                    "Prompt size to test",
                    options=list(SIZE_PRESETS),
                    index=list(SIZE_PRESETS).index(
                        profile.size if profile.size in SIZE_PRESETS else "standard"
                    ),
                    key="blind_size",
                    help=(
                        "Which size of prompt the model writes from. The "
                        "release gate is set on Standard. A smaller size "
                        "carries fewer of the author's passages and so leaves "
                        "more of them free to compare against."
                    ),
                )

            available = len(held_out(profile.at_size(size)))

            with rounds_column:
                # No max_value: it would have to track the size selector, and a
                # stored value above a freshly lowered ceiling makes Streamlit
                # raise. Asking for more than the sample affords is capped
                # during generation instead, and reported in the run record.
                rounds = st.number_input(
                    "Rounds",
                    min_value=1,
                    value=min(10, max(1, available)),
                    step=1,
                    key="blind_rounds",
                    help=(
                        "One comparison per round, each from a different "
                        "passage. The protocol asks for about 10 per author."
                    ),
                )

            if available and rounds > available:
                st.caption(
                    f"You asked for {rounds} rounds and this profile affords "
                    f"**{available}** at {size}. The run will be {available} "
                    f"rounds long."
                )

            if available == 0:
                st.error(
                    f"At **{size}** this profile carries every passage the "
                    f"sample had, so there is nothing left to compare against "
                    f"that the model has not already been shown. Test a "
                    f"smaller size, or profile a longer sample."
                )
            elif available < 10:
                st.caption(
                    f"This profile affords **{available}** round(s) at {size}: "
                    f"the protocol asks for about 10 per author, so the "
                    f"interval will be wide. A smaller size or a longer sample "
                    f"gives more."
                )

            reader_column, author_column = st.columns(2)
            with reader_column:
                reader = st.text_input(
                    "Your name or initials",
                    key="blind_reader",
                    help="A label so ballots can be told apart. Not an identity.",
                )
            with author_column:
                author = st.text_input(
                    "Author",
                    key="blind_author",
                    help=(
                        "Shown to you on every card. The protocol asks for "
                        "readers who know the author."
                    ),
                )

            with st.expander("Model, prompt variant and seed"):
                model_column, variant_column = st.columns([3, 1])
                with model_column:
                    model = st.text_input(
                        "Model", value="claude-sonnet-5", key="blind_model"
                    )
                with variant_column:
                    variant = st.text_input(
                        "Variant",
                        value="v2",
                        key="blind_variant",
                        help=(
                            "Which prompt produced the generated side. Never "
                            "shown on a card; it lets the tally compare v2 "
                            "against v1."
                        ),
                    )
                seed_text = st.text_input(
                    "Shuffle seed (optional)",
                    key="blind_seed",
                    help="Leave blank for a random one. It is recorded in the key.",
                )
                st.caption(
                    f"The key comes from **{contrastive.API_KEY_VARIABLE}** in "
                    f"the environment this app was started in. It is never "
                    f"written into a profile, a packet, a result or a log."
                )

                recorded_model = profile.provenance.get("contrastive_model")
                if recorded_model and recorded_model != model:
                    st.warning(
                        f"This profile's corrections were measured against "
                        f"**{recorded_model}**, and you are generating with "
                        f"**{model}**. Corrections built against one model "
                        f"transfer poorly to another, so the result is about "
                        f"this pairing rather than about the profile."
                    )

            # Validation only: the seed is parsed again at generation time, out
            # of session state. Flagged here so a typo is caught before the user
            # pays for a run whose seed they will not be able to reproduce.
            if seed_text.strip() and not seed_text.strip().lstrip("-").isdigit():
                st.warning("The seed must be a whole number. A random one will be used.")

            st.subheader("3. Generate the comparisons")
            st.caption(
                "The whole run is written before you judge any of it. That is "
                "what keeps it blind: the answers exist, sealed, before you see "
                "card one."
            )

            blocked = available == 0 or not author.strip() or not reader.strip()
            if blocked and available:
                st.caption("Fill in your name and the author's name to start.")

            st.button(
                "Generate and start",
                type="primary",
                disabled=blocked,
                key="blind_go",
                on_click=request_run,
            )

    # --- Judge --------------------------------------------------------------

    elif not run["finished"]:
        packet = run["packet"]
        total = len(packet.pairs)
        position = min(run["position"], total - 1)
        pair = packet.pairs[position]

        st.subheader(f"{position + 1} of {total}")
        st.progress((position + 1) / total, text=f"Card {position + 1} of {total}")
        st.markdown(f"Which of these is really by **{pair.author}**?")
        st.caption(
            "You will not be told whether you were right until the run ends. "
            "Knowing after each card would teach you the imitation's tells and "
            "push the score up for reasons that have nothing to do with the "
            "profile."
        )

        left_column, right_column = st.columns(2)
        with left_column:
            st.caption("Left")
            # Rendered as plain text, never Markdown: a stray asterisk or a
            # heading surviving in one passage and not the other would sort them
            # for the reader without either being read.
            st.text(pair.left)
        with right_column:
            st.caption("Right")
            st.text(pair.right)

        pick_key = f"blind_pick_{pair.pair_id}"
        if pick_key not in st.session_state:
            st.session_state[pick_key] = "Skip"

        choice = st.radio(
            "Your pick",
            options=["Left", "Right", "Skip"],
            horizontal=True,
            key=pick_key,
            help="Skip anything you genuinely cannot judge; it is not counted against you.",
        )
        if choice == "Skip":
            run["picks"].pop(pair.pair_id, None)
        else:
            run["picks"][pair.pair_id] = choice.lower()

        st.divider()
        back_column, next_column, abandon_column = st.columns(3)
        with back_column:
            st.button(
                "← Back",
                disabled=position == 0,
                key="blind_back",
                on_click=move(-1),
            )
        with next_column:
            if position + 1 < total:
                st.button(
                    "Next →", type="primary", key="blind_next", on_click=move(1)
                )
            else:
                st.button(
                    "Finish and score",
                    type="primary",
                    key="blind_finish",
                    on_click=finish_run,
                )
        with abandon_column:
            st.button("Abandon this run", key="blind_abandon", on_click=clear_run)

        st.caption(f"{len(run['picks'])} of {total} judged so far.")

    # --- Score --------------------------------------------------------------

    else:
        packet = run["packet"]
        key = run["key"]
        record = run["record"]
        ballot = Ballot(
            reader=run["reader"] or "unnamed",
            picks=dict(run["picks"]),
            packet_id=packet.packet_id,
        )

        st.subheader("The result")
        if not run["picks"]:
            st.warning("Every card was skipped, so there is nothing to score.")
        else:
            result = tally(packet, key, [ballot])
            render_result(result)

            st.caption(
                f"This is one reader, and the protocol asks for at least "
                f"{MIN_READERS}. Reaching that means other readers running "
                f"their own tests, then pooling the result files under **Tally "
                f"the results**."
            )

            st.subheader("What each card was")
            st.caption(
                "Safe to read now. This is where you learn the tells — after "
                "they can no longer bias the run."
            )
            for position, pair in enumerate(packet.pairs, start=1):
                real_side = key.real_sides.get(pair.pair_id)
                pick = run["picks"].get(pair.pair_id)
                if pick is None:
                    verdict = "skipped"
                elif pick == real_side:
                    verdict = "you were right"
                else:
                    verdict = "you were fooled"

                with st.expander(f"{position}. The real one was on the {real_side} — {verdict}"):
                    real_column, generated_column = st.columns(2)
                    with real_column:
                        st.caption(f"By {pair.author}")
                        st.text(pair.side(real_side))
                    with generated_column:
                        st.caption(f"Generated ({record.get('model') or 'unknown model'})")
                        other = "right" if real_side == "left" else "left"
                        st.text(pair.side(other))

            st.subheader("Keep the run")
            st.caption(
                "One file, and it is the whole run: the pick rate, its "
                "interval, what generated the passages, and every comparison "
                "with its real side and your pick. `docs/evals/` takes one per "
                "run, and a failing number is still worth publishing. Bring "
                "several of these back here under **Tally the results** to "
                "pool them across readers."
            )
            download_json(
                "⬇️ Download the result",
                run_file(packet, key, ballot, result, generation=record),
                f"{packet.packet_id}-{ballot.reader.replace(' ', '-')}-result.json",
                type="primary",
            )

            with st.expander("What the generation did"):
                st.json(record)

        st.button("Start another run", key="blind_again", on_click=clear_run)


# --- Tally ------------------------------------------------------------------

else:
    st.subheader("Pool several readers' runs into one number")
    st.caption(
        "One reader is indicative; the protocol wants three or more per author. "
        "Each of them runs their own test and sends you the result file it "
        "offers. Drop them all in here."
    )
    run_files = st.file_uploader(
        "Result files — one per run",
        type="json",
        accept_multiple_files=True,
        key="tally_runs",
    )

    if not run_files:
        st.caption(
            f"Nothing uploaded yet. The protocol asks for at least "
            f"{MIN_READERS} readers; with fewer, the result is reported as "
            f"indicative rather than as a finding."
        )
    else:
        try:
            runs = [run_from_json(handle.getvalue()) for handle in run_files]
            result = pool(runs)
        except BlindTestError as exc:
            st.error(str(exc))
        else:
            render_result(result)

            st.caption(
                f"Pooled from {len(runs)} run(s). Counts are added rather than "
                f"percentages averaged: a reader who judged three comparisons "
                f"and one who judged twelve did not contribute equally, and "
                f"averaging their rates would pretend they had."
            )

            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "reader": run.get("reader") or f"run-{position}",
                            "author": run.get("generation", {}).get("author", ""),
                            "variant": run.get("generation", {}).get("variant", ""),
                            "model": run.get("generation", {}).get("model", ""),
                            "size": run.get("generation", {}).get("size", ""),
                            "judgements": run.get("judgements", 0),
                            "correct": run.get("correct", 0),
                        }
                        for position, run in enumerate(runs, start=1)
                    ]
                ),
                hide_index=True,
            )
            st.caption(
                "Check the model and size columns before believing the "
                "aggregate: pooling runs that used different models, or "
                "different prompt sizes, produces a number about no single "
                "pairing. The release gate is set on Standard."
            )
