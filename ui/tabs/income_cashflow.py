"""Income and cash flow tab."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from engine.models import SimInputs


def render_income_cashflow(df: pd.DataFrame, inputs: SimInputs):
    st.header("Income & Cash Flow")

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        subplot_titles=("Income by Source vs. Expenses", "Annual Surplus / Deficit"),
        vertical_spacing=0.14, row_heights=[0.6, 0.4],
    )

    # Stacked income bars
    income_series = [
        ("user_w2_gross",    "User W2 (gross)",     "#3b82f6"),
        ("spouse_w2_gross",  "Spouse W2 (gross)",   "#1d4ed8"),
        ("sole_prop_net",     "Sole Prop (net)",       "#10b981"),
        ("rental_cashflow",   "Rental Cash Flow",      "#8b5cf6"),
    ]
    for col, label, color in income_series:
        fig.add_trace(go.Bar(
            x=df["year"], y=df[col].clip(lower=0),
            name=label, marker_color=color, legendgroup="income",
        ), row=1, col=1)

    # Expense lines
    fig.add_trace(go.Scatter(
        x=df["year"], y=df["total_expenses"], name="Total Expenses",
        line=dict(color="#ef4444", width=2.5), legendgroup="expenses",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df["year"], y=df["healthcare"], name="Healthcare (excl. from spending)",
        line=dict(color="#fca5a5", width=1.5, dash="dot"), legendgroup="expenses",
    ), row=1, col=1)

    # Surplus/deficit bars
    colors = ["#16a34a" if v >= 0 else "#dc2626" for v in df["net_cashflow"]]
    fig.add_trace(go.Bar(
        x=df["year"], y=df["net_cashflow"], name="Net Cash Flow",
        marker_color=colors, showlegend=False,
    ), row=2, col=1)
    fig.add_hline(y=0, line_color="black", line_width=1, row=2, col=1)

    fig.update_layout(
        barmode="stack", height=620,
        xaxis2_title="Year",
        yaxis_tickformat="$,.0f",
        yaxis2_tickformat="$,.0f",
        legend=dict(orientation="h", y=-0.18),
        margin=dict(t=60),
    )
    st.plotly_chart(fig, width="stretch")

    st.info(
        "ℹ️ **Tax note:** Income is taxed using 2025 federal progressive brackets (MFJ) "
        "with the standard deduction applied. Rental cash flow is NOI (not subject to "
        "income tax in this model). Healthcare cost appears only when neither person has a W2."
    )
