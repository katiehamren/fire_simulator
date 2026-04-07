"""Account balances tab."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..formatting import COLORS


def render_account_balances(df: pd.DataFrame):
    st.header("Account Balances Over Time")

    account_series = [
        ("hsa",                  "HSA"),
        ("cash",                 "Cash"),
        ("brokerage",            "Taxable Brokerage"),
        ("spouse_roth_ira",     "Spouse Roth IRA"),
        ("spouse_trad_ira",     "Spouse Trad IRA"),
        ("spouse_401k_roth",    "Spouse 401(k) Roth"),
        ("spouse_401k_pretax",  "Spouse 401(k) Pre-tax"),
        ("user_roth_ira",       "User Roth IRA"),
        ("user_trad_ira",       "User Trad IRA"),
        ("user_401k_roth",      "User 401(k) Roth"),
        ("user_401k_pretax",    "User 401(k) Pre-tax"),
    ]

    fig = go.Figure()
    for col, label in account_series:
        fig.add_trace(go.Scatter(
            x=df["year"], y=df[col],
            name=label, stackgroup="one",
            mode="lines",
            line=dict(width=0.5, color=COLORS.get(col, "#888888")),
            fillcolor=COLORS.get(col, "#888888"),
        ))

    fig.update_layout(
        title="All Accounts (Stacked)",
        xaxis_title="Year", yaxis_title="Balance ($)",
        yaxis_tickformat="$,.0f", height=500,
        legend=dict(orientation="h", y=-0.35, font=dict(size=11)),
        margin=dict(b=160),
    )
    st.plotly_chart(fig, width="stretch")

    # Accessibility breakdown
    st.subheader("Accessible vs. Locked Assets")
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=df["year"], y=df["total_liquid_non_retirement"],
        name="Accessible Now (brokerage, cash, HSA)",
        fill="tozeroy", line=dict(color="#f59e0b", width=2),
        fillcolor="rgba(245,158,11,0.15)",
    ))
    fig2.add_trace(go.Scatter(
        x=df["year"], y=df["total_net_worth"],
        name="Total Net Worth",
        line=dict(color="#2563eb", width=2, dash="dot"),
    ))
    fig2.update_layout(
        xaxis_title="Year", yaxis_title="Value ($)",
        yaxis_tickformat="$,.0f", height=320,
        legend=dict(orientation="h", y=-0.25),
    )
    st.plotly_chart(fig2, width="stretch")
    st.caption(
        "The gap between the two lines is your retirement accounts (401k/IRA) — "
        "locked until ~59.5 without penalty. Planning the bridge period is about ensuring "
        "the orange area is large enough to cover expenses until the locked accounts open up."
    )
