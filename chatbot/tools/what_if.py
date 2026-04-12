"""run_what_if tool + OpenAI schema (Phase 3)."""

from copy import deepcopy

import streamlit as st

from engine.insights import fi_crossover
from engine.models import CURRENT_YEAR, SpendingOverride
from engine.simulator import run_simulation

_WHAT_IF_OVERRIDE_KEYS = frozenset({
    "annual_spending",
    "brokerage_contribution",
    "spending_change_year",
    "spending_change_pct",
    "user_w2_stop_year",
    "spouse_w2_stop_year",
    "user_ira",
    "spouse_ira",
    "market_return_rate",
    "inflation_rate",
    "sole_prop_net",
    "sole_prop_years",
    "rental_monthly_rent",
    "roth_conversion_enabled",
    "roth_conversion_amount",
    "sepp_enabled",
    "healthcare_cost",
    "healthcare_mode",
    "aca_arp_extended",
    "aca_additional_oop",
    "user_solo_401k_ee",
    "user_solo_401k_ee_type",
    "user_solo_401k_er_pct",
    "user_solo_401k_er_type",
    "user_401k_mode",
    "user_401k_amount",
    "user_401k_pct",
    "spouse_401k_mode",
    "spouse_401k_amount",
    "spouse_401k_pct",
    "user_w2_salary",
    "user_w2_raise",
    "spouse_w2_salary",
    "spouse_w2_raise",
    "sole_prop_growth",
    "rental_rent_growth",
    "rental_vacancy",
    "rental_expense_ratio",
    "roth_conversion_start_year",
    "roth_conversion_end_year",
    "roth_conversion_source",
    "sepp_start_year",
    "sepp_account",
    "sepp_interest_rate",
    "simulation_end_year",
    "user_401k_pretax_balance",
    "user_401k_roth_balance",
    "user_trad_ira_balance",
    "user_roth_ira_balance",
    "spouse_401k_pretax_balance",
    "spouse_401k_roth_balance",
    "spouse_trad_ira_balance",
    "spouse_roth_ira_balance",
    "brokerage_balance",
    "hsa_balance",
    "cash_balance",
})

_BALANCE_OVERRIDE_MAP = {
    "user_401k_pretax_balance": "user_401k_pretax",
    "user_401k_roth_balance": "user_401k_roth",
    "user_trad_ira_balance": "user_trad_ira",
    "user_roth_ira_balance": "user_roth_ira",
    "spouse_401k_pretax_balance": "spouse_401k_pretax",
    "spouse_401k_roth_balance": "spouse_401k_roth",
    "spouse_trad_ira_balance": "spouse_trad_ira",
    "spouse_roth_ira_balance": "spouse_roth_ira",
    "brokerage_balance": "brokerage",
    "hsa_balance": "hsa",
    "cash_balance": "cash",
}

_COMPARE_METRICS = frozenset({
    "total_net_worth",
    "peak_net_worth",
    "final_net_worth",
    "solvent_through_year",
    "total_expenses",
    "net_cashflow",
})


def _scenario_metrics(snapshots, inputs=None):
    if not snapshots:
        return {
            "solvent_through_year": None,
            "first_insolvent_year": None,
            "peak_net_worth": None,
            "peak_net_worth_year": None,
            "final_net_worth": None,
            "final_year": None,
            "fi_crossover_year": None,
        }
    solvent_years = [s.year for s in snapshots if s.plan_solvent]
    insolvent_years = [s.year for s in snapshots if not s.plan_solvent]
    peak = max(snapshots, key=lambda s: s.total_net_worth)
    final = snapshots[-1]
    fi_year = None
    if inputs is not None:
        fi = fi_crossover(
            snapshots,
            inputs,
            inputs.assumptions.market_return_rate,
            inputs.assumptions.inflation_rate,
        )
        fi_year = fi["year"] if fi else None
    return {
        "solvent_through_year": max(solvent_years) if solvent_years else None,
        "first_insolvent_year": min(insolvent_years) if insolvent_years else None,
        "peak_net_worth": peak.total_net_worth,
        "peak_net_worth_year": peak.year,
        "final_net_worth": final.total_net_worth,
        "final_year": final.year,
        "fi_crossover_year": fi_year,
    }


def _metric_from_snap(snap, metric: str) -> float:
    if metric == "total_expenses":
        return snap.total_expenses
    if metric == "net_cashflow":
        return snap.net_cashflow
    return snap.total_net_worth


def _apply_what_if_overrides(inp, overrides: dict) -> None:
    o = overrides
    if "annual_spending" in o:
        inp.assumptions.annual_spending_today = float(o["annual_spending"])
    cy = o.get("spending_change_year")
    cp = o.get("spending_change_pct")
    if cy is not None and cp is not None:
        inp.spending_override = SpendingOverride(
            change_pct=float(cp),
            change_year=int(cy),
        )
    elif cp is not None:
        inp.spending_override = SpendingOverride(
            change_pct=float(cp),
            change_year=int(cy) if cy is not None else CURRENT_YEAR,
        )
    if "user_w2_stop_year" in o:
        inp.user.w2_stop_year = int(o["user_w2_stop_year"])
    if "spouse_w2_stop_year" in o:
        inp.spouse.w2_stop_year = int(o["spouse_w2_stop_year"])
    if "brokerage_contribution" in o:
        inp.contributions.brokerage = float(o["brokerage_contribution"])
    if "user_ira" in o:
        inp.contributions.user_ira = float(o["user_ira"])
    if "spouse_ira" in o:
        inp.contributions.spouse_ira = float(o["spouse_ira"])
    if "market_return_rate" in o:
        inp.assumptions.market_return_rate = float(o["market_return_rate"])
    if "inflation_rate" in o:
        inp.assumptions.inflation_rate = float(o["inflation_rate"])
    if "sole_prop_net" in o:
        inp.sole_prop.net_annual = float(o["sole_prop_net"])
    if "sole_prop_years" in o:
        inp.sole_prop.years_active = int(o["sole_prop_years"])
    if "rental_monthly_rent" in o:
        inp.rental.monthly_gross_rent = float(o["rental_monthly_rent"])
    if "roth_conversion_enabled" in o:
        inp.roth_conversion.enabled = bool(o["roth_conversion_enabled"])
    if "roth_conversion_amount" in o:
        inp.roth_conversion.annual_amount = float(o["roth_conversion_amount"])
    if "sepp_enabled" in o:
        inp.sepp.enabled = bool(o["sepp_enabled"])
    if "healthcare_cost" in o:
        inp.assumptions.healthcare_mode = "flat"
        inp.assumptions.annual_healthcare_flat = float(o["healthcare_cost"])
    if "healthcare_mode" in o:
        inp.assumptions.healthcare_mode = str(o["healthcare_mode"])
    if "aca_arp_extended" in o:
        inp.assumptions.aca_arp_extended = bool(o["aca_arp_extended"])
    if "aca_additional_oop" in o:
        inp.assumptions.aca_additional_oop = float(o["aca_additional_oop"])

    if "user_solo_401k_ee" in o:
        inp.contributions.user_solo_401k_ee = float(o["user_solo_401k_ee"])
    if "user_solo_401k_ee_type" in o:
        inp.contributions.user_solo_401k_ee_type = str(o["user_solo_401k_ee_type"])
    if "user_solo_401k_er_pct" in o:
        inp.contributions.user_solo_401k_er_pct = float(o["user_solo_401k_er_pct"])
    if "user_solo_401k_er_type" in o:
        inp.contributions.user_solo_401k_er_type = str(o["user_solo_401k_er_type"])

    if "user_401k_mode" in o:
        inp.contributions.user_401k_mode = str(o["user_401k_mode"])
    if "user_401k_amount" in o:
        inp.contributions.user_401k_amount = float(o["user_401k_amount"])
    if "user_401k_pct" in o:
        inp.contributions.user_401k_pct = float(o["user_401k_pct"])
    if "spouse_401k_mode" in o:
        inp.contributions.spouse_401k_mode = str(o["spouse_401k_mode"])
    if "spouse_401k_amount" in o:
        inp.contributions.spouse_401k_amount = float(o["spouse_401k_amount"])
    if "spouse_401k_pct" in o:
        inp.contributions.spouse_401k_pct = float(o["spouse_401k_pct"])

    if "user_w2_salary" in o:
        inp.user_w2.gross_annual = float(o["user_w2_salary"])
    if "user_w2_raise" in o:
        inp.user_w2.annual_raise_rate = float(o["user_w2_raise"])
    if "spouse_w2_salary" in o:
        inp.spouse_w2.gross_annual = float(o["spouse_w2_salary"])
    if "spouse_w2_raise" in o:
        inp.spouse_w2.annual_raise_rate = float(o["spouse_w2_raise"])

    if "sole_prop_growth" in o:
        inp.sole_prop.growth_rate = float(o["sole_prop_growth"])

    if "rental_rent_growth" in o:
        inp.rental.rent_growth_rate = float(o["rental_rent_growth"])
    if "rental_vacancy" in o:
        inp.rental.vacancy_rate = float(o["rental_vacancy"])
    if "rental_expense_ratio" in o:
        inp.rental.expense_ratio = float(o["rental_expense_ratio"])

    if "roth_conversion_start_year" in o:
        inp.roth_conversion.start_year = int(o["roth_conversion_start_year"])
    if "roth_conversion_end_year" in o:
        inp.roth_conversion.end_year = int(o["roth_conversion_end_year"])
    if "roth_conversion_source" in o:
        inp.roth_conversion.source = str(o["roth_conversion_source"])

    if "sepp_start_year" in o:
        inp.sepp.start_year = int(o["sepp_start_year"])
    if "sepp_account" in o:
        inp.sepp.account = str(o["sepp_account"])
    if "sepp_interest_rate" in o:
        inp.sepp.interest_rate = float(o["sepp_interest_rate"])

    if "simulation_end_year" in o:
        inp.end_year = int(o["simulation_end_year"])

    for override_key, attr in _BALANCE_OVERRIDE_MAP.items():
        if override_key in o:
            setattr(inp.accounts, attr, float(o[override_key]))


def _build_yearly_comparison(baseline_snaps, modified_snaps, compare_metric: str):
    if not baseline_snaps or not modified_snaps:
        return []
    start = baseline_snaps[0].year
    end = baseline_snaps[-1].year
    year_list = list(range(start, end + 1, 5))
    if year_list[-1] != end:
        year_list.append(end)

    rows = []
    for y in year_list:
        bs = next((s for s in baseline_snaps if s.year == y), None)
        ms = next((s for s in modified_snaps if s.year == y), None)
        if bs is None or ms is None:
            continue
        row = {
            "year": y,
            "baseline_total_net_worth": bs.total_net_worth,
            "modified_total_net_worth": ms.total_net_worth,
            "delta_total_net_worth": ms.total_net_worth - bs.total_net_worth,
        }
        if compare_metric in ("total_expenses", "net_cashflow"):
            bv = _metric_from_snap(bs, compare_metric)
            mv = _metric_from_snap(ms, compare_metric)
            row[f"baseline_{compare_metric}"] = bv
            row[f"modified_{compare_metric}"] = mv
            row[f"delta_{compare_metric}"] = mv - bv
        rows.append(row)
    return rows


def run_what_if(overrides: dict, compare_metric: str = None, *, _sim_count, max_simulations: int = 3) -> dict:
    """Re-run the simulation with overridden inputs and return a comparison dict."""
    if _sim_count[0] >= max_simulations:
        return {"error": "Simulation limit reached (max 3 per question)"}
    if "sim_snapshots" not in st.session_state or "sim_inputs" not in st.session_state:
        return {"error": "No simulation data found. Run the simulation first."}
    if not isinstance(overrides, dict):
        return {"error": "overrides must be an object of override keys to values."}

    baseline_snaps = st.session_state["sim_snapshots"]
    baseline_inputs = st.session_state["sim_inputs"]
    modified_inputs = deepcopy(baseline_inputs)
    _apply_what_if_overrides(modified_inputs, overrides)
    modified_snaps = run_simulation(modified_inputs)
    _sim_count[0] += 1

    b_met = _scenario_metrics(baseline_snaps, baseline_inputs)
    m_met = _scenario_metrics(modified_snaps, modified_inputs)
    cm = compare_metric if compare_metric in _COMPARE_METRICS else "total_net_worth"

    st_yr_b = b_met["solvent_through_year"]
    st_yr_m = m_met["solvent_through_year"]
    solv_delta = None
    if st_yr_b is not None and st_yr_m is not None:
        solv_delta = st_yr_m - st_yr_b
    elif st_yr_m is not None and st_yr_b is None:
        solv_delta = st_yr_m
    elif st_yr_m is None and st_yr_b is not None:
        solv_delta = None

    fi_yr_b = b_met["fi_crossover_year"]
    fi_yr_m = m_met["fi_crossover_year"]
    fi_delta = None
    if fi_yr_b is not None and fi_yr_m is not None:
        fi_delta = fi_yr_m - fi_yr_b

    applied = {k: overrides[k] for k in overrides if k in _WHAT_IF_OVERRIDE_KEYS}

    return {
        "baseline": b_met,
        "modified": m_met,
        "delta": {
            "solvent_through_year_delta": solv_delta,
            "fi_crossover_year_delta": fi_delta,
            "final_net_worth_delta": (m_met["final_net_worth"] or 0) - (b_met["final_net_worth"] or 0),
            "peak_net_worth_delta": (m_met["peak_net_worth"] or 0) - (b_met["peak_net_worth"] or 0),
        },
        "compare_metric": cm,
        "yearly_comparison": _build_yearly_comparison(baseline_snaps, modified_snaps, cm),
        "overrides_applied": applied,
    }


RUN_WHAT_IF_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_what_if",
        "description": (
            "Run a shadow simulation with specific inputs changed from the current sidebar baseline, "
            "then compare key outcomes (solvency, peak and final net worth, and trajectory every 5 years). "
            "Overrides can include W2 salaries and raises, 401(k) modes and dollar/percent amounts, "
            "Solo 401(k) employee deferral and type, employer profit-sharing percent and type, IRAs, "
            "brokerage savings, sole prop income/growth/years, rental parameters, Roth conversion timing "
            "and source, SEPP timing/account/rate, healthcare (flat cost or ACA-related flags), spending "
            "overrides, market return, inflation, simulation end year, and starting account balances. "
            "At most 3 such runs apply per user question (enforced server-side)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "overrides": {
                    "type": "object",
                    "description": "Only include keys you need to change; omitted keys keep the current simulation values.",
                    "properties": {
                        "annual_spending": {
                            "type": "number",
                            "description": "Annual household spending in today's dollars (replaces assumptions.annual_spending_today).",
                        },
                        "brokerage_contribution": {
                            "type": "number",
                            "description": "Annual savings to taxable brokerage account (today's dollars).",
                        },
                        "spending_change_year": {
                            "type": "integer",
                            "description": "First calendar year a percentage spending change applies (with spending_change_pct).",
                        },
                        "spending_change_pct": {
                            "type": "number",
                            "description": "Fractional change to spending from spending_change_year onward, e.g. -0.40 for -40%.",
                        },
                        "user_w2_stop_year": {"type": "integer"},
                        "spouse_w2_stop_year": {"type": "integer"},
                        "user_ira": {
                            "type": "number",
                            "description": "User's annual IRA contribution (today's dollars).",
                        },
                        "spouse_ira": {
                            "type": "number",
                            "description": "Spouse's annual IRA contribution (today's dollars).",
                        },
                        "market_return_rate": {
                            "type": "number",
                            "description": "Annual investment return, decimal (e.g. 0.07).",
                        },
                        "inflation_rate": {"type": "number", "description": "Annual inflation, decimal."},
                        "sole_prop_net": {"type": "number", "description": "Sole proprietorship net annual income (today's dollars)."},
                        "sole_prop_years": {"type": "integer", "description": "Years sole prop stays active from current year."},
                        "rental_monthly_rent": {"type": "number", "description": "Monthly gross rent on the rental property."},
                        "roth_conversion_enabled": {"type": "boolean"},
                        "roth_conversion_amount": {"type": "number", "description": "Annual Roth conversion amount (pre-tax to Roth)."},
                        "sepp_enabled": {"type": "boolean"},
                        "healthcare_cost": {
                            "type": "number",
                            "description": "Annual healthcare when off employer plan (today's dollars); switches assumptions to flat mode at this cost.",
                        },
                        "healthcare_mode": {
                            "type": "string",
                            "enum": ["aca", "flat"],
                            "description": "Healthcare costing mode (ACA premium estimate vs flat annual cost).",
                        },
                        "aca_arp_extended": {
                            "type": "boolean",
                            "description": "Whether ARP-style premium caps apply in ACA mode.",
                        },
                        "aca_additional_oop": {
                            "type": "number",
                            "description": "Extra out-of-pocket beyond annual premium in ACA mode (today's dollars).",
                        },
                        "user_solo_401k_ee": {
                            "type": "number",
                            "description": (
                                "Solo 401(k) employee elective deferral per year ($). Active whenever "
                                "sole prop income > $0 — including years when User also has W2 income. "
                                "CRITICAL: the IRS $23,500 employee deferral cap is SHARED between the "
                                "W2 401(k) and the Solo 401(k). The simulator subtracts the W2 401(k) "
                                "contribution first; if the W2 plan is still maxed, remaining Solo EE "
                                "room is $0 and this override has no effect. To redirect W2 401(k) "
                                "deferrals to the Solo plan, ALWAYS pair this with "
                                "user_401k_mode='dollar' and user_401k_amount=0."
                            ),
                        },
                        "user_solo_401k_ee_type": {
                            "type": "string",
                            "enum": ["pretax", "roth"],
                            "description": "Pre-tax reduces taxable income now; Roth grows tax-free.",
                        },
                        "user_solo_401k_er_pct": {
                            "type": "number",
                            "description": "Employer profit-sharing as fraction of net SE income (0.0 to 0.25).",
                        },
                        "user_solo_401k_er_type": {
                            "type": "string",
                            "enum": ["pretax", "roth"],
                            "description": "Employer contribution type. Roth allowed under SECURE 2.0.",
                        },
                        "user_401k_mode": {
                            "type": "string",
                            "enum": ["max", "dollar", "percent"],
                            "description": "User W2 401(k) contribution mode.",
                        },
                        "user_401k_amount": {
                            "type": "number",
                            "description": "User W2 401(k) fixed dollar amount (when mode=dollar).",
                        },
                        "user_401k_pct": {
                            "type": "number",
                            "description": "User W2 401(k) as fraction of salary (when mode=percent), e.g. 0.10.",
                        },
                        "spouse_401k_mode": {
                            "type": "string",
                            "enum": ["max", "dollar", "percent"],
                            "description": "Spouse W2 401(k) contribution mode.",
                        },
                        "spouse_401k_amount": {"type": "number", "description": "Spouse W2 401(k) fixed dollar amount (when mode=dollar)."},
                        "spouse_401k_pct": {"type": "number", "description": "Spouse W2 401(k) as fraction of salary (when mode=percent)."},
                        "user_w2_salary": {
                            "type": "number",
                            "description": "User's current gross W2 salary ($/yr).",
                        },
                        "user_w2_raise": {
                            "type": "number",
                            "description": "User's annual W2 raise rate, decimal (e.g. 0.03).",
                        },
                        "spouse_w2_salary": {"type": "number", "description": "Spouse's current gross W2 salary ($/yr)."},
                        "spouse_w2_raise": {
                            "type": "number",
                            "description": "Spouse's annual W2 raise rate, decimal.",
                        },
                        "sole_prop_growth": {
                            "type": "number",
                            "description": "Sole prop annual growth rate, decimal (e.g. 0.05).",
                        },
                        "rental_rent_growth": {"type": "number", "description": "Annual rent increase rate, decimal."},
                        "rental_vacancy": {"type": "number", "description": "Vacancy rate as fraction (e.g. 0.05)."},
                        "rental_expense_ratio": {"type": "number", "description": "Operating expenses as fraction of gross rent."},
                        "roth_conversion_start_year": {"type": "integer"},
                        "roth_conversion_end_year": {"type": "integer"},
                        "roth_conversion_source": {"type": "string", "enum": ["user", "spouse"]},
                        "sepp_start_year": {"type": "integer"},
                        "sepp_account": {"type": "string", "enum": ["user", "spouse"]},
                        "sepp_interest_rate": {"type": "number", "description": "SEPP amortization rate, decimal."},
                        "simulation_end_year": {"type": "integer", "description": "Last year to simulate."},
                        "user_401k_pretax_balance": {"type": "number"},
                        "user_401k_roth_balance": {"type": "number"},
                        "user_trad_ira_balance": {"type": "number"},
                        "user_roth_ira_balance": {"type": "number"},
                        "spouse_401k_pretax_balance": {"type": "number"},
                        "spouse_401k_roth_balance": {"type": "number"},
                        "spouse_trad_ira_balance": {"type": "number"},
                        "spouse_roth_ira_balance": {"type": "number"},
                        "brokerage_balance": {"type": "number"},
                        "hsa_balance": {"type": "number"},
                        "cash_balance": {"type": "number"},
                    },
                },
                "compare_metric": {
                    "type": "string",
                    "enum": sorted(_COMPARE_METRICS),
                    "description": (
                        "Which metric to emphasize in trajectory rows (yearly_comparison includes "
                        "total_net_worth always; also includes total_expenses or net_cashflow columns when selected). "
                        "Default in tool implementation is total_net_worth."
                    ),
                },
            },
            "required": ["overrides"],
        },
    },
}
