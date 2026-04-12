"""OpenAI chat agent with function calling (Phase 5)."""

import json

from openai import OpenAI

from chatbot.env import resolve_openai_api_key
from chatbot.prompts import SYSTEM_PROMPT
from chatbot.tools import (
    FIND_THRESHOLD_SCHEMA,
    READ_SIMULATION_SCHEMA,
    RUN_WHAT_IF_SCHEMA,
    WEB_SEARCH_SCHEMA,
    find_threshold,
    read_simulation,
    run_what_if,
    web_search,
)

_TOOLS = [READ_SIMULATION_SCHEMA, RUN_WHAT_IF_SCHEMA, FIND_THRESHOLD_SCHEMA, WEB_SEARCH_SCHEMA]

_MAX_TOOL_ROUNDS = 5


def _assistant_message_dict(message) -> dict:
    """Convert chat.completions message object to API message dict."""
    d = {"role": message.role, "content": message.content}
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                },
            }
            for tc in tool_calls
        ]
    return d


def _dispatch_tool(
    name: str,
    arguments_json: str,
    *,
    api_key: str,
    sim_count: list,
    status_callback,
) -> dict:
    args = json.loads(arguments_json) if arguments_json else {}
    if status_callback is not None:
        status_callback((name, args))
    if name == "read_simulation":
        return read_simulation(
            args.get("query", "summary"),
            args.get("start_year"),
            args.get("end_year"),
        )
    if name == "run_what_if":
        return run_what_if(
            args.get("overrides") or {},
            args.get("compare_metric"),
            _sim_count=sim_count,
        )
    if name == "find_threshold":
        return find_threshold(
            args.get("parameter", ""),
            args.get("direction", ""),
            args.get("lo", 0),
            args.get("hi", 0),
            args.get("tolerance", 500.0),
            args.get("target", "liquid_assets_through_bridge"),
            args.get("target_fi_year"),
            args.get("context_overrides"),
            target_net_worth=args.get("target_net_worth"),
            max_iterations=args.get("max_iterations", 30),
        )
    if name == "web_search":
        return web_search(
            args.get("query", ""),
            args.get("context"),
            api_key=api_key,
        )
    return {"error": f"Unknown tool: {name}"}


def run_agent(
    user_message: str,
    *,
    api_key: str,
    model: str,
    chat_history: list,
    sim_snapshots=None,
    sim_inputs=None,
    sim_df=None,
    status_callback=None,
):
    """Run one user turn: optional tool loop, then return assistant text and display history.

    `sim_snapshots`, `sim_inputs`, and `sim_df` are reserved for future context injection; tools
    currently read the latest run from ``st.session_state`` when used inside Streamlit.

    ``status_callback`` is called as ``status_callback((tool_name, tool_args_dict))`` immediately
    before each tool runs.

    Returns:
        ``(assistant_text: str, updated_chat_history: list)`` where ``updated_chat_history`` is
        ``chat_history`` plus this user message and assistant reply, trimmed to the last 20 messages.
    """
    _ = (sim_snapshots, sim_inputs, sim_df)

    history_slice = list(chat_history)[-20:] if chat_history else []
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history_slice)
    messages.append({"role": "user", "content": user_message})

    key = resolve_openai_api_key(api_key)
    if not key:
        msg = (
            "No OpenAI API key available. Set the OPENAI_API_KEY environment variable "
            "or enter a key in the chat panel."
        )
        updated = history_slice + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": msg},
        ]
        return msg, updated[-20:]

    client = OpenAI(api_key=key)
    sim_count = [0]
    final_text = ""

    for _ in range(_MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=_TOOLS,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            final_text = (msg.content or "").strip()
            break

        messages.append(_assistant_message_dict(msg))
        for tc in msg.tool_calls:
            result = _dispatch_tool(
                tc.function.name,
                tc.function.arguments or "{}",
                api_key=key,
                sim_count=sim_count,
                status_callback=status_callback,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                }
            )
    else:
        final_text = (
            "I could not finish answering within the tool-call limit. "
            "Try breaking the question into smaller steps."
        )

    updated = list(history_slice) + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": final_text},
    ]
    updated = updated[-20:]
    return final_text, updated
