"""
Early Retirement Simulator — Streamlit web app.

Run with:  streamlit run app.py

Key simplifications in v1:
- Federal tax from progressive MFJ brackets (config) on W2 + sole prop income
- Roth IRA fully accessible for withdrawals (real rule: contributions only pre-59.5)
- No Social Security modeling
- No Roth conversion ladder optimization (Phase 2)
- Healthcare cost is a flat annual input; user should tune to their ACA/MAGI situation
"""
import chatbot.env  # noqa: F401 — load .env into os.environ before other imports

import copy
import hashlib
import io
import json
import re
from datetime import datetime
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from engine.models import (
    CURRENT_YEAR, PersonInfo, W2Income, SolePropIncome, RentalProperty,
    AccountBalances, AnnualContributions, Assumptions, SimInputs,
    RothConversionPlan, SEPPPlan, SpendingOverride,
)
from engine.simulator import run_simulation, _compute_w2_401k
from engine.tax_calc import compute_federal_tax
from engine.insights import compute_all_insights
from scenarios.defaults import PRESETS
from chatbot.ui import render_chat_panel

# ── SCENARIO MANAGEMENT ──────────────────────────────────────────────────────

SAVED_DIR = Path(__file__).parent / "saved_scenarios"

# All sidebar widget keys that represent simulation inputs (excludes UI-only keys).
SCENARIO_KEYS = [
    "u_birth", "u_stop", "s_birth", "s_stop", "end_yr",
    "u_w2", "u_raise", "s_w2", "s_raise",
    "sp_net", "sp_gr", "sp_years",
    "rrent", "rrg", "rvac", "rexp",
    "u401p", "u401r", "utira", "urira",
    "s401p", "s401r", "stira", "srira",
    "brok", "hsa", "cash_bal",
    "uirac", "sirac", "brokc",
    "solo_ee", "solo_ee_type", "solo_er_pct", "solo_er_type",
    "mret_preset", "mret", "inf", "spend", "hccost",
    "spend_override_enabled", "spend_override_year", "spend_override_pct",
    "rc_enabled", "rc_start", "rc_end", "rc_amount", "rc_source",
    "sepp_enabled", "sepp_start", "sepp_account", "sepp_rate",
]


def _slug(name: str) -> str:
    """Convert a scenario name to a safe filename stem."""
    return re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "_")


def list_saved() -> list[str]:
    SAVED_DIR.mkdir(exist_ok=True)
    names = []
    for p in sorted(SAVED_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            names.append(data.get("name", p.stem))
        except Exception:
            pass
    return names


def _json_default(obj):
    """Convert numpy scalars (returned by Streamlit widgets) to JSON-native types."""
    if hasattr(obj, 'item'):   # numpy scalar → Python int/float/bool
        return obj.item()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def save_scenario(name: str) -> None:
    SAVED_DIR.mkdir(exist_ok=True)
    payload = {
        "name": name,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": {k: st.session_state[k] for k in SCENARIO_KEYS if k in st.session_state},
    }
    (SAVED_DIR / f"{_slug(name)}.json").write_text(json.dumps(payload, indent=2, default=_json_default))


def load_saved(name: str) -> dict:
    for p in SAVED_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            if data.get("name") == name:
                return data["inputs"]
        except Exception:
            pass
    return {}


def delete_saved(name: str) -> None:
    for p in SAVED_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            if data.get("name") == name:
                p.unlink()
                return
        except Exception:
            pass


def apply_inputs(inputs: dict) -> None:
    """Load a dict of widget key→value into session state and rerun.

    Only keys in SCENARIO_KEYS are applied so obsolete keys (e.g. legacy taxr)
    in older saved JSON are ignored.
    """
    st.session_state.update({k: v for k, v in inputs.items() if k in SCENARIO_KEYS})
    st.rerun()


# ── INPUT VALIDATION ─────────────────────────────────────────────────────────

_401K_LIMIT_2026 = 23_500   # IRS employee elective deferral limit
_IRA_LIMIT_2026  =  7_000   # IRA annual contribution limit (under 50)

def validate_inputs(inputs: SimInputs) -> list[tuple[str, str]]:
    """Return (level, message) pairs — level is 'error' or 'warning'."""
    issues: list[tuple[str, str]] = []
    # Dollar signs in Streamlit markdown trigger LaTeX parsing; wrap amounts in backticks.
    m = lambda n: f"`{fmt(n)}`"

    # ── 401(k) shortfall check ───────────────────────────────────────────────
    # Estimate year-0 surplus after 401k, IRAs, solo Roth contributions, and expenses.
    # If negative, the contribution assumptions leave the household short of cash.
    _k_w2_0  = inputs.user_w2.gross_annual   if inputs.user.w2_stop_year   > CURRENT_YEAR else 0.0
    _h_w2_0  = inputs.spouse_w2.gross_annual if inputs.spouse.w2_stop_year > CURRENT_YEAR else 0.0
    _sp_0    = inputs.sole_prop.net_annual
    _lim_0   = float(_401K_LIMIT_2026)
    _k401_0  = _compute_w2_401k(
        inputs.contributions.user_401k_mode,
        inputs.contributions.user_401k_amount,
        inputs.contributions.user_401k_pct,
        _k_w2_0, int(_lim_0),
    )
    _h401_0  = _compute_w2_401k(
        inputs.contributions.spouse_401k_mode,
        inputs.contributions.spouse_401k_amount,
        inputs.contributions.spouse_401k_pct,
        _h_w2_0, int(_lim_0),
    )

    _ee = min(inputs.contributions.user_solo_401k_ee, _lim_0, _sp_0) if _sp_0 > 0 else 0.0
    _er = min(inputs.contributions.user_solo_401k_er_pct * _sp_0,
              max(0.0, 70_000 - _ee)) if _sp_0 > 0 else 0.0
    _ee_pretax = 0.0 if inputs.contributions.user_solo_401k_ee_type == "roth" else _ee
    _ee_roth   = _ee if inputs.contributions.user_solo_401k_ee_type == "roth" else 0.0
    _er_pretax = 0.0 if inputs.contributions.user_solo_401k_er_type == "roth" else _er
    _er_roth   = _er if inputs.contributions.user_solo_401k_er_type == "roth" else 0.0

    _gross_tax_0 = ((_k_w2_0 - _k401_0) + (_h_w2_0 - _h401_0)
                    + _sp_0 - _ee_pretax - _er_pretax)
    _taxes_0 = compute_federal_tax(_gross_tax_0)
    _rent_noi_0 = (inputs.rental.monthly_gross_rent * 12
                   * (1 - inputs.rental.vacancy_rate - inputs.rental.expense_ratio))
    _net_inc_0 = (_gross_tax_0 - _taxes_0) + _rent_noi_0
    _hc_0 = 0.0 if (_k_w2_0 > 0 or _h_w2_0 > 0) else inputs.assumptions.annual_healthcare_off_employer
    _exp_0 = inputs.assumptions.annual_spending_today + _hc_0
    _k_has_earned_0 = _k_w2_0 > 0 or _sp_0 > 0
    _ira_0 = ((inputs.contributions.user_ira if _k_has_earned_0 else 0.0)
              + (inputs.contributions.spouse_ira if _h_w2_0 > 0 else 0.0))
    _surplus_0 = _net_inc_0 - _exp_0 - _ira_0 - _ee_roth - _er_roth

    if _surplus_0 < 0:
        issues.append(("warning",
            f"401(k) contributions create an estimated **year-1 cash shortfall of "
            f"{m(-_surplus_0)}.** "
            "Income after contributions and expenses is negative — the plan will draw from "
            "savings immediately. Consider reducing contributions, IRAs, or "
            "checking your spending assumption."))

    # IRA contribution above IRS limit
    if inputs.contributions.user_ira > _IRA_LIMIT_2026:
        issues.append(("warning",
            f"User's IRA contribution ({m(inputs.contributions.user_ira)}/yr) exceeds "
            f"the {CURRENT_YEAR} annual IRA limit ({m(_IRA_LIMIT_2026)}). "
            "Over-contributions face a 6% annual excise tax."))
    if inputs.contributions.spouse_ira > _IRA_LIMIT_2026:
        issues.append(("warning",
            f"Spouse's IRA contribution ({m(inputs.contributions.spouse_ira)}/yr) exceeds "
            f"the {CURRENT_YEAR} annual IRA limit ({m(_IRA_LIMIT_2026)})."))

    # Simulation window too short
    last_retire = max(inputs.user.w2_stop_year, inputs.spouse.w2_stop_year)
    if inputs.end_year < last_retire + 15:
        issues.append(("warning",
            f"Simulation ends in {inputs.end_year}, only "
            f"{inputs.end_year - last_retire} years after the last W2 stop. "
            f"Consider extending to at least {last_retire + 25} to model late-retirement risk."))

    # W2 stop already passed
    if inputs.user.w2_stop_year <= CURRENT_YEAR:
        issues.append(("warning",
            f"User's W2 stop year ({inputs.user.w2_stop_year}) is in the past — "
            "no W2 income for User will be modeled."))
    if inputs.spouse.w2_stop_year <= CURRENT_YEAR:
        issues.append(("warning",
            f"Spouse's W2 stop year ({inputs.spouse.w2_stop_year}) is in the past — "
            "no W2 income for Spouse will be modeled."))

    return issues


# ── PAGE CONFIG ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Early Retirement Simulator",
    page_icon="🏖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── HELPERS ──────────────────────────────────────────────────────────────────

def fmt(n: float) -> str:
    return f"${n:,.0f}"

def to_df(snapshots, inflation_rate: float = 0.03) -> pd.DataFrame:
    df = pd.DataFrame([vars(s) for s in snapshots])
    df["inflation_factor"] = (1 + inflation_rate) ** (df["year"] - CURRENT_YEAR)
    return df

COLORS = {
    "user_401k_pretax":   "#1e3a5f",
    "user_401k_roth":     "#2563eb",
    "user_trad_ira":      "#0e7490",
    "user_roth_ira":      "#22d3ee",
    "spouse_401k_pretax": "#14532d",
    "spouse_401k_roth":   "#16a34a",
    "spouse_trad_ira":    "#15803d",
    "spouse_roth_ira":    "#4ade80",
    "brokerage":           "#d97706",
    "hsa":                 "#7c3aed",
    "cash":                "#9ca3af",
}

def person_ui_label(internal_key: str) -> str:
    """Display label for internal person keys (`user` / `spouse`) in the UI."""
    return {"user": "User", "spouse": "Spouse"}.get(internal_key, internal_key)


# ── SIDEBAR INPUTS ────────────────────────────────────────────────────────────

def build_inputs() -> SimInputs:
    with st.sidebar:
        st.title("⚙️ Inputs")
        st.caption("Adjust any field — charts update instantly.")

        # ── SCENARIOS ──
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
                f"IRS employee limit: **\\${_401K_LIMIT_2026:,}** in {CURRENT_YEAR}, "
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
                        help=f"Contributed each year, capped at the IRS limit (\\${_401K_LIMIT_2026:,} in {CURRENT_YEAR}) and W2 salary.",
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
                        help=f"Contributed each year, capped at the IRS limit (\\${_401K_LIMIT_2026:,} in {CURRENT_YEAR}) and W2 salary.",
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
                     f"\\${_401K_LIMIT_2026:,} in {CURRENT_YEAR}, growing \\$500/yr.",
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


# ── TAB: OVERVIEW ────────────────────────────────────────────────────────────

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


# ── TAB: INCOME & CASH FLOW ──────────────────────────────────────────────────

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


# ── TAB: ACCOUNT BALANCES ────────────────────────────────────────────────────

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


# ── TAB: YEAR-BY-YEAR DETAIL ─────────────────────────────────────────────────

def render_detail(df: pd.DataFrame):
    st.header("Year-by-Year Detail")

    display_cols = [
        "year", "user_age", "spouse_age",
        "user_w2_gross", "spouse_w2_gross", "sole_prop_net", "rental_cashflow",
        "taxes_paid", "total_net_income",
        "spending", "healthcare", "total_expenses", "net_cashflow",
        "brokerage", "total_retirement_accounts", "total_net_worth",
        "early_withdrawal_amount", "user_rmd", "spouse_rmd", "plan_solvent",
    ]

    col_labels = {
        "year": "Year", "user_age": "User Age", "spouse_age": "Spouse Age",
        "user_w2_gross": "User W2", "spouse_w2_gross": "Spouse W2",
        "sole_prop_net": "Sole Prop", "rental_cashflow": "Rental CF",
        "taxes_paid": "Taxes", "total_net_income": "Net Income",
        "spending": "Spending", "healthcare": "Healthcare",
        "total_expenses": "Expenses", "net_cashflow": "Cash Flow",
        "brokerage": "Brokerage", "total_retirement_accounts": "Retirement",
        "total_net_worth": "Net Worth",
        "early_withdrawal_amount": "Early W/D",
        "user_rmd": "User RMD", "spouse_rmd": "Spouse RMD",
        "plan_solvent": "Solvent",
    }

    currency_cols = [
        "user_w2_gross", "spouse_w2_gross", "sole_prop_net", "rental_cashflow",
        "taxes_paid", "total_net_income", "spending", "healthcare", "total_expenses",
        "net_cashflow", "brokerage", "total_retirement_accounts",
        "total_net_worth", "early_withdrawal_amount", "user_rmd", "spouse_rmd",
    ]

    display_df = df[display_cols].copy()
    display_df.rename(columns=col_labels, inplace=True)

    def highlight(row):
        if not row["Solvent"]:
            return ["background-color: #fee2e2; color: #991b1b"] * len(row)
        if row["User RMD"] > 0 or row["Spouse RMD"] > 0:
            return ["background-color: #ede9fe; color: #5b21b6"] * len(row)
        if row["Early W/D"] > 0:
            return ["background-color: #fef9c3; color: #854d0e"] * len(row)
        return [""] * len(row)

    format_map = {col_labels[c]: "${:,.0f}" for c in currency_cols}

    styled = (
        display_df.style
        .apply(highlight, axis=1)
        .format(format_map, na_rep="—")
    )

    st.dataframe(styled, width="stretch", height=520)
    st.caption(
        "🟡 Yellow row = early retirement account withdrawal (10% IRS penalty applies). "
        "🟣 Purple row = RMD year (mandatory withdrawal from pre-tax accounts at age 73+). "
        "🔴 Red row = plan insolvency (expenses exceed all available assets)."
    )

    st.divider()
    st.subheader("Export")
    col_csv, col_xlsx = st.columns(2)

    csv_bytes = display_df.to_csv(index=False).encode("utf-8")
    col_csv.download_button(
        "Download CSV",
        data=csv_bytes,
        file_name="retirement_simulation.csv",
        mime="text/csv",
        width="stretch",
    )

    xlsx_buf = io.BytesIO()
    with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
        display_df.to_excel(writer, index=False, sheet_name="Simulation")
    col_xlsx.download_button(
        "Download Excel",
        data=xlsx_buf.getvalue(),
        file_name="retirement_simulation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )


# ── TAB: INSIGHTS ────────────────────────────────────────────────────────────

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
        st.info(
            f"Investment returns first exceed annual expenses in **{fi['year']}**. "
            "After this point, the portfolio can sustain spending from growth alone "
            "without drawing down principal."
        )
    else:
        st.warning(
            "Investment returns never fully cover annual expenses in this plan. "
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
    )
    c2.metric("Avg annual drawdown", fmt(abs(bb["avg_annual_deficit"])))
    c3.metric(
        "Liquid assets consumed",
        f"{bb['pct_liquid_consumed']:.0f}%",
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


# ── TAB: SENSITIVITY ANALYSIS ────────────────────────────────────────────────

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


# ── TAB: BRIDGE STRATEGIES ───────────────────────────────────────────────────

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
                "For example, a $50,000 conversion in 2029 produces $50,000 of accessible Roth principal "
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
            conv_table["conversion_tax"] = conv_table.apply(
                lambda row: compute_federal_tax(
                    _gross_by_year[row["year"]] + row["roth_conversion_amount"]
                )
                - compute_federal_tax(_gross_by_year[row["year"]]),
                axis=1,
            )
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


def _inputs_hash(inputs: SimInputs) -> str:
    """Quick hash of inputs to detect sidebar changes."""
    return hashlib.md5(str(inputs).encode()).hexdigest()


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    inputs = build_inputs()

    # Validation — shown above the tabs so they're always visible
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


if __name__ == "__main__":
    main()
