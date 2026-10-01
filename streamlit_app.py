import time

import pandas as pd
import streamlit as st

from copyme import (
    DEFAULT_VOCABULARY_PERCENTILE,
    StyleAnalyser,
    TextTooLongError,
    build_pre_prompt,
    build_profile,
    count_tokens,
    max_length_for_memory,
    memory_budget_from_env,
    memory_for_length,
    summarise_vocabulary,
)


st.set_page_config(page_title="Linguistic Profile Generator", page_icon="📝")

st.title("Linguistic Profile Generator")
st.write(
    "Paste or type text below, generate a linguistic profile, then copy the "
    "pre-prompt at the bottom and paste it into your favourite LLM to write in "
    "the author's voice."
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
                    cleaned_text, memory_gb=memory_gb, on_progress=on_progress
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
    results = build_profile(analyzer, vocabulary_percentile=vocabulary_percentile)
    pre_prompt = build_pre_prompt(results)

    vocabulary = summarise_vocabulary(
        analyzer.word_counts, analyzer.repeated_counts, vocabulary_percentile
    )
    words = vocabulary["common_vocabulary"]
    phrases = vocabulary["frequent_phrases"]

    limits = results.get("limits", {})
    st.caption(
        "Analysed "
        f"{limits.get('text_length', len(cleaned_text)):,} characters "
        f"(limit {limits.get('max_length', max_length):,})."
    )

    st.subheader("Quantitative Metrics")
    st.json(results.get("quantitative", {}))

    st.subheader("Qualitative Assessments")
    st.json(results.get("qualitative", {}))

    st.subheader("Vocabulary & Phrases")
    st.caption(
        f"Most frequent {vocabulary_percentile}% of distinct terms: "
        f"{len(words):,} of {len(analyzer.word_counts):,} words and "
        f"{len(phrases):,} of {len(analyzer.repeated_counts):,} phrases."
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

    st.subheader("Copyable Pre-Prompt")

    token_count, exact = count_tokens(pre_prompt)
    token_label = f"**{token_count:,} tokens**"
    if not exact:
        token_label += " (estimated)"
    st.markdown(
        f"Pre-prompt size: {len(pre_prompt):,} characters \u00b7 {token_label}"
    )
    if not exact:
        st.caption(
            "Install `tiktoken` for exact counts. The estimate is calibrated "
            "against `cl100k_base` and is usually within about 10%."
        )

    st.caption(
        "Click the copy icon in the top-right of the block, then paste into "
        "ChatGPT, Claude, or any other LLM."
    )
    st.code(pre_prompt, language="markdown")
