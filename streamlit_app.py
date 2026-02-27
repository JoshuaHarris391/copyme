import logging
import os

import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage

from copyme import analyze_linguistic_style
from copyme.prompt_pipeline import (
    build_system_prompt,
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
    Streamlit empty placeholder as small grey text, and
    accumulates all logs into session state."""

    def __init__(self, placeholder):
        super().__init__()
        self._ph = placeholder

    def emit(self, record):
        try:
            msg = self.format(record)
            self._ph.markdown(
                f'<p style="color:grey;font-size:0.8em;'
                f'margin:0">{record.getMessage()}</p>',
                unsafe_allow_html=True,
            )
            if "logs" in st.session_state:
                st.session_state.logs.append(msg)
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
    "system_prompt": None,
    "selected_model": DEFAULT_MODEL,
    "available_models": None,
    "regenerate_index": None,
    "edit_index": None,
    "logs": [],
    "sidebar_view": "💬 Chat",
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
        value=0.3,
        step=0.05,
        help=(
            "Controls randomness in word choice. "
            "Lower = more deterministic and focused. "
            "Higher = more creative and varied. "
            "0.3 is recommended for style mimicry."
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
        value=2,
        step=1,
        help=(
            "How many times the AI reviews and revises "
            "its output against your linguistic profile. "
            "More iterations = better style match "
            "but slower."
        ),
    )

    st.divider()
    st.subheader("View")

    _view = st.radio(
        "Select view",
        ["💬 Chat", "📋 Logs"],
        index=(
            0
            if st.session_state.sidebar_view
            == "💬 Chat"
            else 1
        ),
        label_visibility="collapsed",
    )
    st.session_state.sidebar_view = _view

    st.divider()
    st.subheader("Session")

    if st.button(
        "🗑️ Clear Chat Only",
        help=(
            "Reset chat history but keep your "
            "linguistic profile and example text."
        ),
    ):
        st.session_state.chat_history = []
        st.session_state.regenerate_index = None
        st.session_state.edit_index = None
        st.rerun()

    if st.button(
        "🗑️ Clear All & Reset",
        type="primary",
        help=(
            "Full hard reset: clears all caches, "
            "profile, chat history, and session state."
        ),
    ):
        st.cache_data.clear()
        st.cache_resource.clear()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

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

    # --- STEP 3: VIEW SWITCHER ---

    if _view == "📋 Logs":
        st.subheader("📋 Logs")
        _log_container = st.container()
        with _log_container:
            if st.session_state.logs:
                st.code(
                    "\n".join(
                        st.session_state.logs
                    ),
                    language="log",
                )
            else:
                st.info(
                    "No logs yet. Generate a "
                    "response to see logs here."
                )
        if st.button("🗑️ Clear logs"):
            st.session_state.logs = []
            st.rerun()

    else:
        # Handle pending regeneration
        _regen_idx = st.session_state.regenerate_index
        if _regen_idx is not None:
            st.session_state.chat_history.pop(_regen_idx)
            st.session_state.regenerate_index = None

        # Handle pending edit
        _edit_idx = st.session_state.edit_index
        if _edit_idx is not None:
            _old_content = (
                st.session_state.chat_history[_edit_idx]
                ["content"]
            )
            with st.chat_message("user"):
                st.markdown(
                    "*✏️ Editing your message:*"
                )
                _edited = st.text_area(
                    "Edit your message",
                    value=_old_content,
                    height=150,
                    key="edit_text_area",
                )
                _col1, _col2 = st.columns(2)
                with _col1:
                    if st.button(
                        "✅ Send edited message",
                        type="primary",
                    ):
                        st.session_state.chat_history[
                            _edit_idx
                        ]["content"] = _edited.strip()
                        st.session_state.chat_history = (
                            st.session_state
                            .chat_history[
                                :_edit_idx + 1
                            ]
                        )
                        st.session_state.edit_index = (
                            None
                        )
                        st.rerun()
                with _col2:
                    if st.button("❌ Cancel"):
                        st.session_state.edit_index = (
                            None
                        )
                        st.rerun()
            st.stop()

        # Render chat history with action buttons
        for _i, msg in enumerate(
            st.session_state.chat_history
        ):
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg["role"] == "assistant":
                    if st.button(
                        "🔄 Regenerate",
                        key=f"regen_{_i}",
                        help=(
                            "Re-generate this response "
                            "with current model and "
                            "settings."
                        ),
                    ):
                        st.session_state.regenerate_index = _i
                        st.rerun()
                elif msg["role"] == "user":
                    if st.button(
                        "✏️ Edit & Resend",
                        key=f"edit_{_i}",
                        help=(
                            "Edit this message and "
                            "re-generate from here."
                        ),
                    ):
                        st.session_state.edit_index = _i
                        st.rerun()

        # Determine if we need to generate
        _needs_generation = False
        _gen_prompt = None

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
                    "Please provide your Anthropic "
                    "API key in the sidebar."
                )
            else:
                st.session_state.chat_history.append(
                    {
                        "role": "user",
                        "content": user_input,
                    }
                )
                _needs_generation = True
                _gen_prompt = user_input
                with st.chat_message("user"):
                    st.markdown(user_input)

        if (
            _needs_generation
            and _gen_prompt
            and api_key
        ):
            # Build LangChain history
            lc_history = []
            for msg in (
                st.session_state.chat_history[:-1]
            ):
                if msg["role"] == "user":
                    lc_history.append(
                        HumanMessage(
                            content=msg["content"]
                        )
                    )
                else:
                    lc_history.append(
                        AIMessage(
                            content=msg["content"]
                        )
                    )

            # Invoke with refinement loop
            with st.chat_message("assistant"):
                _log_ph = st.empty()
                _log_handler = _StreamlitLogHandler(
                    _log_ph
                )
                _log_handler.setLevel(logging.INFO)
                _log_handler.setFormatter(
                    logging.Formatter(
                        "%(asctime)s [%(name)s] "
                        "%(levelname)s: %(message)s",
                        datefmt="%H:%M:%S",
                    )
                )
                _pipeline_logger = logging.getLogger(
                    "copyme.prompt_pipeline"
                )
                _pipeline_logger.addHandler(
                    _log_handler
                )

                # Live draft output
                _drafts_ctr = st.container()

                def _on_draft(label, text):
                    with _drafts_ctr:
                        with st.expander(
                            f"📝 {label}",
                            expanded=False,
                        ):
                            st.markdown(text)

                try:
                    with st.spinner(
                        "Writing & refining…"
                    ):
                        result = (
                            generate_with_refinement(
                                profile=(
                                    st.session_state
                                    .profile
                                ),
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
                                on_draft=_on_draft,
                            )
                        )
                finally:
                    _pipeline_logger.removeHandler(
                        _log_handler
                    )
                    _log_ph.empty()

                response = result["content"]
                st.markdown("### Final Response")
                st.markdown(response)

                # Show refinement iterations
                iters = result["iterations"]
                total = result["total_iterations"]
                init_draft = result.get(
                    "initial_draft"
                )
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

                    with st.expander(
                        label, expanded=False
                    ):
                        if init_draft:
                            st.markdown(
                                "### Original Draft"
                            )
                            st.markdown(init_draft)
                            st.divider()

                        for idx, it in enumerate(
                            iters, 1
                        ):
                            verdict_icon = (
                                "✅"
                                if it["verdict"]
                                == "PASS"
                                else "❌"
                            )
                            st.markdown(
                                f"### Iteration "
                                f"{idx} "
                                f"{verdict_icon} "
                                f"{it['verdict']}"
                            )

                            st.markdown(
                                "**Draft Reviewed**"
                            )
                            st.markdown(
                                it["draft"]
                            )

                            pdiff = it.get(
                                "profile_diff"
                            )
                            if pdiff:
                                st.markdown(
                                    "**Linguistic "
                                    "Profile "
                                    "Comparison**"
                                )
                                st.code(
                                    pdiff,
                                    language=(
                                        "markdown"
                                    ),
                                )

                            st.markdown(
                                "**Reviewer "
                                "Analysis**"
                            )
                            st.markdown(
                                it["critique"]
                            )

                            if (
                                it["verdict"]
                                != "PASS"
                            ):
                                st.markdown(
                                    "**Revision "
                                    "Plan:** "
                                    "Adjusting draft "
                                    "to close metric "
                                    "gaps and "
                                    "incorporate "
                                    "profile "
                                    "vocabulary."
                                )

                            if idx < total:
                                st.divider()

                        st.divider()
                        st.markdown(
                            "### Final Output"
                        )
                        st.markdown(response)

            st.session_state.chat_history.append(
                {
                    "role": "assistant",
                    "content": response,
                }
            )
            st.rerun()
else:
    st.info(
        "👆 Generate a linguistic profile from "
        "example text to start chatting."
    )
