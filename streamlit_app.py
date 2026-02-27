import os

import streamlit as st
from dotenv import load_dotenv

from copyme import analyze_linguistic_style
from copyme.prompt_pipeline import build_system_prompt, create_chain

load_dotenv()

# --- PAGE CONFIG ---

st.set_page_config(page_title="CopyMe — AI Scribe", page_icon="✍️", layout="wide")

# --- SESSION STATE DEFAULTS ---

if "profile" not in st.session_state:
    st.session_state.profile = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []  # list of {"role": str, "content": str}
if "chain" not in st.session_state:
    st.session_state.chain = None
if "system_prompt" not in st.session_state:
    st.session_state.system_prompt = None

# --- SIDEBAR: API KEY ---

with st.sidebar:
    st.header("Settings")
    env_key = os.environ.get("ANTHROPIC_API_KEY", "")
    api_key_input = st.text_input(
        "Anthropic API Key",
        value=env_key,
        type="password",
        help="Stored in session only. Set ANTHROPIC_API_KEY in a .env file to avoid re-entering.",
    )
    api_key = api_key_input.strip() or env_key

# --- MAIN LAYOUT ---

st.title("✍️ CopyMe — AI Scribe")
st.caption("Generate content that sounds like *you*.")

# --- STEP 1: EXAMPLE TEXT & PROFILE GENERATION ---

st.subheader("1. Provide example text")
example_text = st.text_area(
    "Paste example text that represents your writing style",
    height=200,
    placeholder="Paste a sample of your writing here…",
    key="example_text",
)

if st.button("Generate linguistic profile", type="primary"):
    cleaned = example_text.strip()
    if not cleaned:
        st.warning("Please enter some example text first.")
    elif not api_key:
        st.error("Please provide your Anthropic API key in the sidebar.")
    else:
        with st.spinner("Analyzing writing style…"):
            profile = analyze_linguistic_style(cleaned)
            st.session_state.profile = profile
            st.session_state.system_prompt = build_system_prompt(profile)
            st.session_state.chain = create_chain(api_key=api_key)
            st.session_state.chat_history = []
        st.success("Linguistic profile generated! You can now chat below.")

# --- STEP 2: COLLAPSIBLE LINGUISTIC PROFILE ---

if st.session_state.profile:
    with st.expander("📊 Linguistic Profile", expanded=False):
        profile = st.session_state.profile

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Quantitative Metrics**")
            st.json(profile.get("quantitative", {}))
        with col2:
            st.markdown("**Qualitative Assessments**")
            st.json(profile.get("qualitative", {}))

        st.markdown("**Words Data**")
        st.json(profile.get("words", {}))

    # --- STEP 3: CHAT INTERFACE ---

    st.subheader("2. Chat with your AI scribe")

    # Render existing chat history
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if user_input := st.chat_input("Ask the AI scribe to write something…"):
        if not api_key:
            st.error("Please provide your Anthropic API key in the sidebar.")
        else:
            # Show user message
            st.session_state.chat_history.append({"role": "user", "content": user_input})
            with st.chat_message("user"):
                st.markdown(user_input)

            # Build langchain message history from session
            from langchain_core.messages import AIMessage, HumanMessage

            lc_history = []
            for msg in st.session_state.chat_history[:-1]:  # exclude current
                if msg["role"] == "user":
                    lc_history.append(HumanMessage(content=msg["content"]))
                else:
                    lc_history.append(AIMessage(content=msg["content"]))

            # Recreate chain if needed (e.g. key changed)
            if st.session_state.chain is None:
                st.session_state.chain = create_chain(api_key=api_key)
                st.session_state.system_prompt = build_system_prompt(st.session_state.profile)

            # Invoke
            with st.chat_message("assistant"):
                with st.spinner("Writing…"):
                    result = st.session_state.chain.invoke({
                        "system_prompt": st.session_state.system_prompt,
                        "chat_history": lc_history,
                        "user_input": user_input,
                    })
                    response = result.content
                    st.markdown(response)

            st.session_state.chat_history.append({"role": "assistant", "content": response})
else:
    st.info("👆 Generate a linguistic profile from example text to start chatting.")
