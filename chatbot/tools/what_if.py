"""run_what_if tool + OpenAI schema (Phase 3)."""

from copy import deepcopy

import streamlit as st

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
})

_COMPARE_METRICS = frozenset({
    "total_net_worth",
    "peak_net_worth",
    "final_net_worth",
    "solvent_through_year",
    "total_expenses",
    "net_cashflow",
})


def _scenario_metrics(snapshots):
    if not snapshots:
        return {
            "solvent_through_year": None,
            "first_insolvent_year": None,
            "peak_net_worth": None,
            "peak_net_worth_year": None,
            "final_net_worth": None,
            "final_year": None,
        }
    solvent_years = [s.year for s in snapshots if s.plan_solvent]
    insolvent_years = [s.year for s in snapshots if not s.plan_solvent]
    peak = max(snapshots, key=lambda s: s.total_net_worth)
    final = snapshots[-1]
    return {
        "solvent_through_year": max(solvent_years) if solvent_years else None,
        "first_insolvent_year": min(insolvent_years) if insolvent_years else None,
        "peak_net_worth": peak.total_net_worth,
        "peak_net_worth_year": peak.year,
        "final_net_worth": final.total_net_worth,
        "final_year": final.year,
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
        inp.assumptions.annual_healthcare_off_employer = float(o["healthcare_cost"])


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

    b_met = _scenario_metrics(baseline_snaps)
    m_met = _scenario_metrics(modified_snaps)
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

    applied = {k: overrides[k] for k in overrides if k in _WHAT_IF_OVERRIDE_KEYS}

    return {
        "baseline": b_met,
        "modified": m_met,
        "delta": {
            "solvent_through_year_delta": solv_delta,
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
            "Use for hypotheticals — e.g. retire earlier, change spending, toggle Roth conversion or SEPP. "
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
                            "description": "Annual healthcare when off employer plan (today's dollars).",
                        },
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
