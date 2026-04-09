"""find_threshold tool — bisection search over a single what-if parameter (Phase threshold tool)."""

import math
from copy import deepcopy

import streamlit as st

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
}


def find_threshold(
    parameter: str,
    direction: str,
    lo: float,
    hi: float,
    tolerance: float = 500.0,
    target: str = "plan_stays_solvent",
    *,
    max_iterations: int = 30,
) -> dict:
    if parameter not in _WHAT_IF_OVERRIDE_KEYS:
        return {"error": f"Unsupported parameter: {parameter}"}
    if direction not in ("minimize", "maximize"):
        return {"error": f"Invalid direction: {direction!r} (use 'minimize' or 'maximize')"}
    if target not in _TARGET_PREDICATES:
        return {"error": f"Unsupported target: {target}"}
    if "sim_snapshots" not in st.session_state or "sim_inputs" not in st.session_state:
        return {"error": "No simulation data found. Run the simulation first."}

    # Year-based parameters span ~50 years; default tolerance=500 would skip all iterations.
    is_year_param = parameter in _YEAR_PARAMETERS
    effective_tolerance = 1.0 if (is_year_param and tolerance == 500.0) else tolerance

    baseline_metrics = _scenario_metrics(st.session_state["sim_snapshots"])
    iteration_count = 0

    while iteration_count < max_iterations and abs(hi - lo) >= effective_tolerance:
        mid = (lo + hi) / 2
        inp = deepcopy(st.session_state["sim_inputs"])
        _apply_what_if_overrides(inp, {parameter: mid})
        snaps = run_simulation(inp)
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
    _apply_what_if_overrides(inp, {parameter: threshold})
    snaps = run_simulation(inp)
    result_at_threshold = _scenario_metrics(snaps)

    return {
        "parameter": parameter,
        "direction": direction,
        "target": target,
        "threshold": threshold,
        "search_range": {"lo": round(lo, 2), "hi": round(hi, 2)},
        "result_at_threshold": result_at_threshold,
        "baseline": baseline_metrics,
        "iterations": iteration_count,
        "tolerance": effective_tolerance,
    }


FIND_THRESHOLD_SCHEMA = {
    "type": "function",
    "function": {
        "name": "find_threshold",
        "description": (
            "Find the minimum or maximum value of a single simulation parameter "
            "that satisfies a solvency or risk target. Uses internal bisection "
            "(no LLM round-trips). Use this for questions like 'what is the minimum "
            "brokerage savings to stay solvent?' or 'what is the maximum spending "
            "before the plan fails?'."
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
                    "enum": sorted(_TARGET_PREDICATES.keys()),
                    "description": (
                        "Predicate the threshold must satisfy. Default: plan_stays_solvent."
                    ),
                },
            },
            "required": ["parameter", "direction", "lo", "hi"],
        },
    },
}
