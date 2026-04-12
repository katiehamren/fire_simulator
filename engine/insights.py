"""Computed insight metrics from simulation snapshots (server-side, no LLM)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

from .models import SimInputs, YearSnapshot, CURRENT_YEAR
from .simulator import run_simulation


def _estimate_healthcare(inputs: SimInputs, year: int) -> float:
    """Estimate annual healthcare cost for a year, ignoring employer coverage.

    Uses the same mode (flat or ACA) as the main simulation but never
    returns $0 for employer-covered years — the FI crossover needs to
    know what expenses *would be* without a W2 plan.
    """
    inflation_factor = (1 + inputs.assumptions.inflation_rate) ** (year - CURRENT_YEAR)
    if inputs.assumptions.healthcare_mode == "flat":
        return inputs.assumptions.annual_healthcare_flat * inflation_factor
    from .aca import estimate_aca_premium
    aca_result = estimate_aca_premium(
        magi=0.0,
        year=year,
        inflation_rate=inputs.assumptions.inflation_rate,
        benchmark_override=inputs.assumptions.aca_benchmark_override or None,
        arp_extended=inputs.assumptions.aca_arp_extended,
    )
    return aca_result["premium"] + inputs.assumptions.aca_additional_oop * inflation_factor


def fi_crossover(
    snapshots: list[YearSnapshot],
    inputs: SimInputs,
    return_rate: float,
    inflation_rate: float,
) -> Optional[dict[str, Any]]:
    """First year where total portfolio real returns cover full expenses
    assuming no employer healthcare (i.e. healthcare is always costed).

    Searches from the current year so it can surface "you could stop
    working earlier" when the portfolio already supports expenses.
    For years where the snapshot has healthcare = 0 (employer-covered),
    an estimated healthcare cost is added to total_expenses.
    """
    real_rate = max(0.0, return_rate - inflation_rate)

    for s in snapshots:
        expenses = s.total_expenses
        if s.on_employer_healthcare:
            expenses += _estimate_healthcare(inputs, s.year)
        if s.total_net_worth * real_rate >= expenses:
            return {
                "year": s.year,
                "user_age": s.user_age,
                "spouse_age": s.spouse_age,
                "portfolio_returns": round(s.total_net_worth * real_rate),
                "total_expenses": round(expenses),
            }
    return None


def bridge_burn(snapshots: list[YearSnapshot], inputs: SimInputs) -> dict[str, Any]:
    """Compute bridge period liquid burn and cashflow deficit stats."""
    bridge_start = inputs.user.w2_stop_year
    bridge_end = min(inputs.user.birth_year + 60, inputs.spouse.birth_year + 60)

    pre_bridge = next((s for s in snapshots if s.year == bridge_start - 1), None)
    at_bridge_end = next((s for s in snapshots if s.year == bridge_end), None)

    r = inputs.assumptions.inflation_rate

    # Deflate nominal balances to today's dollars so the comparison matches
    # the inflation-adjusted view shown in the graph.
    def _real(nominal: float, year: int) -> float:
        return nominal / (1 + r) ** (year - CURRENT_YEAR)

    liquid_at_start_real = _real(
        pre_bridge.total_liquid_non_retirement if pre_bridge else 0.0,
        bridge_start - 1,
    )
    liquid_at_end_real = _real(
        at_bridge_end.total_liquid_non_retirement if at_bridge_end else 0.0,
        bridge_end,
    )

    bridge_snaps = [s for s in snapshots if bridge_start <= s.year < bridge_end]

    # Average net cashflow over ALL bridge years in today's dollars.
    avg_annual_cashflow_real = (
        sum(_real(s.net_cashflow, s.year) for s in bridge_snaps)
        / max(len(bridge_snaps), 1)
    )

    # Net change in real liquid assets: positive = grew, negative = consumed.
    liquid_net_change_real = liquid_at_end_real - liquid_at_start_real
    liquid_net_change_pct = (
        liquid_net_change_real / liquid_at_start_real * 100
        if liquid_at_start_real > 0
        else 0.0
    )

    return {
        "bridge_start": bridge_start,
        "bridge_end": bridge_end,
        "years": bridge_end - bridge_start,
        "avg_annual_cashflow": avg_annual_cashflow_real,
        "liquid_at_start": liquid_at_start_real,
        "liquid_at_end": liquid_at_end_real,
        "liquid_net_change": liquid_net_change_real,
        "liquid_net_change_pct": liquid_net_change_pct,
    }


def tax_windows(
    snapshots: list[YearSnapshot], inputs: SimInputs
) -> Optional[dict[str, Any]]:
    """Find lowest-tax years after both W2s stop (by snapshot effective_tax_rate)."""
    post_retire = [
        s
        for s in snapshots
        if s.year >= max(inputs.user.w2_stop_year, inputs.spouse.w2_stop_year)
        and s.gross_taxable_income > 0
    ]
    if not post_retire:
        return None

    sorted_by_rate = sorted(post_retire, key=lambda s: s.effective_tax_rate)
    low_years = sorted_by_rate[:10]
    low_years.sort(key=lambda s: s.year)

    avg_rate = sum(s.effective_tax_rate for s in low_years) / len(low_years)

    return {
        "low_tax_start": low_years[0].year,
        "low_tax_end": low_years[-1].year,
        "avg_effective_rate": avg_rate,
        "lowest_year": sorted_by_rate[0].year,
        "lowest_rate": sorted_by_rate[0].effective_tax_rate,
    }


def rmd_pressure(snapshots: list[YearSnapshot]) -> Optional[dict[str, Any]]:
    """When RMDs exist and optionally when they exceed annual expenses."""
    rmd_snaps = [s for s in snapshots if (s.user_rmd + s.spouse_rmd) > 0]
    if not rmd_snaps:
        return None

    first_rmd_year = rmd_snaps[0].year

    exceeds_year = None
    for s in rmd_snaps:
        total_rmd = s.user_rmd + s.spouse_rmd
        if total_rmd > s.total_expenses:
            exceeds_year = s.year
            break

    peak_rmd_snap = max(rmd_snaps, key=lambda s: s.user_rmd + s.spouse_rmd)
    peak_rmd = peak_rmd_snap.user_rmd + peak_rmd_snap.spouse_rmd

    rmd_expense_pct = (
        peak_rmd / peak_rmd_snap.total_expenses * 100
        if peak_rmd_snap.total_expenses > 0
        else 0.0
    )

    return {
        "first_rmd_year": first_rmd_year,
        "exceeds_expenses_year": exceeds_year,
        "peak_rmd": peak_rmd,
        "peak_rmd_year": peak_rmd_snap.year,
        "peak_rmd_expense_pct": rmd_expense_pct,
    }


def income_dependency(
    snapshots: list[YearSnapshot], inputs: SimInputs
) -> dict[str, Any]:
    """Re-run simulation without sole prop or without rental to test dependency."""
    results: dict[str, Any] = {}

    inp_no_sp = deepcopy(inputs)
    inp_no_sp.sole_prop.net_annual = 0.0
    inp_no_sp.sole_prop.years_active = 0
    snaps_no_sp = run_simulation(inp_no_sp)
    no_sp_solvent = all(s.plan_solvent for s in snaps_no_sp)
    no_sp_insolvent_year = next(
        (s.year for s in snaps_no_sp if not s.plan_solvent), None
    )
    results["without_sole_prop"] = {
        "still_solvent": no_sp_solvent,
        "insolvent_year": no_sp_insolvent_year,
        "final_net_worth": snaps_no_sp[-1].total_net_worth if snaps_no_sp else 0.0,
    }

    inp_no_rent = deepcopy(inputs)
    inp_no_rent.rental.monthly_gross_rent = 0.0
    snaps_no_rent = run_simulation(inp_no_rent)
    no_rent_solvent = all(s.plan_solvent for s in snaps_no_rent)
    no_rent_insolvent_year = next(
        (s.year for s in snaps_no_rent if not s.plan_solvent), None
    )
    results["without_rental"] = {
        "still_solvent": no_rent_solvent,
        "insolvent_year": no_rent_insolvent_year,
        "final_net_worth": snaps_no_rent[-1].total_net_worth if snaps_no_rent else 0.0,
    }

    return results


def lifetime_tax(
    snapshots: list[YearSnapshot], inputs: SimInputs
) -> dict[str, Any]:
    """Total taxes paid, split accumulation vs drawdown; average effective rates by phase."""
    last_w2 = max(inputs.user.w2_stop_year, inputs.spouse.w2_stop_year)

    accum_tax = sum(s.taxes_paid for s in snapshots if s.year < last_w2)
    drawdown_tax = sum(s.taxes_paid for s in snapshots if s.year >= last_w2)
    total_tax = accum_tax + drawdown_tax

    accum_se = sum(s.se_tax for s in snapshots if s.year < last_w2)
    drawdown_se = sum(s.se_tax for s in snapshots if s.year >= last_w2)
    total_ltcg = sum(s.ltcg_tax for s in snapshots)

    n_accum = max(sum(1 for s in snapshots if s.year < last_w2), 1)
    n_draw = max(sum(1 for s in snapshots if s.year >= last_w2), 1)
    avg_accum_rate = (
        sum(s.effective_tax_rate for s in snapshots if s.year < last_w2) / n_accum
    )
    avg_drawdown_rate = (
        sum(s.effective_tax_rate for s in snapshots if s.year >= last_w2) / n_draw
    )

    return {
        "total_tax": total_tax,
        "accumulation_tax": accum_tax,
        "drawdown_tax": drawdown_tax,
        "accumulation_se_tax": accum_se,
        "drawdown_se_tax": drawdown_se,
        "total_se_tax": accum_se + drawdown_se,
        "total_ltcg_tax": total_ltcg,
        "avg_accumulation_rate": avg_accum_rate,
        "avg_drawdown_rate": avg_drawdown_rate,
    }


def compute_all_insights(
    snapshots: list[YearSnapshot], inputs: SimInputs
) -> dict[str, Any]:
    return_rate = inputs.assumptions.market_return_rate
    inflation_rate = inputs.assumptions.inflation_rate
    return {
        "fi_crossover": fi_crossover(snapshots, inputs, return_rate, inflation_rate),
        "bridge_burn": bridge_burn(snapshots, inputs),
        "tax_windows": tax_windows(snapshots, inputs),
        "rmd_pressure": rmd_pressure(snapshots),
        "income_dependency": income_dependency(snapshots, inputs),
        "lifetime_tax": lifetime_tax(snapshots, inputs),
    }
