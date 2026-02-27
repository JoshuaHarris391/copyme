import streamlit as st

from copyme import analyze_linguistic_style


st.set_page_config(page_title="Linguistic Profile Generator", page_icon="📝")

st.title("Linguistic Profile Generator")
st.write("Paste or type text below, then generate a linguistic profile.")

text_input = st.text_area(
    "Text to analyze",
    height=260,
    placeholder="Enter text here...",
)

if st.button("Generate linguistic profile", type="primary"):
    cleaned_text = text_input.strip()

    if not cleaned_text:
        st.warning("Please enter some text before generating a profile.")
    else:
        with st.spinner("Analyzing text..."):
            results = analyze_linguistic_style(cleaned_text)

        st.subheader("Quantitative Metrics")
        st.json(results.get("quantitative", {}))

        st.subheader("Qualitative Assessments")
        st.json(results.get("qualitative", {}))

        st.subheader("Words Data")
        st.json(results.get("words", {}))
