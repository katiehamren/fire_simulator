"""Bridge strategies (Roth ladder, SEPP) tab."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine.models import SimInputs
from engine.tax_calc import compute_federal_tax

from ..formatting import fmt, person_ui_label


def render_bridge_strategies(df: pd.DataFrame, inputs: SimInputs):
    st.header("Bridge Strategies")
    st.caption(
        "Models Roth conversion ladder and SEPP/72(t) — the two main tools for accessing "
        "pre-tax retirement funds before age 59½ without penalty. Enable either (or both) "
        "in the **🔑 Bridge Strategies** sidebar section."
    )

    rc = inputs.roth_conversion
    sepp = inputs.sepp

    any_active = rc.enabled or sepp.enabled
    if not any_active:
        st.info(
            "No bridge strategies are enabled. Open the **🔑 Bridge Strategies** sidebar section "
            "to configure a Roth conversion ladder and/or SEPP plan."
        )
        return

    # ── Roth Conversion Ladder ────────────────────────────────────────────────
    if rc.enabled:
        st.subheader("Roth Conversion Ladder")

        conv_df = df[df["roth_conversion_amount"] > 0].copy()
        total_converted = conv_df["roth_conversion_amount"].sum()
        first_seasoned_yr = rc.start_year + 5
        seasoned_by_end = df.iloc[-1]["accessible_roth_seasoned"] if not df.empty else 0

        c1, c2, c3 = st.columns(3)
        c1.metric("Conversion window", f"{rc.start_year}–{rc.end_year}")
        c2.metric("Total converted", fmt(total_converted))
        c3.metric("First accessible batch", str(first_seasoned_yr))

        # Timeline chart: conversions + when they season
        fig = go.Figure()

        # Conversion bars
        fig.add_trace(go.Bar(
            x=df["year"], y=df["roth_conversion_amount"],
            name="Annual conversion (pre-tax → Roth)",
            marker_color="#2563eb", opacity=0.8,
        ))

        # Accessible seasoned Roth (cumulative)
        fig.add_trace(go.Scatter(
            x=df["year"], y=df["accessible_roth_seasoned"],
            name="Cumulative seasoned Roth (accessible without penalty)",
            line=dict(color="#16a34a", width=2.5),
            yaxis="y2",
        ))

        # Roth IRA total balance
        fig.add_trace(go.Scatter(
            x=df["year"], y=df["user_roth_ira"] + df["spouse_roth_ira"],
            name="Total Roth IRA balance",
            line=dict(color="#22d3ee", width=1.8, dash="dot"),
            yaxis="y2",
        ))

        # Vline when first seasoning
        yr_min = int(df["year"].min())
        yr_max = int(df["year"].max())
        if yr_min <= first_seasoned_yr <= yr_max:
            fig.add_vline(
                x=first_seasoned_yr, line_dash="dash", line_color="#16a34a", opacity=0.6,
                annotation_text=f"First batch accessible ({first_seasoned_yr})",
                annotation_position="top right", annotation_font_size=11,
            )

        fig.update_layout(
            title=f"Roth Conversion Ladder — {person_ui_label(rc.source)}'s pre-tax accounts",
            xaxis_title="Year",
            yaxis=dict(title="Annual Conversion ($)", tickformat="$,.0f"),
            yaxis2=dict(
                title="Cumulative / Balance ($)", tickformat="$,.0f",
                overlaying="y", side="right",
            ),
            height=420,
            legend=dict(orientation="h", y=-0.28),
            margin=dict(t=50),
        )
        st.plotly_chart(fig, width="stretch")

        # Explain the 5-year rule
        with st.expander("How the 5-year seasoning rule works", expanded=False):
            st.markdown(
                "Each Roth conversion starts its own **5-year clock**. "
                "The *converted principal* (not earnings) becomes accessible penalty-free "
                "once 5 years have passed since that conversion year. "
                r"For example, a \$50,000 conversion in 2029 produces \$50,000 of accessible Roth principal "
                "starting in 2034.\n\n"
                "This simulator tracks only converted principal. Roth earnings remain locked until "
                "age 59½ (or are subject to a 10% penalty). Existing Roth IRA contributions "
                "(basis) are always accessible — not modeled here as that depends on your basis tracking."
            )

        # Conversion tax impact table
        if not conv_df.empty:
            st.subheader("Year-by-Year Conversion Detail")
            conv_table = conv_df[["year", "roth_conversion_amount", "accessible_roth_seasoned"]].copy()
            _gross_by_year = df.set_index("year")["gross_taxable_income"]
            _inf = inputs.assumptions.inflation_rate

            def _conv_tax_row(row):
                y = int(row["year"])
                g = _gross_by_year[row["year"]]
                return (
                    compute_federal_tax(g + row["roth_conversion_amount"], y, _inf)
                    - compute_federal_tax(g, y, _inf)
                )

            conv_table["conversion_tax"] = conv_table.apply(_conv_tax_row, axis=1)
            # Net cash cost = tax you actually pay out-of-pocket (principal goes into Roth, not lost)
            conv_table["net_cash_cost"] = conv_table["conversion_tax"]
            conv_table = conv_table[["year", "roth_conversion_amount", "conversion_tax",
                                     "net_cash_cost", "accessible_roth_seasoned"]]
            conv_table.columns = [
                "Year", "Converted to Roth ($)",
                "Conversion Tax (marginal)",
                "Net Cash Cost ($)", "Cumul. Seasoned Roth ($)",
            ]
            st.dataframe(
                conv_table.style.format({
                    "Converted to Roth ($)":         "${:,.0f}",
                    "Conversion Tax (marginal)":     "${:,.0f}",
                    "Net Cash Cost ($)":              "${:,.0f}",
                    "Cumul. Seasoned Roth ($)":       "${:,.0f}",
                }),
                width="stretch", hide_index=True,
            )
            st.caption(
                "**Conversion Tax** is the marginal tax on the conversion amount — "
                "the incremental federal income tax from adding the conversion to ordinary income. "
                "This comes from your cash surplus for that year. "
                "The converted principal moves into Roth intact and is not lost. "
                "**Cumulative Seasoned Roth** shows how much converted principal is accessible "
                "without penalty (conversions ≥ 5 years old)."
            )

        st.divider()

    # ── SEPP / 72(t) ─────────────────────────────────────────────────────────
    if sepp.enabled:
        st.subheader("SEPP / 72(t) Plan")

        sepp_df = df[df["sepp_payment"] > 0].copy()
        if sepp_df.empty:
            st.info("SEPP is enabled but no payments appear in the simulation range. Check the start year.")
        else:
            first_payment = sepp_df.iloc[0]["sepp_payment"]
            total_sepp = sepp_df["sepp_payment"].sum()
            sepp_years = len(sepp_df)

            person_birth = (inputs.user.birth_year if sepp.account == "user"
                            else inputs.spouse.birth_year)
            sepp_end_yr = max(sepp.start_year + 4, person_birth + 59)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Account", person_ui_label(sepp.account))
            c2.metric("Annual payment", fmt(first_payment))
            c3.metric("Plan ends", str(sepp_end_yr))
            c4.metric("Total distributions", fmt(total_sepp))

            fig2 = go.Figure()
            fig2.add_trace(go.Bar(
                x=sepp_df["year"], y=sepp_df["sepp_payment"],
                name=f"SEPP payment ({person_ui_label(sepp.account)})",
                marker_color="#f59e0b",
            ))
            fig2.update_layout(
                title=f"SEPP annual payment — {person_ui_label(sepp.account)}'s pre-tax accounts",
                xaxis_title="Year", yaxis_title="Payment ($)",
                yaxis_tickformat="$,.0f", height=300,
                legend=dict(orientation="h", y=-0.25),
            )
            st.plotly_chart(fig2, width="stretch")

            with st.expander("How SEPP works", expanded=False):
                st.markdown(
                    f"The **amortization method** divides the account balance (at start year {sepp.start_year}) "
                    f"over a fixed schedule using an assumed interest rate of **{sepp.interest_rate:.1%}**. "
                    f"This produces a fixed annual payment of **{fmt(first_payment)}**.\n\n"
                    f"The plan must continue for the **LATER of** 5 years or until age 59½ "
                    f"(ends {sepp_end_yr} for {person_ui_label(sepp.account)}).\n\n"
                    "SEPP distributions are taxed as ordinary income. No 10% early withdrawal "
                    "penalty applies as long as the plan is not modified or terminated early. "
                    "Breaking the plan before the required end date triggers the 10% penalty "
                    "retroactively on all prior payments."
                )
