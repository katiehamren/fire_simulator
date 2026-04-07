"""Streamlit app entry: validation, simulation, tabs, chat sidebar."""

import hashlib

import streamlit as st

from engine.models import SimInputs
from engine.simulator import run_simulation

from chatbot.ui import render_chat_panel

from .formatting import to_df
from .sidebar import build_inputs
from .validation import validate_inputs
from .tabs.account_balances import render_account_balances
from .tabs.bridge_strategies import render_bridge_strategies
from .tabs.income_cashflow import render_income_cashflow
from .tabs.insights import render_insights
from .tabs.overview import render_overview
from .tabs.sensitivity import render_sensitivity
from .tabs.year_detail import render_detail


def _inputs_hash(inputs: SimInputs) -> str:
    """Quick hash of inputs to detect sidebar changes."""
    return hashlib.md5(str(inputs).encode()).hexdigest()


def main() -> None:
    inputs = build_inputs()

    for level, msg in validate_inputs(inputs):
        (st.error if level == "error" else st.warning)(msg)

    snapshots = run_simulation(inputs)
    df = to_df(snapshots, inputs.assumptions.inflation_rate)

    st.session_state["sim_snapshots"] = snapshots
    st.session_state["sim_inputs"] = inputs
    st.session_state["sim_df"] = df

    current_hash = _inputs_hash(inputs)
    if st.session_state.get("_insights_hash") != current_hash:
        st.session_state.pop("insights_narrative", None)
        st.session_state["_insights_hash"] = current_hash

    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📊 Overview",
        "💰 Income & Cash Flow",
        "🏦 Account Balances",
        "📋 Year-by-Year Detail",
        "💡 Insights",
        "📉 Sensitivity",
        "🔑 Bridge Strategies",
    ])

    with tab1:
        render_overview(df, inputs)
    with tab2:
        render_income_cashflow(df, inputs)
    with tab3:
        render_account_balances(df)
    with tab4:
        render_detail(df)
    with tab5:
        render_insights(df, snapshots, inputs)
    with tab6:
        render_sensitivity(inputs)
    with tab7:
        render_bridge_strategies(df, inputs)

    with st.sidebar:
        render_chat_panel()
