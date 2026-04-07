"""Sensitivity analysis tab."""
import copy

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine.models import SimInputs
from engine.simulator import run_simulation

from ..formatting import fmt, to_df


def render_sensitivity(base_inputs: SimInputs):
    st.header("Sensitivity Analysis")
    st.caption(
        "Reruns the full simulation at return rates from −2% to +2% around your base assumption. "
        "Shows how much plan outcomes depend on long-term market performance."
    )

    base_rate = base_inputs.assumptions.market_return_rate

    offsets = [-0.02, -0.01, 0.0, +0.01, +0.02]
    colors  = ["#dc2626", "#f97316", "#2563eb", "#16a34a", "#059669"]

    with st.spinner("Running sensitivity scenarios…"):
        results = []
        for offset in offsets:
            inp = copy.deepcopy(base_inputs)
            inp.assumptions.market_return_rate = max(0.005, base_rate + offset)
            df  = to_df(run_simulation(inp), inp.assumptions.inflation_rate)
            label = f"{inp.assumptions.market_return_rate:.1%}"
            results.append((label, df, offset == 0.0))

    # ── Summary table ─────────────────────────────────────────────────────────
    st.subheader("Key Metrics Across Return Rates")
    final_year = results[0][1]["year"].max()
    rows = []
    for label, df, is_base in results:
        first_bad = df[~df["plan_solvent"]]
        solvent_through = first_bad["year"].min() - 1 if not first_bad.empty else final_year
        fully_solvent   = solvent_through == final_year
        rows.append({
            "Return Rate": ("▶ " if is_base else "  ") + label,
            "Solvent Through":  "Full period" if fully_solvent else str(int(solvent_through)),
            "Peak Net Worth":   df["total_net_worth"].max(),
            f"Net Worth {final_year}": df.iloc[-1]["total_net_worth"],
            "Early Withdrawals": df["early_withdrawal_amount"].sum(),
        })

    summary_df = pd.DataFrame(rows).set_index("Return Rate")
    money_cols = ["Peak Net Worth", f"Net Worth {final_year}", "Early Withdrawals"]

    def _color_solvency(val):
        if val == "Full period":
            return "color: #16a34a; font-weight: bold"
        try:
            int(val.strip())
            return "color: #dc2626; font-weight: bold"
        except ValueError:
            return ""

    st.dataframe(
        summary_df.style
            .format({c: "${:,.0f}" for c in money_cols})
            .map(_color_solvency, subset=["Solvent Through"]),
        width="stretch",
    )

    st.divider()

    # ── Net Worth fan chart ───────────────────────────────────────────────────
    fig = go.Figure()
    for i, (label, df, is_base) in enumerate(results):
        fig.add_trace(go.Scatter(
            x=df["year"], y=df["total_net_worth"],
            name=f"{label} return",
            line=dict(color=colors[i], width=3 if is_base else 1.5,
                      dash="solid" if is_base else "dot"),
        ))
    fig.update_layout(
        title=f"Net Worth — Return Rate Sensitivity (base: {base_rate:.1%})",
        xaxis_title="Year", yaxis_title="Net Worth (nominal $)",
        yaxis_tickformat="$,.0f", height=420,
        legend=dict(orientation="h", y=-0.22), margin=dict(t=50),
    )
    st.plotly_chart(fig, width="stretch")

    # ── Cash flow fan chart ───────────────────────────────────────────────────
    fig2 = go.Figure()
    for i, (label, df, is_base) in enumerate(results):
        fig2.add_trace(go.Scatter(
            x=df["year"], y=df["net_cashflow"],
            name=f"{label} return",
            line=dict(color=colors[i], width=2.5 if is_base else 1.5,
                      dash="solid" if is_base else "dot"),
        ))
    fig2.add_hline(y=0, line_color="black", line_width=1)
    fig2.update_layout(
        title="Annual Cash Flow Sensitivity",
        xaxis_title="Year", yaxis_title="Cash Flow ($)",
        yaxis_tickformat="$,.0f", height=320,
        legend=dict(orientation="h", y=-0.30), margin=dict(t=50),
    )
    st.plotly_chart(fig2, width="stretch")

    st.caption(
        f"Base return: **{base_rate:.1%}** (▶ in table above). "
        "The spread between bands widens over time — compounding amplifies small differences in assumed return. "
        "If the plan only works at optimistic returns, that's a risk worth planning around."
    )
