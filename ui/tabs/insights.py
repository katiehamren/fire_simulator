"""Insights tab and AI narrative."""
import json

import pandas as pd
import streamlit as st

from engine.insights import compute_all_insights
from engine.models import SimInputs

from ..formatting import fmt


def _generate_narrative(insights: dict, inputs: SimInputs) -> str:
    """Call OpenAI to synthesize insights into a narrative."""
    from openai import OpenAI

    from chatbot.env import resolve_openai_api_key

    key = resolve_openai_api_key(st.session_state.get("openai_key"))
    if not key:
        return "No OpenAI API key available. Set the OPENAI_API_KEY environment variable."

    model = st.session_state.get("chat_model", "gpt-4o").lower()
    client = OpenAI(api_key=key)

    prompt = f"""You are a retirement planning analyst. Given the following computed insights
from a retirement simulation, write a concise (2-3 paragraphs) narrative summary with
actionable observations. Focus on what matters most for early retirement success.

NEVER give specific investment advice or recommend securities. NEVER give specific tax advice.
Frame observations as "this plan shows..." or "consider whether..." rather than "you should...".

Use dollar formatting with commas. Do not use markdown headers — write flowing prose.
Do not use backtick formatting for numbers.

Plan context:
- User stops W2: {inputs.user.w2_stop_year} (age {inputs.user.w2_stop_year - inputs.user.birth_year})
- Spouse stops W2: {inputs.spouse.w2_stop_year} (age {inputs.spouse.w2_stop_year - inputs.spouse.birth_year})
- Annual spending: ${inputs.assumptions.annual_spending_today:,.0f}
- Market return assumption: {inputs.assumptions.market_return_rate:.1%}
- Simulation end year: {inputs.end_year}

Computed insights:
{json.dumps(insights, indent=2, default=str)}
"""

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=800,
    )
    return response.choices[0].message.content.strip()


def render_insights(_df: pd.DataFrame, snapshots, inputs: SimInputs):
    st.header("Insights")
    st.caption(
        "Key metrics computed from your simulation to help identify risks, "
        "opportunities, and optimization windows."
    )

    insights = compute_all_insights(snapshots, inputs)

    # ── 1. Financial Independence Crossover ──
    st.subheader("Financial Independence Crossover")
    fi = insights["fi_crossover"]
    if fi:
        c1, c2, c3 = st.columns(3)
        c1.metric("Returns cover expenses", str(fi["year"]))
        c2.metric("User age", str(fi["user_age"]))
        c3.metric("Spouse age", str(fi["spouse_age"]))
        returns_str = fmt(fi["portfolio_returns"]).replace("$", r"\$")
        expenses_str = fmt(fi["total_expenses"]).replace("$", r"\$")
        st.info(
            f"In **{fi['year']}**, real portfolio returns of **{returns_str}** "
            f"first cover total expenses of **{expenses_str}** (including healthcare). "
            "After this point, the portfolio can sustain spending from growth alone without "
            "drawing down principal — and without W2 income."
        )
    else:
        st.warning(
            "Investment returns never fully cover annual expenses after both W2s stop in this plan. "
            "The portfolio relies on principal drawdown throughout."
        )

    st.divider()

    # ── 2. Bridge Period Burn Rate ──
    st.subheader("Bridge Period")
    bb = insights["bridge_burn"]
    c1, c2, c3 = st.columns(3)
    c1.metric(
        f"Bridge period ({bb['bridge_start']}–{bb['bridge_end']})",
        f"{bb['years']} years",
        delta_color="off",
    )

    avg_cf = bb["avg_annual_cashflow"]
    c2.metric(
        "Avg annual net cashflow",
        fmt(abs(avg_cf)),
        "surplus/yr" if avg_cf >= 0 else "deficit/yr",
        delta_color="off" if avg_cf >= 0 else "inverse",
    )

    pct = bb["liquid_net_change_pct"]
    if pct >= 0:
        c3.metric(
            "Liquid assets at bridge end",
            f"+{pct:.0f}%",
            f"Grew {fmt(bb['liquid_net_change'])}",
            delta_color="off",
        )
    else:
        c3.metric(
            "Liquid assets at bridge end",
            f"{pct:.0f}%",
            f"Consumed {fmt(abs(bb['liquid_net_change']))}",
            delta_color="inverse",
        )

    st.divider()

    # ── 3. Tax Efficiency Windows ──
    st.subheader("Tax Efficiency")
    tw = insights["tax_windows"]
    lt = insights["lifetime_tax"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Lifetime federal tax", fmt(lt["total_tax"]))
    c2.metric(
        f"Accumulation (avg {lt['avg_accumulation_rate']:.1%})",
        fmt(lt["accumulation_tax"]),
    )
    c3.metric(
        f"Drawdown (avg {lt['avg_drawdown_rate']:.1%})",
        fmt(lt["drawdown_tax"]),
    )
    if tw:
        st.info(
            f"Lowest-tax window: **{tw['low_tax_start']}–{tw['low_tax_end']}** "
            f"(avg effective rate {tw['avg_effective_rate']:.1%}). "
            f"Best single year: {tw['lowest_year']} at {tw['lowest_rate']:.1%}. "
            "This is the optimal window for Roth conversions or realizing capital gains."
        )

    st.divider()

    # ── 4. RMD Pressure ──
    st.subheader("RMD Outlook")
    rmd = insights["rmd_pressure"]
    if rmd:
        c1, c2, c3 = st.columns(3)
        c1.metric("RMDs begin", str(rmd["first_rmd_year"]))
        c2.metric("Peak RMD", fmt(rmd["peak_rmd"]), f"Year {rmd['peak_rmd_year']}")
        c3.metric("Peak RMD vs expenses", f"{rmd['peak_rmd_expense_pct']:.0f}%")
        if rmd["exceeds_expenses_year"]:
            st.warning(
                f"RMDs exceed annual expenses starting **{rmd['exceeds_expenses_year']}**. "
                "This creates forced taxable income beyond what you need to spend. "
                "Pre-retirement Roth conversions could reduce this pressure."
            )
    else:
        st.info("No RMDs in this simulation window (neither person reaches age 73).")

    st.divider()

    # ── 5. Income Source Dependency ──
    st.subheader("Income Source Dependency")
    dep = insights["income_dependency"]
    c1, c2 = st.columns(2)

    sp = dep["without_sole_prop"]
    if sp["still_solvent"]:
        c1.metric("Without sole prop", "✅ Solvent", delta_color="off")
        c1.caption(f"Final net worth: {fmt(sp['final_net_worth'])}")
    else:
        c1.metric("Without sole prop", f"❌ Fails {sp['insolvent_year']}", delta_color="off")

    rent = dep["without_rental"]
    if rent["still_solvent"]:
        c2.metric("Without rental income", "✅ Solvent", delta_color="off")
        c2.caption(f"Final net worth: {fmt(rent['final_net_worth'])}")
    else:
        c2.metric("Without rental income", f"❌ Fails {rent['insolvent_year']}", delta_color="off")

    st.divider()

    # ── 6. AI Narrative Summary ──
    st.subheader("AI Summary")
    if st.button("Generate AI Summary", key="gen_insights_summary"):
        with st.spinner("Analyzing your plan..."):
            narrative = _generate_narrative(insights, inputs)
            st.session_state["insights_narrative"] = narrative

    if "insights_narrative" in st.session_state:
        st.markdown(st.session_state["insights_narrative"])
