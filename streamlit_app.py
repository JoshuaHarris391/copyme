import logging
import os

import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage

from copyme import analyze_linguistic_style
from copyme.prompt_pipeline import (
    build_system_prompt,
    create_chain,
    generate_with_refinement,
    list_available_models,
    DEFAULT_MODEL,
    FALLBACK_MODELS,
)

load_dotenv()

# --- LOGGING ---

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)


class _StreamlitLogHandler(logging.Handler):
    """Logging handler that writes the latest log to a
    Streamlit empty placeholder as small grey text."""

    def __init__(self, placeholder):
        super().__init__()
        self._ph = placeholder

    def emit(self, record):
        try:
            msg = record.getMessage()
            self._ph.markdown(
                f'<p style="color:grey;font-size:0.8em;'
                f'margin:0">{msg}</p>',
                unsafe_allow_html=True,
            )
        except Exception:
            pass


# --- PAGE CONFIG ---

st.set_page_config(
    page_title="CopyMe — AI Scribe",
    page_icon="✍️",
    layout="wide",
)

# --- SESSION STATE DEFAULTS ---

_DEFAULTS = {
    "profile": None,
    "chat_history": [],
    "chain": None,
    "system_prompt": None,
    "selected_model": DEFAULT_MODEL,
    "available_models": None,
    "regenerate_index": None,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# --- SIDEBAR ---

with st.sidebar:
    st.header("Settings")

    # API key
    env_key = os.environ.get("ANTHROPIC_API_KEY", "")
    api_key_input = st.text_input(
        "Anthropic API Key",
        value=env_key,
        type="password",
        help=(
            "Stored in session only. "
            "Set ANTHROPIC_API_KEY in .env to avoid re-entering."
        ),
    )
    api_key = api_key_input.strip() or env_key

    # Model selector — query available models
    if api_key and st.session_state.available_models is None:
        with st.spinner("Fetching models…"):
            st.session_state.available_models = (
                list_available_models(api_key)
            )

    model_options = (
        st.session_state.available_models or FALLBACK_MODELS
    )

    # Ensure default is in the list
    if DEFAULT_MODEL not in model_options:
        model_options = [DEFAULT_MODEL] + model_options

    default_idx = (
        model_options.index(DEFAULT_MODEL)
        if DEFAULT_MODEL in model_options
        else 0
    )

    selected_model = st.selectbox(
        "Model",
        options=model_options,
        index=default_idx,
        help="Select which Anthropic model to use.",
    )
    st.session_state.selected_model = selected_model

    # Refresh button
    if api_key and st.button("🔄 Refresh models"):
        st.session_state.available_models = (
            list_available_models(api_key)
        )
        st.rerun()

    st.divider()
    st.subheader("Model Tuning")

    temperature = st.slider(
        "Temperature",
        min_value=0.0,
        max_value=1.0,
        value=0.7,
        step=0.05,
        help=(
            "Controls randomness in word choice. "
            "Lower = more deterministic and focused. "
            "Higher = more creative and varied. "
            "0.7 is recommended for style mimicry."
        ),
    )

    max_tokens = st.slider(
        "Max Tokens",
        min_value=256,
        max_value=8192,
        value=4096,
        step=256,
        help=(
            "Maximum number of tokens (roughly words) "
            "the model can generate in a single response. "
            "Increase for longer outputs."
        ),
    )

    max_refinement_iters = st.slider(
        "Max Refinement Iterations",
        min_value=1,
        max_value=5,
        value=3,
        step=1,
        help=(
            "How many times the AI reviews and revises "
            "its output against your linguistic profile. "
            "More iterations = better style match "
            "but slower."
        ),
    )

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
        st.error(
            "Please provide your Anthropic API key "
            "in the sidebar."
        )
    else:
        with st.spinner("Analyzing writing style…"):
            profile = analyze_linguistic_style(cleaned)
            st.session_state.profile = profile
            sp = build_system_prompt(profile)
            st.session_state.system_prompt = sp
            st.session_state.chain = create_chain(
                api_key=api_key,
                model=st.session_state.selected_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            st.session_state.chat_history = []
        st.success(
            "Linguistic profile generated! "
            "You can now chat below."
        )

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

    # Handle pending regeneration
    _regen_idx = st.session_state.regenerate_index
    if _regen_idx is not None:
        # Remove the assistant message at _regen_idx
        st.session_state.chat_history.pop(_regen_idx)
        st.session_state.regenerate_index = None

    # Render existing chat history with regenerate buttons
    for _i, msg in enumerate(st.session_state.chat_history):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                if st.button(
                    "🔄 Regenerate",
                    key=f"regen_{_i}",
                    help=(
                        "Re-generate this response with "
                        "current model and settings."
                    ),
                ):
                    st.session_state.regenerate_index = _i
                    st.rerun()

    # Determine if we need to generate (new input or regeneration)
    _needs_generation = False
    _gen_prompt = None

    # Check for regeneration: last message is now a user
    # message that lost its assistant reply
    _hist = st.session_state.chat_history
    if (
        _hist
        and _hist[-1]["role"] == "user"
        and (
            len(_hist) < 2
            or _hist[-2]["role"] != "assistant"
            or _regen_idx is not None
        )
    ):
        _needs_generation = True
        _gen_prompt = _hist[-1]["content"]

    # Chat input
    user_input = st.chat_input(
        "Ask the AI scribe to write something…"
    )
    if user_input:
        if not api_key:
            st.error(
                "Please provide your Anthropic API key "
                "in the sidebar."
            )
        else:
            st.session_state.chat_history.append(
                {"role": "user", "content": user_input}
            )
            _needs_generation = True
            _gen_prompt = user_input
            with st.chat_message("user"):
                st.markdown(user_input)

    if _needs_generation and _gen_prompt and api_key:
        # Build LangChain history (everything before the
        # last user message)
        lc_history = []
        for msg in st.session_state.chat_history[:-1]:
            if msg["role"] == "user":
                lc_history.append(
                    HumanMessage(content=msg["content"])
                )
            else:
                lc_history.append(
                    AIMessage(content=msg["content"])
                )

        # Recreate chain if needed
        if st.session_state.chain is None:
            st.session_state.chain = create_chain(
                api_key=api_key,
                model=st.session_state.selected_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            st.session_state.system_prompt = (
                build_system_prompt(
                    st.session_state.profile
                )
            )

        # Invoke with refinement loop
        with st.chat_message("assistant"):
            _log_ph = st.empty()
            _log_handler = _StreamlitLogHandler(_log_ph)
            _log_handler.setLevel(logging.INFO)
            _pipeline_logger = logging.getLogger(
                "copyme.prompt_pipeline"
            )
            _pipeline_logger.addHandler(_log_handler)
            try:
                with st.spinner("Writing & refining…"):
                    result = generate_with_refinement(
                        profile=st.session_state.profile,
                        user_prompt=_gen_prompt,
                        api_key=api_key,
                        model=(
                            st.session_state
                            .selected_model
                        ),
                        chat_history=lc_history,
                        max_iterations=(
                            max_refinement_iters
                        ),
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
            finally:
                _pipeline_logger.removeHandler(
                    _log_handler
                )
                _log_ph.empty()
            response = result["content"]
            st.markdown(response)

            # Show refinement iterations
            iters = result["iterations"]
            total = result["total_iterations"]
            if total > 0:
                label = (
                    f"🔄 Refinement: "
                    f"{total} iteration(s)"
                )
                last = iters[-1]["verdict"]
                if last == "PASS":
                    label += " — ✅ PASSED"
                else:
                    label += " — ⚠️ best effort"

                with st.expander(label, expanded=False):
                    for idx, it in enumerate(iters, 1):
                        st.markdown(
                            f"**Iteration {idx}** "
                            f"— {it['verdict']}"
                        )
                        st.markdown(
                            it["critique"]
                        )
                        if idx < total:
                            st.divider()

        st.session_state.chat_history.append(
            {"role": "assistant", "content": response}
        )
        st.rerun()
else:
    st.info(
        "👆 Generate a linguistic profile from "
        "example text to start chatting."
    )
