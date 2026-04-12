"""find_threshold tool — bisection search over a single what-if parameter (Phase threshold tool)."""

import math
from copy import deepcopy

import streamlit as st

from engine.insights import fi_crossover
from engine.simulator import run_simulation
from .what_if import (
    _WHAT_IF_OVERRIDE_KEYS,
    _apply_what_if_overrides,
    _scenario_metrics,
)

# Parameters measured in whole calendar years; bisection needs tolerance=1, not 500.
_YEAR_PARAMETERS = frozenset({
    "spending_change_year",
    "user_w2_stop_year",
    "spouse_w2_stop_year",
    "sole_prop_years",
    "roth_conversion_start_year",
    "roth_conversion_end_year",
    "sepp_start_year",
    "simulation_end_year",
})

_TARGET_PREDICATES = {
    "plan_stays_solvent": lambda snaps: all(s.plan_solvent for s in snaps),
    "no_early_withdrawals": lambda snaps: all(s.early_withdrawal_amount <= 0 for s in snaps),
    "final_net_worth_positive": lambda snaps: snaps[-1].total_net_worth > 0 if snaps else False,
    # Liquid assets (brokerage + cash + HSA) stay positive only through the bridge period —
    # years before the younger person reaches age 60 (proxy for 59½ penalty-free access).
    # After age 60, retirement accounts open and the plan can draw from them freely.
    # USE THIS as the default for "what minimum income lets both people stop W2?" questions.
    # Gives a lower, more meaningful threshold than liquid_assets_always_positive because it
    # does not penalize late-retirement years when RMDs naturally refill liquid assets.
    "liquid_assets_through_bridge": lambda snaps: all(
        s.total_liquid_non_retirement > 0
        for s in snaps
        if min(s.user_age, s.spouse_age) < 60
    ),
    # Liquid assets (brokerage + cash + HSA) never hit zero across ALL simulation years.
    # Checks the entire run including 73+ RMD years where liquid assets are naturally
    # replenished. Usually converges to the same high number as no_early_withdrawals.
    # Avoid for W2-stop questions; prefer liquid_assets_through_bridge instead.
    "liquid_assets_always_positive": lambda snaps: all(
        s.total_liquid_non_retirement > 0 for s in snaps
    ),
    # Weaker variant: only checks that liquid assets are positive at the END of the simulation.
    # Use when early drawdown is acceptable but full depletion by plan end is not.
    "final_liquid_assets_positive": lambda snaps: (
        snaps[-1].total_liquid_non_retirement > 0 if snaps else False
    ),
}

_FI_TARGETS = frozenset({"fi_crossover_exists", "fi_crossover_by_year"})

_VALID_TARGETS = frozenset(_TARGET_PREDICATES.keys()) | _FI_TARGETS


def find_threshold(
    parameter: str,
    direction: str,
    lo: float,
    hi: float,
    tolerance: float = 500.0,
    target: str = "plan_stays_solvent",
    target_fi_year: int | None = None,
    context_overrides: dict | None = None,
    *,
    max_iterations: int = 30,
) -> dict:
    """
    Perform a bisection search to find the threshold value of a single simulation parameter
    that meets a specified target predicate (such as solvency or net worth) using what-if overrides.

    Args:
        parameter (str): The simulation parameter to adjust.
        direction (str): Search direction, either "minimize" or "maximize".
        lo (float): Lower bound of the parameter.
        hi (float): Upper bound of the parameter.
        tolerance (float, optional): Stopping tolerance for search. Defaults to 500.0.
        target (str, optional): Target predicate to evaluate (e.g., "plan_stays_solvent").
        target_fi_year (int, optional): Calendar year ceiling for fi_crossover_by_year target.
        context_overrides (dict, optional): Additional simulation overrides.
        max_iterations (int, optional): Maximum search iterations. Defaults to 30.

    Returns:
        dict: Results including the threshold found or any encountered error.
    """
    if parameter not in _WHAT_IF_OVERRIDE_KEYS:
        return {"error": f"Unsupported parameter: {parameter}"}
    if direction not in ("minimize", "maximize"):
        return {"error": f"Invalid direction: {direction!r} (use 'minimize' or 'maximize')"}
    if target not in _VALID_TARGETS:
        return {"error": f"Unsupported target: {target}"}
    if target == "fi_crossover_by_year" and target_fi_year is None:
        return {"error": "target_fi_year is required when target is fi_crossover_by_year"}
    if "sim_snapshots" not in st.session_state or "sim_inputs" not in st.session_state:
        return {"error": "No simulation data found. Run the simulation first."}

    # Year-based parameters span ~50 years; default tolerance=500 would skip all iterations.
    is_year_param = parameter in _YEAR_PARAMETERS
    effective_tolerance = 1.0 if (is_year_param and tolerance == 500.0) else tolerance

    baseline_inputs = st.session_state["sim_inputs"]
    baseline_metrics = _scenario_metrics(st.session_state["sim_snapshots"], baseline_inputs)
    iteration_count = 0

    while iteration_count < max_iterations and abs(hi - lo) >= effective_tolerance:
        mid = (lo + hi) / 2
        inp = deepcopy(st.session_state["sim_inputs"])
        combined = {**(context_overrides or {}), parameter: mid}
        _apply_what_if_overrides(inp, combined)
        snaps = run_simulation(inp)
        if target in _FI_TARGETS:
            r = inp.assumptions.market_return_rate
            inf = inp.assumptions.inflation_rate
            fi = fi_crossover(snaps, inp, r, inf)
            if target == "fi_crossover_exists":
                passes = fi is not None
            else:
                passes = fi is not None and fi["year"] <= target_fi_year
        else:
            passes = _TARGET_PREDICATES[target](snaps)
        if direction == "minimize":
            if passes:
                hi = mid
            else:
                lo = mid
        else:
            if passes:
                lo = mid
            else:
                hi = mid
        iteration_count += 1

    # For year parameters: round to the nearest safe integer.
    # minimize → lowest integer that passes → ceil(hi)
    # maximize → highest integer that passes → floor(lo)
    if is_year_param:
        threshold = math.ceil(hi) if direction == "minimize" else math.floor(lo)
    else:
        threshold = round((lo + hi) / 2, 2)

    inp = deepcopy(st.session_state["sim_inputs"])
    combined_final = {**(context_overrides or {}), parameter: threshold}
    _apply_what_if_overrides(inp, combined_final)
    snaps = run_simulation(inp)
    result_at_threshold = _scenario_metrics(snaps, inp)

    out = {
        "parameter": parameter,
        "context_overrides": context_overrides or {},
        "direction": direction,
        "target": target,
        "threshold": threshold,
        "search_range": {"lo": round(lo, 2), "hi": round(hi, 2)},
        "result_at_threshold": result_at_threshold,
        "baseline": baseline_metrics,
        "iterations": iteration_count,
        "tolerance": effective_tolerance,
    }
    if target_fi_year is not None:
        out["target_fi_year"] = target_fi_year
    return out


FIND_THRESHOLD_SCHEMA = {
    "type": "function",
    "function": {
        "name": "find_threshold",
        "description": (
            "Find the minimum or maximum value of a single simulation parameter "
            "that satisfies a solvency, FI crossover, or risk target. Uses internal bisection "
            "(no LLM round-trips). Use for 'minimum savings to stay solvent', "
            "'maximum spending before failure', 'minimum sole prop income to reach FI by year Y', etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "parameter": {
                    "type": "string",
                    "enum": sorted(_WHAT_IF_OVERRIDE_KEYS),
                    "description": "The simulation parameter to search over.",
                },
                "direction": {
                    "type": "string",
                    "enum": ["minimize", "maximize"],
                    "description": (
                        "'minimize' finds the lowest value where the target is met. "
                        "'maximize' finds the highest value where the target is still met."
                    ),
                },
                "lo": {
                    "type": "number",
                    "description": "Lower bound of the search range.",
                },
                "hi": {
                    "type": "number",
                    "description": "Upper bound of the search range.",
                },
                "tolerance": {
                    "type": "number",
                    "description": "Stop when search range narrows below this. Default: 500.",
                },
                "target": {
                    "type": "string",
                    "enum": sorted(_VALID_TARGETS),
                    "description": (
                        "Predicate the threshold must satisfy. Default: plan_stays_solvent. "
                        "Choose the predicate that matches the user's actual concern:\n"
                        "- plan_stays_solvent: all accounts never simultaneously hit zero. "
                        "Very lenient — nearly impossible to fail with large retirement balances. "
                        "Often gives a very low threshold with a huge final net worth, meaning "
                        "the constraint was not actually binding.\n"
                        "- final_net_worth_positive: total net worth (liquid + retirement) is "
                        "positive at the last simulated year. Similar leniency to plan_stays_solvent.\n"
                        "- no_early_withdrawals: never draws from penalty-territory retirement "
                        "accounts before 59½. Very strict.\n"
                        "- liquid_assets_through_bridge: brokerage + cash + HSA stay positive "
                        "only through the bridge period (years before the younger person turns 60, "
                        "after which retirement accounts are penalty-free and can cover expenses). "
                        "USE THIS as the default for 'what minimum income/savings lets both people "
                        "stop W2?' questions. It gives a meaningful, lower threshold than "
                        "liquid_assets_always_positive because it does not penalize late-retirement "
                        "years when RMDs naturally refill liquid assets.\n"
                        "- liquid_assets_always_positive: brokerage + cash + HSA never reach zero "
                        "across ALL simulation years including post-73 RMD years. Usually converges "
                        "to the same high number as no_early_withdrawals. Avoid for W2-stop questions.\n"
                        "- final_liquid_assets_positive: brokerage + cash + HSA are positive at the "
                        "end of the simulation. Use when temporary drawdown is acceptable but full "
                        "depletion by plan end is not.\n"
                        "- fi_crossover_exists: portfolio reaches FI (real returns cover full expenses "
                        "including healthcare) at some point after both W2s stop.\n"
                        "- fi_crossover_by_year: FI crossover occurs on or before target_fi_year "
                        "(requires target_fi_year parameter)."
                    ),
                },
                "target_fi_year": {
                    "type": "integer",
                    "description": (
                        "Calendar year ceiling when target is fi_crossover_by_year "
                        "(e.g. 2030 means FI must be reached by end of 2030)."
                    ),
                    
                },
                "context_overrides": {
                    "type": "object",
                    "description": (
                        "Fixed overrides applied to every simulation during the bisection search. "
                        "Use this when the question requires holding additional inputs constant while "
                        "searching over 'parameter'. For example, to find the minimum sole_prop_net "
                        "assuming spouse also stops W2 in 2029, pass "
                        "context_overrides: {\"spouse_w2_stop_year\": 2029}. "
                        "All keys valid for run_what_if overrides are accepted here. "
                        "If a key duplicates 'parameter', the search value for 'parameter' wins."
                    ),
                    "additionalProperties": True,
                },
            },
            "required": ["parameter", "direction", "lo", "hi"],
        },
    },
}
