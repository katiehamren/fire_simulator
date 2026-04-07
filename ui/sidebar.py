"""Streamlit sidebar: collect SimInputs from widgets.

The scenarios block uses :func:`_expand_scenarios`; other expanders can be split the same way
without changing widget ``key=`` values (preserves saved JSON compatibility).
"""
import streamlit as st

from engine.models import (
    CURRENT_YEAR, PersonInfo, W2Income, SolePropIncome, RentalProperty,
    AccountBalances, AnnualContributions, Assumptions, SimInputs,
    RothConversionPlan, SEPPPlan, SpendingOverride,
)
from scenarios.defaults import PRESETS

from .formatting import fmt, person_ui_label
from .scenarios import apply_inputs, list_saved, load_saved, delete_saved, save_scenario
from .validation import K401_EE_LIMIT_2026


def _expand_scenarios() -> None:
    """Preset / saved scenario load and save controls."""
    with st.expander("💾 Scenarios", expanded=False):

        # Presets
        st.markdown("**Presets**")
        preset_names = list(PRESETS.keys())
        selected_preset = st.selectbox(
            "Preset template", preset_names, label_visibility="collapsed", key="preset_select"
        )
        if st.button("Load preset", key="btn_load_preset", width="stretch"):
            apply_inputs(PRESETS[selected_preset])

        st.divider()

        # Saved scenarios
        st.markdown("**Saved scenarios**")
        saved = list_saved()
        if saved:
            selected_saved = st.selectbox(
                "Saved scenario", saved, label_visibility="collapsed", key="saved_select"
            )
            col_load, col_del = st.columns(2)
            if col_load.button("Load", key="btn_load_saved", width="stretch"):
                apply_inputs(load_saved(selected_saved))
            if col_del.button("Delete", key="btn_del_saved", width="stretch"):
                delete_saved(selected_saved)
                st.rerun()
        else:
            st.caption("No saved scenarios yet.")

        st.divider()

        # Save current
        st.markdown("**Save current inputs**")
        if st.session_state.pop("_clear_save_name", False):
            st.session_state["save_name_input"] = ""
        save_name = st.text_input(
            "Scenario name", placeholder='e.g. "User retires 2027, conservative"',
            label_visibility="collapsed", key="save_name_input",
        )
        if msg := st.session_state.pop("_save_success_msg", ""):
            st.success(msg)
        if st.button(
            "Save", key="btn_save", width="stretch",
            disabled=not (save_name or "").strip(),
        ):
            name = save_name.strip()
            save_scenario(name)
            st.session_state["_clear_save_name"] = True
            st.session_state["_save_success_msg"] = f'Saved "{name}"'
            st.rerun()


def build_inputs() -> SimInputs:
    with st.sidebar:
        st.title("⚙️ Inputs")
        st.caption("Adjust any field — charts update instantly.")

        _expand_scenarios()

        # ── PEOPLE ──
        with st.expander("👤 People & Timeline", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**User**")
                user_birth = st.number_input(
                    "Birth year", value=1985, min_value=1950, max_value=2005, key="u_birth",
                    help="Used to compute age at each milestone and determine when 401(k)/IRA accounts become penalty-free (~age 59½).")
                user_stop = st.number_input(
                    "W2 stop year", value=2029, min_value=CURRENT_YEAR, max_value=2055, key="u_stop",
                    help="First calendar year with no W2 paycheck. W2 income and 401(k) contributions stop here.")
                st.caption(f"Age at stop: **{user_stop - user_birth}**")
                st.caption(f"401k unlocks: **~{user_birth + 60}**")
            with col2:
                st.markdown("**Spouse**")
                spouse_birth = st.number_input(
                    "Birth year", value=1983, min_value=1950, max_value=2005, key="s_birth",
                    help="Used to compute age at each milestone and determine when 401(k)/IRA accounts become penalty-free (~age 59½).")
                spouse_stop = st.number_input(
                    "W2 stop year", value=2036, min_value=CURRENT_YEAR, max_value=2055, key="s_stop",
                    help="First calendar year with no W2 paycheck. W2 income and 401(k) contributions stop here.")
                st.caption(f"Age at stop: **{spouse_stop - spouse_birth}**")
                st.caption(f"401k unlocks: **~{spouse_birth + 60}**")

            end_year = st.number_input(
                "Simulate through year", value=2075, min_value=2040, max_value=2090, key="end_yr",
                help="How far out to project. Consider running to late 80s for both.")

        # ── INCOME ──
        with st.expander("💼 W2 Income"):
            st.markdown("**User's W2** *(active until stop year)*")
            k_w2 = st.number_input("Gross salary ($/yr)", value=120_000, step=5_000, key="u_w2")
            k_raise = st.slider("Annual raise", 0.0, 8.0, 3.0, 0.5, format="%.1f%%", key="u_raise",
                                help="Compounding annual salary increase applied each year until W2 stops.") / 100

            st.divider()
            st.markdown("**Spouse's W2** *(active until stop year)*")
            h_w2 = st.number_input("Gross salary ($/yr)", value=150_000, step=5_000, key="s_w2")
            h_raise = st.slider("Annual raise", 0.0, 8.0, 3.0, 0.5, format="%.1f%%", key="s_raise",
                                help="Compounding annual salary increase applied each year until W2 stops.") / 100

        # ── ACCOUNTS ──
        with st.expander("🏦 Account Balances (today)"):
            st.markdown("**User**")
            k_401k_pre = st.number_input("401(k) Pre-tax ($)", value=150_000, step=10_000, key="u401p")
            k_401k_r   = st.number_input("401(k) Roth ($)",    value=0,       step=10_000, key="u401r")
            k_tira     = st.number_input("Traditional IRA ($)", value=0,      step=5_000,  key="utira")
            k_rira     = st.number_input("Roth IRA ($)",       value=30_000,  step=5_000,  key="urira")

            st.markdown("**Spouse**")
            h_401k_pre = st.number_input("401(k) Pre-tax ($)", value=250_000, step=10_000, key="s401p")
            h_401k_r   = st.number_input("401(k) Roth ($)",    value=0,       step=10_000, key="s401r")
            h_tira     = st.number_input("Traditional IRA ($)", value=0,      step=5_000,  key="stira")
            h_rira     = st.number_input("Roth IRA ($)",       value=20_000,  step=5_000,  key="srira")

            st.markdown("**Joint**")
            brokerage  = st.number_input("Taxable Brokerage ($)",   value=100_000, step=10_000, key="brok")
            hsa        = st.number_input("HSA ($)",                  value=15_000,  step=5_000,  key="hsa",
                           help="Health Savings Account. Triple tax-advantaged: contributions pre-tax, growth tax-free, withdrawals tax-free for medical. After 65, withdrawable for any purpose (taxed as ordinary income).")
            cash_bal   = st.number_input("Cash / Emergency Fund ($)", value=50_000, step=5_000,  key="cash_bal")

        # ── CONTRIBUTIONS ──
        with st.expander("📥 Annual Contributions"):
            st.caption(
                f"**W2 401(k)** — active while each person has W2 income. "
                f"IRS employee limit: **\\${K401_EE_LIMIT_2026:,}** in {CURRENT_YEAR}, "
                f"growing \\$500/yr. Contributions are always capped at W2 salary and the IRS limit."
            )

            _MODE_LABELS = {
                "max":     "Max out (IRS limit + $500/yr)",
                "percent": "% of W2 salary",
                "dollar":  "Fixed $ amount",
            }
            _MODE_KEYS = list(_MODE_LABELS.keys())

            col_u, col_s = st.columns(2)
            with col_u:
                st.markdown("**User**")
                u_401k_mode = st.radio(
                    "Contribution mode", _MODE_KEYS,
                    format_func=lambda k: _MODE_LABELS[k],
                    key="u401k_mode",
                )
                if u_401k_mode == "dollar":
                    u_401k_amount = float(st.number_input(
                        "Amount/yr ($)", value=10_000, step=500, min_value=0, key="u401k_amt",
                        help=f"Contributed each year, capped at the IRS limit (\\${K401_EE_LIMIT_2026:,} in {CURRENT_YEAR}) and W2 salary.",
                    ))
                    u_401k_pct = 0.0
                elif u_401k_mode == "percent":
                    u_401k_pct = st.slider(
                        "% of gross W2", 1, 100, 10, 1, format="%d%%", key="u401k_pct",
                    ) / 100.0
                    u_401k_amount = 0.0
                else:
                    u_401k_amount = 0.0
                    u_401k_pct = 0.0

            with col_s:
                st.markdown("**Spouse**")
                s_401k_mode = st.radio(
                    "Contribution mode", _MODE_KEYS,
                    format_func=lambda k: _MODE_LABELS[k],
                    key="s401k_mode",
                )
                if s_401k_mode == "dollar":
                    s_401k_amount = float(st.number_input(
                        "Amount/yr ($)", value=10_000, step=500, min_value=0, key="s401k_amt",
                        help=f"Contributed each year, capped at the IRS limit (\\${K401_EE_LIMIT_2026:,} in {CURRENT_YEAR}) and W2 salary.",
                    ))
                    s_401k_pct = 0.0
                elif s_401k_mode == "percent":
                    s_401k_pct = st.slider(
                        "% of gross W2", 1, 100, 10, 1, format="%d%%", key="s401k_pct",
                    ) / 100.0
                    s_401k_amount = 0.0
                else:
                    s_401k_amount = 0.0
                    s_401k_pct = 0.0

            st.divider()
            st.caption("IRA — while person has earned income (W2 or self-employment):")
            k_ira_c = st.number_input("User IRA/yr ($)",    value=7_000, step=500, key="uirac")
            h_ira_c = st.number_input("Spouse IRA/yr ($)", value=7_000, step=500, key="sirac")

            st.caption("Brokerage — from surplus after expenses:")
            brok_c = st.number_input("Brokerage/yr ($)", value=20_000, step=5_000, key="brokc",
                                      help="Amount to save in taxable brokerage if there is surplus income.")

        # ── SOLE PROP ──
        with st.expander("🏢 Sole Proprietorship", expanded=False):
            st.markdown("**Income**")
            sp_net = st.number_input("Net income ($/yr)", value=40_000, step=5_000, key="sp_net",
                                      help="After business expenses, before income tax.")
            sp_growth = st.slider("Annual growth", -5.0, 20.0, 5.0, 1.0, format="%.1f%%", key="sp_gr") / 100
            sp_years = st.number_input(
                "Years active", value=20, min_value=1, max_value=50, key="sp_years",
                help=f"How many years from {CURRENT_YEAR} the business generates income. "
                     f"Income drops to $0 after this period.",
            )
            st.caption(f"Active through: **{CURRENT_YEAR + int(sp_years) - 1}**")

            st.divider()
            st.markdown("**Solo 401(k)**")
            st.caption(
                "Active as long as sole prop income > $0. "
                "Pre-tax reduces SE taxable income now; Roth grows tax-free and builds "
                "conversion-ladder basis for penalty-free access before 59½."
            )
            solo_ee = st.number_input(
                "Employee deferral/yr ($)", value=0, step=500, key="solo_ee",
                help=f"Employee elective deferral. Same IRS cap as W2 401(k): "
                     f"\\${K401_EE_LIMIT_2026:,} in {CURRENT_YEAR}, growing \\$500/yr.",
            )
            solo_ee_type = st.radio(
                "Employee deferral type", ["pretax", "roth"],
                format_func=lambda x: "Pre-tax Solo 401(k)" if x == "pretax" else "Roth Solo 401(k)",
                horizontal=True, key="solo_ee_type",
                help="Pre-tax: deducted from SE income, reduces taxes now. "
                     "Roth: no deduction, but grows tax-free; builds Roth basis for the conversion ladder.",
            )
            st.divider()
            solo_er_pct = st.slider(
                "Employer profit-sharing (% of net SE income)", 0, 25, 0, 1, format="%d%%",
                key="solo_er_pct",
                help="The 'employer' side of your Solo 401(k) — you-the-business contributing. "
                     "Up to 25% of net SE compensation.",
            )
            solo_er_type = st.radio(
                "Employer contribution type", ["pretax", "roth"],
                format_func=lambda x: "Pre-tax Solo 401(k)" if x == "pretax" else "Roth Solo 401(k) (SECURE 2.0)",
                horizontal=True, key="solo_er_type",
                help="Pre-tax: standard employer profit-sharing (always a business deduction). "
                     "Roth: allowed under SECURE 2.0 Act; taxable in year contributed but grows tax-free.",
            )
            _solo_er_frac = solo_er_pct / 100

        # ── RENTAL ──
        with st.expander("🏠 Rental Property"):
            r_rent      = st.number_input("Monthly gross rent ($)",   value=2_500, step=100, key="rrent",
                           help="Total rent collected before any expenses or vacancy. Grows each year by the rent increase rate.")
            r_rent_grow = st.slider("Annual rent increase", 0.0, 8.0, 3.0, 0.5, format="%.1f%%", key="rrg") / 100
            r_vac       = st.slider("Vacancy rate", 0.0, 20.0, 5.0, 1.0, format="%.1f%%", key="rvac",
                           help="Fraction of the year the unit sits empty. 5% ≈ 18 days/year. Applied to gross rent before expenses.") / 100
            r_exp       = st.slider(
                "Expense ratio (% of gross rent)", 5.0, 60.0, 30.0, 5.0, format="%.0f%%", key="rexp",
                help="Property taxes, insurance, maintenance, management fees — as % of gross rent.",
            ) / 100

        # ── ASSUMPTIONS ──
        with st.expander("📈 Assumptions"):
            st.caption(
                "Federal tax: 2025 MFJ progressive brackets with $31,500 standard deduction. "
                "Edit `engine/tax_brackets.json` to update brackets."
            )
            ret_preset = st.radio(
                "Return rate preset",
                ["Conservative (5%)", "Base (7%)", "Optimistic (9%)", "Custom"],
                index=1, horizontal=True, key="mret_preset",
            )
            _preset_map = {"Conservative (5%)": 5.0, "Base (7%)": 7.0, "Optimistic (9%)": 9.0}
            if ret_preset == "Custom":
                mkt_return = st.slider(
                    "Annual market return", 3.0, 12.0, 7.0, 0.5, format="%.1f%%", key="mret"
                ) / 100
            else:
                mkt_return = _preset_map[ret_preset] / 100
                st.caption(f"Using **{mkt_return:.0%}** annual market return")
            inflation  = st.slider("Annual inflation",     1.0,  6.0, 3.0, 0.5, format="%.1f%%", key="inf")  / 100
            spending   = st.number_input(
                "Annual household spending, today's $ ($)", value=90_000, step=5_000, key="spend",
                help="Does not include healthcare. Will be inflation-adjusted going forward.")
            hc_cost    = st.number_input(
                "Healthcare cost when not on employer plan ($/yr)", value=24_000, step=1_000, key="hccost",
                help="Full health insurance premiums + estimated out-of-pocket. "
                     "Applies in years when neither person has a W2 job. "
                     "Heavily influenced by MAGI — tune this to your ACA scenario.")

            st.divider()
            st.markdown("**Spending change**")
            st.caption(
                "Model a one-time permanent shift in annual spending — e.g. mortgage paid off, "
                "kids finish college, lifestyle inflation. Applied on top of the base spending above."
            )
            spend_override_enabled = st.checkbox(
                "Enable spending change", value=False, key="spend_override_enabled",
            )
            spend_override_year = st.number_input(
                "Starting year", value=CURRENT_YEAR + 10,
                min_value=CURRENT_YEAR, max_value=2080,
                key="spend_override_year", disabled=not spend_override_enabled,
                help="First calendar year the new spending level applies.",
            )
            spend_override_pct = st.slider(
                "Change (%)", -80.0, 100.0, -20.0, 5.0,
                format="%.0f%%", key="spend_override_pct",
                disabled=not spend_override_enabled,
                help="Percentage change relative to the base spending above. "
                     "Negative = spending falls (e.g. mortgage paid off). "
                     "Positive = spending rises (e.g. lifestyle inflation).",
            )
            if spend_override_enabled:
                _new_spend = spending * (1 + spend_override_pct / 100)
                st.caption(
                    f"Spending drops from **{fmt(spending)}/yr** to **{fmt(_new_spend)}/yr** "
                    f"(today's $) starting **{spend_override_year}**."
                    if spend_override_pct < 0 else
                    f"Spending rises from **{fmt(spending)}/yr** to **{fmt(_new_spend)}/yr** "
                    f"(today's $) starting **{spend_override_year}**."
                )

        # ── BRIDGE STRATEGIES ──
        with st.expander("🔑 Bridge Strategies (Roth Ladder & SEPP)", expanded=False):
            st.markdown(
                "These strategies unlock pre-tax retirement funds **before age 59½** without penalty. "
                "Enable one or both to bridge the gap between leaving W2 employment and 401(k) access."
            )

            st.markdown("**Roth Conversion Ladder**")
            st.caption(
                "Convert pre-tax 401k/IRA → Roth IRA each year. Converted principal is accessible "
                "penalty-free after a 5-year seasoning period. Best done in low-income years to "
                "minimize taxes on the conversion."
            )
            rc_enabled = st.checkbox("Enable Roth conversions", value=False, key="rc_enabled")
            rc_start = st.number_input(
                "Conversion start year", value=user_stop, min_value=CURRENT_YEAR, max_value=2060,
                key="rc_start", disabled=not rc_enabled,
            )
            rc_end = st.number_input(
                "Conversion end year", value=min(user_stop + 9, spouse_stop - 1),
                min_value=CURRENT_YEAR, max_value=2070,
                key="rc_end", disabled=not rc_enabled,
            )
            rc_amount = st.number_input(
                "Annual conversion amount ($)", value=50_000, step=5_000, key="rc_amount",
                disabled=not rc_enabled,
                help="Amount to convert per year. Keep in mind: conversions increase taxable income. "
                     "Target an amount that stays within your desired tax bracket.",
            )
            rc_source = st.radio(
                "Convert from", ["user", "spouse"], horizontal=True, key="rc_source",
                format_func=person_ui_label,
                disabled=not rc_enabled,
                help="Whose pre-tax 401k/IRA to draw from for conversions.",
            )
            if rc_enabled:
                seasoning_yr = rc_start + 5
                st.caption(
                    f"First seasoned batch accessible: **{seasoning_yr}** "
                    f"(converting ${rc_amount:,.0f}/yr starting {rc_start})."
                )

            st.divider()
            st.markdown("**SEPP / 72(t)**")
            st.caption(
                "Substantially Equal Periodic Payments — IRS-approved penalty-free withdrawals from "
                "a pre-tax retirement account before 59½. Payment is fixed at plan start (amortization "
                "method) and must continue for 5 years OR until 59½, whichever is later."
            )
            sepp_enabled = st.checkbox("Enable SEPP", value=False, key="sepp_enabled")
            sepp_start = st.number_input(
                "SEPP start year", value=user_stop, min_value=CURRENT_YEAR, max_value=2060,
                key="sepp_start", disabled=not sepp_enabled,
            )
            sepp_account = st.radio(
                "Draw from", ["user", "spouse"], horizontal=True, key="sepp_account",
                format_func=person_ui_label,
                disabled=not sepp_enabled,
                help="SEPP must be tied to a single account owner's retirement accounts.",
            )
            sepp_rate_pct = st.slider(
                "SEPP interest rate", 2.0, 7.0, 4.5, 0.5, format="%.1f%%",
                key="sepp_rate", disabled=not sepp_enabled,
                help="Rate used in the amortization formula (~120% of IRS mid-term AFR). "
                     "Higher rate = larger payment.",
            )
            if sepp_enabled:
                person_birth_yr = user_birth if sepp_account == "user" else spouse_birth
                sepp_end_yr = max(sepp_start + 4, person_birth_yr + 59)
                st.caption(
                    f"SEPP runs through **{sepp_end_yr}** "
                    f"({sepp_end_yr - sepp_start + 1} payments). "
                    f"Payment amount computed at plan start from account balance."
                )

    return SimInputs(
        user=PersonInfo("User", user_birth, user_stop),
        spouse=PersonInfo("Spouse", spouse_birth, spouse_stop),
        user_w2=W2Income(k_w2, k_raise),
        spouse_w2=W2Income(h_w2, h_raise),
        sole_prop=SolePropIncome(sp_net, sp_growth, int(sp_years)),
        rental=RentalProperty(r_rent, r_rent_grow, r_vac, r_exp),
        accounts=AccountBalances(
            k_401k_pre, k_401k_r, k_tira, k_rira,
            h_401k_pre, h_401k_r, h_tira, h_rira,
            brokerage, hsa, cash_bal,
        ),
        contributions=AnnualContributions(
            user_401k_mode=u_401k_mode,
            user_401k_amount=u_401k_amount,
            user_401k_pct=u_401k_pct,
            spouse_401k_mode=s_401k_mode,
            spouse_401k_amount=s_401k_amount,
            spouse_401k_pct=s_401k_pct,
            user_ira=k_ira_c, spouse_ira=h_ira_c, brokerage=brok_c,
            user_solo_401k_ee=float(solo_ee),
            user_solo_401k_ee_type=solo_ee_type,
            user_solo_401k_er_pct=_solo_er_frac,
            user_solo_401k_er_type=solo_er_type,
        ),
        assumptions=Assumptions(mkt_return, inflation, spending, hc_cost),
        end_year=end_year,
        roth_conversion=RothConversionPlan(
            enabled=rc_enabled,
            start_year=int(rc_start),
            end_year=int(rc_end),
            annual_amount=float(rc_amount),
            source=rc_source,
        ),
        sepp=SEPPPlan(
            enabled=sepp_enabled,
            start_year=int(sepp_start),
            account=sepp_account,
            interest_rate=sepp_rate_pct / 100,
        ),
        spending_override=(
            SpendingOverride(
                change_pct=spend_override_pct / 100,
                change_year=int(spend_override_year),
            )
            if spend_override_enabled else None
        ),
    )

