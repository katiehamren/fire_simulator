"""Plan overview tab."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine.models import SimInputs

from ..formatting import fmt


def render_overview(df: pd.DataFrame, inputs: SimInputs):
    st.header("Plan Overview")
    # Hide the SVG arrow icons from metric delta badges — they're not directional indicators here.
    st.markdown(
        "<style>[data-testid='stMetricDelta'] svg { display: none; }</style>",
        unsafe_allow_html=True,
    )

    user_401k_yr   = inputs.user.birth_year + 60
    spouse_401k_yr = inputs.spouse.birth_year + 60

    # Plan health metrics
    first_insolvent = df[~df["plan_solvent"]]
    solvent_through = (
        first_insolvent["year"].min() - 1
        if not first_insolvent.empty
        else df["year"].max()
    )
    fully_solvent = solvent_through == df["year"].max()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "User stops W2", str(inputs.user.w2_stop_year),
        f"Age {inputs.user.w2_stop_year - inputs.user.birth_year}",
        delta_color="off",
    )
    col2.metric(
        "Spouse stops W2", str(inputs.spouse.w2_stop_year),
        f"Age {inputs.spouse.w2_stop_year - inputs.spouse.birth_year}",
        delta_color="off",
    )
    col3.metric(
        "401k access opens", f"~{min(user_401k_yr, spouse_401k_yr)}",
        f"{min(user_401k_yr, spouse_401k_yr) - inputs.user.w2_stop_year} yrs after User's W2 stop",
        delta_color="off",
    )
    if fully_solvent:
        col4.metric("Plan solvent through", str(solvent_through), "✅ Full period")
    else:
        col4.metric("Plan solvent through", str(solvent_through), "⚠️ Runs short", delta_color="inverse")

    # Bridge period summary
    bridge_start = inputs.user.w2_stop_year
    bridge_end   = min(user_401k_yr, spouse_401k_yr)
    bridge_df    = df[(df["year"] >= bridge_start) & (df["year"] < bridge_end)]

    c1, c2, c3 = st.columns(3)
    peak = df.loc[df["total_net_worth"].idxmax()]
    c1.metric("Peak net worth", fmt(peak["total_net_worth"]), f"Year {int(peak['year'])}", delta_color="off")
    c2.metric(f"Net worth in {inputs.end_year}", fmt(df.iloc[-1]["total_net_worth"]))

    if not bridge_df.empty:
        total_deficit = bridge_df[bridge_df["net_cashflow"] < 0]["net_cashflow"].sum()
        bridge_covered = total_deficit >= 0
        c3.metric(
            f"Bridge-period deficit ({bridge_start}–{bridge_end})",
            fmt(abs(total_deficit)) if total_deficit < 0 else "$0",
            "Covered by savings" if bridge_covered else "Draw from accounts",
            delta_color="off" if bridge_covered else "inverse",
        )

    st.divider()

    real_mode = st.checkbox(
        "Show inflation-adjusted (today's dollars)",
        value=False, key="overview_real",
        help=f"Divides all values by cumulative inflation ({inputs.assumptions.inflation_rate:.1%}/yr). "
             "Makes future dollars comparable to today's purchasing power.",
    )
    _scale = lambda col: df[col] / df["inflation_factor"] if real_mode else df[col]
    _ytitle = "Value (today's $)" if real_mode else "Value (nominal $)"

    # Net Worth chart
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["year"], y=_scale("total_net_worth"),
        name="Total Net Worth", fill="tozeroy",
        line=dict(color="#2563eb", width=2.5),
        fillcolor="rgba(37,99,235,0.08)",
    ))
    fig.add_trace(go.Scatter(
        x=df["year"], y=_scale("total_retirement_accounts"),
        name="Retirement Accounts (401k/IRA)",
        line=dict(color="#16a34a", width=1.8, dash="dot"),
    ))
    fig.add_trace(go.Scatter(
        x=df["year"], y=_scale("total_liquid_non_retirement"),
        name="Liquid (Brokerage + Cash + HSA)",
        line=dict(color="#f59e0b", width=1.8, dash="dot"),
    ))

    # Key event lines
    events = [
        (inputs.user.w2_stop_year,  "User stops W2",      "#ef4444"),
        (inputs.spouse.w2_stop_year, "Spouse stops W2",   "#f97316"),
        (user_401k_yr,               "User 401k access",  "#16a34a"),
        (spouse_401k_yr,             "Spouse 401k access", "#059669"),
    ]
    yr_min, yr_max = df["year"].min(), df["year"].max()
    for yr, label, color in events:
        if yr_min <= yr <= yr_max:
            fig.add_vline(
                x=yr, line_dash="dash", line_color=color, opacity=0.55,
                annotation_text=label, annotation_position="top right",
                annotation_font_size=11,
            )

    fig.update_layout(
        title="Net Worth Over Time" + (" (inflation-adjusted)" if real_mode else " (nominal)"),
        xaxis_title="Year", yaxis_title=_ytitle,
        yaxis_tickformat="$,.0f", height=440,
        legend=dict(orientation="h", y=-0.22),
        margin=dict(t=50),
    )
    st.plotly_chart(fig, width="stretch")

    # Healthcare / MAGI chart (only meaningful when off employer plans)
    off_employer = df[~df["on_employer_healthcare"]]
    if not off_employer.empty and inputs.assumptions.healthcare_mode == "aca":
        st.subheader("Healthcare: MAGI & ACA Premiums")

        fig_hc = go.Figure()

        fig_hc.add_trace(go.Bar(
            x=off_employer["year"],
            y=off_employer["aca_subsidy"],
            name="ACA Subsidy (PTC)",
            marker_color="#16a34a",
            opacity=0.7,
        ))
        fig_hc.add_trace(go.Bar(
            x=off_employer["year"],
            y=off_employer["aca_premium"],
            name="Premium You Pay",
            marker_color="#ef4444",
            opacity=0.7,
        ))
        fig_hc.add_trace(go.Scatter(
            x=off_employer["year"],
            y=off_employer["magi"],
            name="MAGI",
            yaxis="y2",
            line=dict(color="#2563eb", width=2),
        ))

        # 400% FPL reference line
        fpl_2025 = 20_440
        fpl_growth = 0.02
        fpl_400 = [
            fpl_2025 * (1 + fpl_growth) ** max(0, yr - 2025) * 4
            for yr in off_employer["year"]
        ]
        fig_hc.add_trace(go.Scatter(
            x=off_employer["year"],
            y=fpl_400,
            name="400% FPL",
            yaxis="y2",
            line=dict(color="#f59e0b", width=1.5, dash="dash"),
        ))

        fig_hc.update_layout(
            barmode="stack",
            xaxis_title="Year",
            yaxis=dict(title="Annual Cost ($)", tickformat="$,.0f"),
            yaxis2=dict(
                title="MAGI ($)", tickformat="$,.0f",
                overlaying="y", side="right",
            ),
            height=380,
            legend=dict(orientation="h", y=-0.25),
            margin=dict(t=30),
        )
        st.plotly_chart(fig_hc, width="stretch")

        hsa_total = off_employer["hsa_for_healthcare"].sum()
        if hsa_total > 0:
            st.caption(
                f"HSA covered **{fmt(hsa_total)}** in healthcare costs over "
                f"{len(off_employer)} off-employer years (tax-free)."
            )

        st.divider()

    # Warnings
    early = df[df["early_withdrawal_amount"] > 0]
    if not early.empty:
        total_early = early["early_withdrawal_amount"].sum()
        yrs = early["year"].tolist()
        st.warning(
            f"⚠️ **Early retirement account withdrawals** in {len(early)} year(s) "
            f"({yrs[0]}–{yrs[-1]}, total: `{fmt(total_early)}`). "
            f"These trigger a 10% IRS penalty. "
            f"Use the **🔑 Bridge Strategies** sidebar section to enable a Roth conversion ladder "
            f"or SEPP/72(t) plan to eliminate this."
        )

    if not fully_solvent:
        st.error(
            f"❌ **Plan runs out of money in {solvent_through + 1}.** "
            f"Adjust spending, retirement dates, or contribution rates."
        )
