import time

import streamlit as st

from copyme import (
    TextTooLongError,
    analyze_linguistic_style,
    build_pre_prompt,
    max_length_for_memory,
    memory_budget_from_env,
    memory_for_length,
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

if st.button("Generate linguistic profile", type="primary"):
    if not cleaned_text:
        st.warning("Please enter some text before generating a profile.")
    else:
        started = time.monotonic()
        results = None

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
                results = analyze_linguistic_style(
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
                pre_prompt = build_pre_prompt(results)
                progress_bar.progress(1.0, text="Done")
                status.update(
                    label=(
                        "Analysis complete in "
                        f"{time.monotonic() - started:.1f}s"
                    ),
                    state="complete",
                    expanded=False,
                )

        if results is not None:
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

            st.subheader("Words Data")
            st.json(results.get("words", {}))

            st.subheader("Copyable Pre-Prompt")
            st.caption(
                "Click the copy icon in the top-right of the block, then paste into "
                "ChatGPT, Claude, or any other LLM."
            )
            st.code(pre_prompt, language="markdown")
