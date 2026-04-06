"""Streamlit sidebar chat panel (Phase 6)."""

import streamlit as st
from openai import APIConnectionError, AuthenticationError, OpenAIError, RateLimitError

from chatbot.agent import run_agent
from chatbot.env import resolve_openai_api_key

_STARTERS = [
    "What are my RMDs?",
    "When does cash run out?",
    "What if I retire 2 years early?",
    "Summarize my plan",
]

_MODEL_LABEL_TO_ID = {
    "GPT-4o": "gpt-4o",
    "GPT-4o-mini": "gpt-4o-mini",
}


def _tool_status_label(name: str) -> str:
    return {
        "read_simulation": "Reading simulation data…",
        "run_what_if": "Running what-if scenario…",
        "web_search": "Searching the web…",
    }.get(name, f"Running {name}…")


def _run_chat_turn(user_text: str) -> None:
    text = (user_text or "").strip()
    if not text:
        return

    api_key = resolve_openai_api_key(st.session_state.get("openai_api_key"))
    if not api_key:
        st.session_state["chat_messages"] = (
            st.session_state.get("chat_messages", [])
            + [
                {"role": "user", "content": text},
                {
                    "role": "assistant",
                    "content": "Set the OPENAI_API_KEY environment variable or enter an API key in the sidebar.",
                },
            ]
        )[-20:]
        st.rerun()
        return

    if "sim_snapshots" not in st.session_state:
        st.session_state["chat_messages"] = (
            st.session_state.get("chat_messages", [])
            + [
                {"role": "user", "content": text},
                {
                    "role": "assistant",
                    "content": "No simulation data yet. Adjust sidebar inputs so the plan runs.",
                },
            ]
        )[-20:]
        st.rerun()
        return

    label = st.session_state.get("chat_model", "GPT-4o")
    model = _MODEL_LABEL_TO_ID.get(label, "gpt-4o")
    hist = list(st.session_state.get("chat_messages", []))

    try:
        with st.status("Thinking…", expanded=True) as status:

            def cb(info):
                status.update(label=_tool_status_label(info[0]))

            reply, new_hist = run_agent(
                text,
                api_key=st.session_state.get("openai_api_key"),
                model=model,
                chat_history=hist,
                sim_snapshots=st.session_state.get("sim_snapshots"),
                sim_inputs=st.session_state.get("sim_inputs"),
                sim_df=st.session_state.get("sim_df"),
                status_callback=cb,
            )
    except AuthenticationError:
        reply = "OpenAI rejected the API key (authentication failed). Check the key and try again."
        new_hist = hist + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        new_hist = new_hist[-20:]
    except (RateLimitError, APIConnectionError) as e:
        reply = f"Request failed (network or rate limit): {e}"
        new_hist = hist + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        new_hist = new_hist[-20:]
    except OpenAIError as e:
        reply = f"OpenAI error: {e}"
        new_hist = hist + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        new_hist = new_hist[-20:]
    except Exception as e:
        reply = f"Something went wrong: {e}"
        new_hist = hist + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        new_hist = new_hist[-20:]

    st.session_state["chat_messages"] = new_hist
    st.rerun()


def render_chat_panel() -> None:
    with st.expander("🤖 Ask a Question", expanded=False):
        st.text_input(
            "OpenAI API key (optional if OPENAI_API_KEY is set)",
            type="password",
            key="openai_api_key",
            help="Overrides OPENAI_API_KEY for this session when non-empty. "
            "Otherwise the key is read from the OPENAI_API_KEY environment variable.",
        )
        api_key = resolve_openai_api_key(st.session_state.get("openai_api_key"))
        if api_key:
            if (st.session_state.get("openai_api_key") or "").strip():
                st.caption("✓ Using API key from sidebar")
            else:
                st.caption("✓ Using OPENAI_API_KEY from environment")
        else:
            st.caption(
                "No key in this process: set ``OPENAI_API_KEY``, add ``retirement_simulator/.env`` "
                "with OPENAI_API_KEY=…, or enter a key above. "
                "(IDE-launched Streamlit often does not inherit your terminal ``export``.)"
            )

        st.radio(
            "Model",
            ["GPT-4o", "GPT-4o-mini"],
            horizontal=True,
            key="chat_model",
            help="GPT-4o is better for multi-step what-if questions.",
        )

        if "chat_messages" not in st.session_state:
            st.session_state["chat_messages"] = []

        messages = st.session_state["chat_messages"]
        for msg in messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if not messages:
            st.caption("Starter questions:")
            c0, c1, c2, c3 = st.columns(4)
            for i, (col, starter) in enumerate(zip((c0, c1, c2, c3), _STARTERS)):
                if col.button(starter, key=f"chat_starter_{i}", width="stretch"):
                    _run_chat_turn(starter)

        chat_disabled = not api_key
        prompt = st.chat_input(
            "Ask about your plan…",
            disabled=chat_disabled,
        )
        if prompt:
            _run_chat_turn(prompt)
