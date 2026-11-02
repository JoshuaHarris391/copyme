import time

import pandas as pd
import streamlit as st

from copyme import (
    DEFAULT_MAX_PHRASE_WORDS,
    DEFAULT_VOCABULARY_PERCENTILE,
    FORMATS,
    MAX_PHRASE_WORDS,
    MIN_PHRASE_WORDS,
    SIZE_PRESETS,
    StyleAnalyser,
    TextTooLongError,
    build_pre_prompt,
    build_profile,
    max_length_for_memory,
    memory_budget_from_env,
    memory_for_length,
    score,
    summarise_vocabulary,
    token_estimates,
)
from copyme.analyser import V2_ANALYSIS_STAGES
from copyme.profile import COMFORTABLE_WORDS, RECOMMENDED_MINIMUM_WORDS

# What each export target is for, shown beside the selector so the choice does
# not require reading the documentation.
FORMAT_HELP = {
    "first_message": "Paste as the first message of a chat.",
    "system_prompt": "For a system-prompt field, a custom GPT or a Claude Project.",
    "voice_card": "Five lines to re-paste when a long chat starts to drift.",
    "sillytavern_card": "Character Card V2 JSON for SillyTavern and compatible front ends.",
    "json": "The whole profile, for programs and for `copyme score`.",
    "exemplars": "Just the passages, for an application that assembles its own prompt.",
    "rules": "Just the rules, for the same reason.",
}


st.set_page_config(page_title="Linguistic Profile Generator", page_icon="📝")

st.title("Linguistic Profile Generator")
st.write(
    "Paste or type text below, generate a voice profile, then copy it into your "
    "favourite LLM to write in the author's voice. The profile carries the "
    "author's own passages and a set of followable rules; the measurements work "
    "behind it, choosing the passages and writing the rules."
)
st.caption(
    f"About {RECOMMENDED_MINIMUM_WORDS:,} words gives a recognisable voice; "
    f"{COMFORTABLE_WORDS:,} or more gives a reliable one. Exemplar selection "
    f"needs passages to choose between."
)

text_input = st.text_area(
    "Text to analyze",
    height=260,
    placeholder="Enter text here...",
)

cleaned_text = text_input.strip()

with st.sidebar:
    st.header("Analysis limits")
    st.write(
        "SpaCy's parser and NER models need roughly 1 GB of temporary memory "
        "per 100,000 characters of input, so the memory budget sets the "
        "longest text that can be analysed."
    )
    default_memory_gb = float(memory_budget_from_env())
    memory_gb = st.number_input(
        "Temporary memory budget (GB)",
        min_value=1.0,
        max_value=256.0,
        value=min(max(default_memory_gb, 1.0), 256.0),
        step=1.0,
    )
    max_length = max_length_for_memory(memory_gb)
    st.metric("Maximum text length", f"{max_length:,} characters")
    st.caption(f"Current input: {len(cleaned_text):,} characters")

    st.header("Profile size")
    st.write(
        "How much of the author's writing to carry, and therefore where the "
        "profile will fit."
    )
    size = st.radio(
        "Size",
        options=list(SIZE_PRESETS),
        index=list(SIZE_PRESETS).index("standard"),
        format_func=lambda key: (
            f"{key.capitalize()} — up to {SIZE_PRESETS[key]['total']:,} tokens, "
            f"{SIZE_PRESETS[key]['min_n']}–{SIZE_PRESETS[key]['max_n']} passages"
        ),
        help=(
            "The token figure is a ceiling, not a target. Changing size "
            "re-selects from the cached parse, so it is instant."
        ),
    )
    st.caption(f"Best for {SIZE_PRESETS[size]['use']}.")

    mask_names = st.toggle(
        "Mask one-off names",
        value=True,
        help=(
            "Replaces a name mentioned once or twice with a role placeholder, "
            "so a passing mention cannot leak. Names the author uses "
            "throughout are kept: they are part of the voice."
        ),
    )

    st.header("Vocabulary")
    st.write(
        "Words and phrases are ranked by frequency, then trimmed to the most "
        "frequent share of distinct terms. Lower values keep only the words the "
        "author leans on most; higher values keep more of the long tail."
    )
    vocabulary_percentile = st.slider(
        "Keep the most frequent (%)",
        min_value=1,
        max_value=100,
        value=int(DEFAULT_VOCABULARY_PERCENTILE),
        step=1,
        help=(
            "Proportional, not absolute: 20% of a short text is a handful of "
            "terms, 20% of a long text is a lot. Changing this re-derives the "
            "vocabulary from the cached parse, so it is instant."
        ),
    )

    st.header("Phrases")
    st.write(
        "Phrases are repeated word sequences. Set how long they may get: 2 "
        "counts pairs like \"of the\", 4 counts \"in the end of the\". Longer "
        "sequences rarely repeat, so raising this mostly reshuffles the "
        "shorter candidates."
    )
    max_phrase_words = st.slider(
        "Longest phrase (words)",
        min_value=MIN_PHRASE_WORDS,
        max_value=MAX_PHRASE_WORDS,
        value=DEFAULT_MAX_PHRASE_WORDS,
        step=1,
        help=(
            "Applies to the phrase list and the pre-prompt. Formulaic Density "
            "stays pinned to 2-4 word sequences so profiles remain comparable. "
            "Changing this re-derives from the cached parse, so it is instant."
        ),
    )


# The SpaCy parse is the expensive half of the analysis, so it runs only when
# the button is pressed. Everything below re-derives from that cached parse, so
# changing the vocabulary slider stays instant instead of re-parsing the text.

signature = (cleaned_text, float(memory_gb))
analysis = st.session_state.get("analysis")

if analysis is not None and analysis["signature"] != signature:
    # Text or memory budget changed: the cached parse no longer applies. Drop it
    # so the SpaCy document is released instead of being held in session state.
    # Note: dict.pop() returns the removed value, so clear the flag separately.
    st.session_state.pop("analysis", None)
    analysis = None

if st.button("Generate linguistic profile", type="primary"):
    if not cleaned_text:
        st.warning("Please enter some text before generating a profile.")
    else:
        started = time.monotonic()

        with st.status("Analyzing text...", expanded=True) as status:
            progress_bar = st.progress(0.0, text="Starting analysis...")
            stage_caption = st.empty()

            def on_progress(label, percent):
                elapsed = time.monotonic() - started
                progress_bar.progress(
                    min(percent / 100.0, 1.0),
                    text=f"{label} — {percent:.0f}%",
                )
                stage_caption.caption(f"Elapsed: {elapsed:.1f}s")

            try:
                analyzer = StyleAnalyser(
                    cleaned_text,
                    memory_gb=memory_gb,
                    on_progress=on_progress,
                    # Exemplar selection and rule rendering run after the
                    # metrics, so the bar is scaled to include them.
                    stages=V2_ANALYSIS_STAGES,
                )
            except TextTooLongError as exc:
                progress_bar.empty()
                stage_caption.empty()
                status.update(label="Analysis failed", state="error", expanded=True)
                st.error(
                    f"This input is too long for the current memory budget.\n\n"
                    f"{exc}\n\n"
                    f"Raise **Temporary memory budget** to about "
                    f"{memory_for_length(len(cleaned_text)):g} GB in the sidebar "
                    f"and try again."
                )
            else:
                analysis = {"signature": signature, "analyzer": analyzer}
                st.session_state["analysis"] = analysis
                stage_caption.empty()
                progress_bar.progress(1.0, text="Done")
                status.update(
                    label=f"Analysis complete in {time.monotonic() - started:.1f}s",
                    state="complete",
                    expanded=False,
                )


if analysis is not None:
    analyzer = analysis["analyzer"]

    # Selection is cached per (size, percentile, phrase length, masking) in the
    # same way the phrase counts are, so moving a slider or switching tabs
    # re-derives from the cached parse instead of re-selecting.
    profile_key = (size, vocabulary_percentile, max_phrase_words, mask_names)
    cache = analysis.setdefault("profiles", {})
    if profile_key not in cache:
        cache[profile_key] = build_profile(
            analyzer,
            vocabulary_percentile=vocabulary_percentile,
            max_phrase_words=max_phrase_words,
            size=size,
            mask_names=mask_names,
        )
    profile = cache[profile_key]
    results = profile.metrics

    phrase_counts = analyzer.phrase_counts(max_phrase_words)
    vocabulary = summarise_vocabulary(
        analyzer.word_counts, phrase_counts, vocabulary_percentile
    )
    words = vocabulary["common_vocabulary"]
    phrases = vocabulary["frequent_phrases"]

    limits = results.get("limits", {})
    st.caption(
        "Analysed "
        f"{limits.get('text_length', len(cleaned_text)):,} characters, "
        f"{profile.word_count:,} words, into "
        f"{profile.provenance.get('candidate_passages', 0):,} candidate passages "
        f"(limit {limits.get('max_length', max_length):,} characters)."
    )

    if profile.thin:
        st.warning(
            f"This sample is under {RECOMMENDED_MINIMUM_WORDS:,} words, so the "
            f"profile describes the voice loosely. The prompt says so too. Add "
            f"more of the author's writing for a profile worth relying on."
        )
    if profile.provenance.get("entity_check_relaxed"):
        st.info(
            "This writer keeps to one subject throughout, so the passages carry "
            "more subject matter than usual. The prompt warns the model to take "
            "the manner and leave the subject."
        )
    if profile.provenance.get("baseline_status") == "provisional":
        st.caption(
            "Rules are suppressed against a **provisional** baseline of generic "
            "prose, which is good enough to rank and filter but not to publish "
            "numbers from. Expect the rule set to shift when it is replaced."
        )

    profile_tab, score_tab = st.tabs(["Profile", "Score a draft"])

    with profile_tab:
        st.subheader("The passages it chose, and why")
        st.caption(
            "The reason is for you. It is never sent to the model: a model shown "
            "the reasoning imitates the reasoning."
        )
        if not profile.exemplars:
            st.info(
                "No passage was long enough to use as an exemplar. Paste a "
                "longer sample, or one with fuller paragraphs."
            )
        for position, exemplar in enumerate(profile.exemplars, start=1):
            with st.expander(
                f"{position}. {exemplar.reason}  "
                f"\u00b7 {exemplar.token_count} tokens",
                expanded=position == 1,
            ):
                st.markdown(
                    f"Typicality {exemplar.typicality:.2f} \u00b7 "
                    f"distinctiveness {exemplar.distinctiveness:.2f} \u00b7 "
                    f"diversity {exemplar.diversity:.2f}"
                )
                body = exemplar.masked_text if mask_names and exemplar.masked_text else exemplar.text
                st.text(body)

        st.subheader("Voice rules")
        if not profile.rules:
            st.info(
                "This writer's measurable habits sit close to ordinary prose, so "
                "there is nothing worth instructing. The passages carry the voice."
            )
        for rule in profile.rules:
            st.markdown(f"- {rule.prose}")

        if profile.known_failures:
            st.subheader("Where this usually goes wrong")
            for note in profile.known_failures:
                st.markdown(note)

        st.subheader("Copy it, in the format you need")
        export_format = st.selectbox(
            "Format",
            options=list(FORMATS),
            format_func=lambda key: f"{key} \u2014 {FORMAT_HELP[key]}",
        )
        rendered = build_pre_prompt(
            profile, size=size, format=export_format, mask_names=mask_names
        )

        counts = token_estimates(rendered)
        gpt_label = f"**{counts['gpt']:,}**" + ("" if counts["gpt_exact"] else " (estimated)")
        st.markdown(
            f"{len(rendered):,} characters \u00b7 GPT family {gpt_label} tokens "
            f"\u00b7 Claude **{counts['claude']:,}** tokens (estimated)"
        )
        st.caption(
            f"Two figures because the tokenisers differ. The GPT figure uses "
            f"`cl100k_base`"
            + ("" if counts["gpt_exact"] else " (install `tiktoken` for an exact count)")
            + f"; the Claude figure is that number times "
            f"{counts['multiplier']}, because no offline Claude tokeniser is "
            f"available. Both are guides, not guarantees."
        )
        st.caption(
            "Click the copy icon in the top-right of the block, then paste it "
            "where it is going."
        )
        st.code(
            rendered,
            language="json" if export_format in ("json", "sillytavern_card") else "markdown",
        )

        with st.expander("Raw metrics", expanded=False):
            st.caption(
                "Nothing is taken away from you; these just stopped being the "
                "prompt. A model cannot act on a number, which is why v2 sends "
                "passages and rules instead."
            )
            st.markdown("**The v2 feature vector**")
            st.json(profile.features)
            st.markdown("**Quantitative metrics**")
            st.json(results.get("quantitative", {}))
            st.markdown("**Qualitative assessments**")
            st.json(results.get("qualitative", {}))
            st.markdown("**Style vocabulary and idioms**")
            st.caption(
                "Filtered to manner rather than subject: connectives and "
                "qualifiers survive, nouns and names do not."
            )
            st.json(profile.vocabulary)
            st.markdown("**Provenance**")
            st.json(profile.provenance)

            st.markdown("**Vocabulary and phrases, unfiltered**")
            st.caption(
                f"Most frequent {vocabulary_percentile}% of distinct terms: "
                f"{len(words):,} of {len(analyzer.word_counts):,} words and "
                f"{len(phrases):,} of {len(phrase_counts):,} phrases "
                f"({MIN_PHRASE_WORDS}\u2013{max_phrase_words} words long)."
            )
            if not words and not phrases:
                st.info("No vocabulary was captured from this text.")
            else:
                words_column, phrases_column = st.columns(2)
                with words_column:
                    st.markdown("**Words**")
                    st.dataframe(
                        pd.DataFrame(words, columns=["term", "count"]), hide_index=True
                    )
                with phrases_column:
                    st.markdown("**Phrases**")
                    st.dataframe(
                        pd.DataFrame(phrases, columns=["term", "count"]), hide_index=True
                    )

    with score_tab:
        st.subheader("Score a draft against this profile")
        st.write(
            "Paste what the model wrote. This compares it with the author on "
            "every rule the profile set, and checks that nothing was copied "
            "outright."
        )
        draft = st.text_area("The model's output", height=220, key="draft")
        if st.button("Score it"):
            if not draft.strip():
                st.warning("Paste the model's output first.")
            else:
                report = score(draft, profile)
                st.metric("Rules met", f"{report.in_band:.0%}")
                st.markdown(f"**{report.summary.splitlines()[0]}**")

                rows = [
                    {
                        "feature": drift.feature,
                        "author": drift.author,
                        "draft": drift.generated,
                        "verdict": drift.verdict,
                        "note": drift.note,
                    }
                    for drift in report.drifts
                ]
                if rows:
                    st.dataframe(pd.DataFrame(rows), hide_index=True)

                if report.copied_spans:
                    st.error(
                        f"{len(report.copied_spans)} span(s) of 12 or more "
                        f"consecutive words were copied from the sample. The "
                        f"prompt asks the model not to do this."
                    )
                    for span in report.copied_spans:
                        st.markdown(f"> {span}")
                else:
                    st.success("No copied spans of 12 or more words.")

                st.caption(report.footer)
