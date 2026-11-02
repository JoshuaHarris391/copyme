"""The blind pairwise test: build a packet, rate one, tally the result.

This page is separate from the profiler because its users are different. A
reader rating a packet should not have to paste a writing sample and wait for
spaCy, and should never see anything that reveals which passage is real.

The three modes map onto the three roles in the protocol:

- **Build a packet** -- the organiser pairs each real passage with a generated
  one and gets two files: a packet to send out and an answer key to keep.
- **Rate a packet** -- a reader opens the packet, picks the passage they
  believe is genuine, and sends back a ballot.
- **Tally** -- the organiser combines the key with the ballots.

Blindness is structural, not a matter of discipline: this page cannot reveal
the answers in rating mode because the packet file does not contain them.
"""

import json

import pandas as pd
import streamlit as st

from copyme.blind import (
    MIN_READERS,
    RELEASE_GATE,
    TARGET_PAIRS_PER_AUTHOR,
    Ballot,
    BlindTestError,
    build_packet,
    ballot_from_json,
    key_from_json,
    packet_from_json,
    tally,
)

st.set_page_config(page_title="Blind test", page_icon="🎭")

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
    options=["Build a packet", "Rate a packet", "Tally the results"],
    horizontal=True,
    help=(
        "Build and tally are the organiser's jobs. Readers only need 'Rate a "
        "packet' and the packet file you send them."
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


# --- Build a packet ---------------------------------------------------------

if mode == "Build a packet":
    st.subheader("1. Pair each real passage with a generated one")
    st.caption(
        "For each comparison you need a passage genuinely by the author and "
        "one a model wrote while following the profile. Use passages on topics "
        "the profile never saw, or the model can pass by repeating what it was "
        "given."
    )

    drafts = st.session_state.setdefault("blind_drafts", [])

    with st.form("add_pair", clear_on_submit=True):
        author_column, variant_column = st.columns([3, 1])
        with author_column:
            author = st.text_input(
                "Author",
                help="Shown to the reader. The protocol asks for readers who know them.",
            )
        with variant_column:
            variant = st.text_input(
                "Prompt variant",
                value="v2",
                help=(
                    "Which prompt produced the generated side. Never shown to "
                    "the reader; it lets the tally compare v2 against v1."
                ),
            )
        real = st.text_area("The real passage, by the author", height=160)
        generated = st.text_area("The generated passage", height=160)

        if st.form_submit_button("Add this pair", type="primary"):
            if not real.strip() or not generated.strip():
                st.warning("A comparison needs both passages.")
            elif not author.strip():
                st.warning("Name the author: the reader is told whose voice it is.")
            else:
                drafts.append(
                    {
                        "author": author.strip(),
                        "variant": variant.strip() or "v2",
                        "real": real,
                        "generated": generated,
                    }
                )
                st.rerun()

    with st.expander("Or paste a list of pairs as JSON"):
        st.caption(
            "A JSON array of objects with `author`, `real`, `generated` and "
            "optionally `variant`. Useful once passage generation is scripted."
        )
        bulk = st.text_area("JSON array", height=140, key="blind_bulk")
        if st.button("Add them all"):
            try:
                rows = json.loads(bulk)
                if not isinstance(rows, list):
                    raise ValueError("the top level must be an array")
            except (json.JSONDecodeError, ValueError) as exc:
                st.error(f"Could not read that as a JSON array: {exc}")
            else:
                drafts.extend(row for row in rows if isinstance(row, dict))
                st.rerun()

    if drafts:
        st.subheader("2. Check the run")
        summary = {}
        for row in drafts:
            key = (row.get("author", "unknown"), row.get("variant", "v2"))
            summary[key] = summary.get(key, 0) + 1
        st.dataframe(
            pd.DataFrame(
                [
                    {"author": author, "variant": variant, "pairs": count}
                    for (author, variant), count in sorted(summary.items())
                ]
            ),
            hide_index=True,
        )

        thin = sorted(
            {author for (author, _), count in summary.items() if count < TARGET_PAIRS_PER_AUTHOR}
        )
        if thin:
            st.caption(
                f"The protocol asks for about {TARGET_PAIRS_PER_AUTHOR} pairs "
                f"per author. Fewer is still worth running, but the confidence "
                f"interval will be wide. Short of that for: {', '.join(thin)}."
            )

        st.subheader("3. Build the two files")
        st.caption(
            "The **packet** goes to your readers and contains no answers. The "
            "**key** stays with you. Keep them apart: that separation is what "
            "makes the result mean anything."
        )

        identifier_column, seed_column = st.columns(2)
        with identifier_column:
            packet_id = st.text_input("Packet name", value="run-1")
        with seed_column:
            seed_text = st.text_input(
                "Shuffle seed (optional)",
                help="Leave blank for a random one. It is recorded in the key.",
            )

        try:
            seed = int(seed_text) if seed_text.strip() else None
        except ValueError:
            seed = None
            st.warning("The seed must be a whole number. Using a random one.")

        if st.button("Build packet and key", type="primary"):
            try:
                packet, key = build_packet(
                    drafts,
                    packet_id=packet_id.strip() or "run-1",
                    seed=seed,
                    note="Pick the passage you believe is genuinely by the author.",
                )
            except BlindTestError as exc:
                st.error(str(exc))
            else:
                st.session_state["blind_built"] = (packet, key)

        built = st.session_state.get("blind_built")
        if built:
            packet, key = built
            st.success(
                f"Built **{len(packet.pairs)} pairs** covering "
                f"{', '.join(packet.authors)}."
            )
            packet_column, key_column = st.columns(2)
            with packet_column:
                download_json(
                    "⬇️ Packet — send to readers",
                    packet.to_dict(),
                    f"{packet.packet_id}-packet.json",
                    type="primary",
                )
                st.caption("Contains no answers.")
            with key_column:
                download_json(
                    "⬇️ Answer key — keep this",
                    key.to_dict(),
                    f"{packet.packet_id}-key.json",
                )
                st.caption("Do not send this to a reader.")

        if st.button("Clear all pairs"):
            st.session_state["blind_drafts"] = []
            st.session_state.pop("blind_built", None)
            st.rerun()
    else:
        st.caption("No pairs yet. Add one above.")


# --- Rate a packet ----------------------------------------------------------

elif mode == "Rate a packet":
    st.subheader("Pick the passage you think is genuine")
    uploaded = st.file_uploader("The packet file you were sent", type="json")

    if uploaded is None:
        st.caption(
            "You need the packet file from whoever organised the test. It "
            "contains the passages and nothing else — not even they can see "
            "your picks until you send the ballot back."
        )
    else:
        try:
            packet = packet_from_json(uploaded.getvalue())
        except BlindTestError as exc:
            st.error(str(exc))
        else:
            reader = st.text_input(
                "Your name or initials",
                help="A label so ballots can be told apart. Not an identity.",
            )
            st.caption(
                f"{len(packet.pairs)} comparisons. {packet.note} You may skip "
                f"any you genuinely cannot judge — a skip is not counted as a "
                f"wrong answer."
            )

            picks = st.session_state.setdefault("blind_picks", {})

            for position, pair in enumerate(packet.pairs, start=1):
                st.divider()
                st.markdown(
                    f"**{position} of {len(packet.pairs)}** — which of these is "
                    f"really by **{pair.author}**?"
                )
                left_column, right_column = st.columns(2)
                with left_column:
                    st.caption("Left")
                    st.text(pair.left)
                with right_column:
                    st.caption("Right")
                    st.text(pair.right)

                choice = st.radio(
                    f"Your pick for {position}",
                    options=["Skip", "Left", "Right"],
                    horizontal=True,
                    key=f"pick_{pair.pair_id}",
                    label_visibility="collapsed",
                )
                if choice == "Skip":
                    picks.pop(pair.pair_id, None)
                else:
                    picks[pair.pair_id] = choice.lower()

            st.divider()
            answered = len(picks)
            st.progress(
                answered / len(packet.pairs),
                text=f"{answered} of {len(packet.pairs)} judged",
            )

            if not reader.strip():
                st.caption("Add your name above to download your ballot.")
            elif not picks:
                st.caption("Make at least one pick to download your ballot.")
            else:
                ballot = Ballot(
                    reader=reader.strip(), picks=dict(picks), packet_id=packet.packet_id
                )
                download_json(
                    "⬇️ Download my ballot",
                    ballot.to_dict(),
                    f"{packet.packet_id}-ballot-{reader.strip().replace(' ', '-')}.json",
                    type="primary",
                )
                st.caption("Send this file back to whoever organised the test.")


# --- Tally ------------------------------------------------------------------

else:
    st.subheader("Combine the key with the ballots")
    packet_column, key_column = st.columns(2)
    with packet_column:
        packet_file = st.file_uploader("Packet", type="json", key="tally_packet")
    with key_column:
        key_file = st.file_uploader("Answer key", type="json", key="tally_key")
    ballot_files = st.file_uploader(
        "Ballots — one per reader",
        type="json",
        accept_multiple_files=True,
        key="tally_ballots",
    )

    if not (packet_file and key_file and ballot_files):
        st.caption(
            f"All three are needed. The protocol asks for at least "
            f"{MIN_READERS} readers; with fewer, the result is reported as "
            f"indicative rather than as a finding."
        )
    else:
        try:
            packet = packet_from_json(packet_file.getvalue())
            key = key_from_json(key_file.getvalue())
            ballots = [ballot_from_json(handle.getvalue()) for handle in ballot_files]
            result = tally(packet, key, ballots)
        except BlindTestError as exc:
            st.error(str(exc))
        else:
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

            download_json(
                "⬇️ Download the result",
                {
                    "packet_id": packet.packet_id,
                    "judgements": result.judgements,
                    "correct": result.correct,
                    "pick_rate": result.pick_rate,
                    "interval": list(result.interval),
                    "readers": result.readers,
                    "enough_readers": result.enough_readers,
                    "meets_gate": result.meets_gate,
                    "by_author": {k: list(v) for k, v in result.by_author.items()},
                    "by_variant": {k: list(v) for k, v in result.by_variant.items()},
                    "verdict": result.verdict,
                },
                f"{packet.packet_id}-result.json",
            )
            st.caption(
                "`docs/evals/` takes one file per run. This is that file, and "
                "a failing number is still worth publishing."
            )
