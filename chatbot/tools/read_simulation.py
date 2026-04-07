"""read_simulation tool + OpenAI schema (Phase 2)."""

import streamlit as st

from engine.tax_calc import compute_federal_tax

from .utils import bridge_years, filter_years, snap_to_dict

_TAX_METHOD = "2025 MFJ progressive brackets with $31,500 standard deduction"

_VALID_QUERIES = frozenset({
    "summary", "yearly_detail", "rmds", "income_sources",
    "account_balances", "bridge_period", "cashflow", "roth_ladder", "sepp",
})


def _handle_summary(snapshots, inputs) -> dict:
    solvent_years = [s.year for s in snapshots if s.plan_solvent]
    insolvent_years = [s.year for s in snapshots if not s.plan_solvent]
    solvency_end_year = solvent_years[-1] if solvent_years else None
    first_insolvent = insolvent_years[0] if insolvent_years else None

    peak_snap = max(snapshots, key=lambda s: s.total_net_worth)
    final = snapshots[-1]

    bridge_start, bridge_end = bridge_years(inputs)
    bridge_snaps = [s for s in snapshots if bridge_start <= s.year <= bridge_end]
    bridge_deficit = sum(
        -s.net_cashflow for s in bridge_snaps if s.net_cashflow < 0
    )

    user_retire_age = inputs.user.w2_stop_year - inputs.user.birth_year
    spouse_retire_age = inputs.spouse.w2_stop_year - inputs.spouse.birth_year

    return {
        "data": {
            "solvency_end_year": solvency_end_year,
            "first_insolvent_year": first_insolvent,
            "plan_ever_insolvent": bool(insolvent_years),
            "peak_net_worth": peak_snap.total_net_worth,
            "peak_net_worth_year": peak_snap.year,
            "final_net_worth": final.total_net_worth,
            "final_year": final.year,
            "bridge_period_start": bridge_start,
            "bridge_period_end": bridge_end,
            "bridge_deficit_total": bridge_deficit,
            "user_w2_stop_year": inputs.user.w2_stop_year,
            "user_retire_age": user_retire_age,
            "spouse_w2_stop_year": inputs.spouse.w2_stop_year,
            "spouse_retire_age": spouse_retire_age,
        },
        "inputs_context": {
            "inflation_rate": inputs.assumptions.inflation_rate,
            "market_return_rate": inputs.assumptions.market_return_rate,
            "tax_method": _TAX_METHOD,
            "annual_spending_today": inputs.assumptions.annual_spending_today,
        },
    }


def _handle_yearly_detail(snapshots, inputs, start_year, end_year) -> dict:
    snaps = filter_years(snapshots, start_year, end_year)
    return {
        "data": [snap_to_dict(s) for s in snaps],
        "inputs_context": {
            "inflation_rate": inputs.assumptions.inflation_rate,
            "tax_method": _TAX_METHOD,
        },
    }


def _handle_rmds(snapshots, inputs, start_year, end_year) -> dict:
    snaps = filter_years(snapshots, start_year, end_year)
    rows = []
    for s in snaps:
        total_rmd = s.user_rmd + s.spouse_rmd
        rmd_covers_pct = (total_rmd / s.total_expenses * 100) if s.total_expenses > 0 else 0.0
        rows.append({
            "year": s.year,
            "user_age": s.user_age,
            "spouse_age": s.spouse_age,
            "user_rmd": s.user_rmd,
            "spouse_rmd": s.spouse_rmd,
            "total_rmd": total_rmd,
            "total_expenses": s.total_expenses,
            "rmd_covers_pct": round(rmd_covers_pct, 1),
        })
    return {
        "data": rows,
        "inputs_context": {
            "tax_method": _TAX_METHOD,
            "note": "RMDs begin at age 73 per SECURE 2.0; taxed as ordinary income under federal progressive brackets.",
        },
    }


def _handle_income_sources(snapshots, inputs, start_year, end_year) -> dict:
    snaps = filter_years(snapshots, start_year, end_year)
    rows = []
    for s in snaps:
        total_rmd = s.user_rmd + s.spouse_rmd
        rows.append({
            "year": s.year,
            "user_age": s.user_age,
            "spouse_age": s.spouse_age,
            "user_w2_gross": s.user_w2_gross,
            "spouse_w2_gross": s.spouse_w2_gross,
            "sole_prop_net": s.sole_prop_net,
            "rental_cashflow": s.rental_cashflow,
            "sepp_payment": s.sepp_payment,
            "user_rmd": s.user_rmd,
            "spouse_rmd": s.spouse_rmd,
            "total_rmd": total_rmd,
            "total_net_income": s.total_net_income,
        })
    return {
        "data": rows,
        "inputs_context": {
            "sole_prop_years_active": inputs.sole_prop.years_active,
            "rental_vacancy_rate": inputs.rental.vacancy_rate,
            "rental_expense_ratio": inputs.rental.expense_ratio,
            "tax_method": _TAX_METHOD,
        },
    }


def _handle_account_balances(snapshots, inputs, start_year, end_year) -> dict:
    snaps = filter_years(snapshots, start_year, end_year)
    rows = []
    for s in snaps:
        rows.append({
            "year": s.year,
            "user_age": s.user_age,
            "spouse_age": s.spouse_age,
            "user_401k_pretax": s.user_401k_pretax,
            "user_401k_roth": s.user_401k_roth,
            "user_trad_ira": s.user_trad_ira,
            "user_roth_ira": s.user_roth_ira,
            "spouse_401k_pretax": s.spouse_401k_pretax,
            "spouse_401k_roth": s.spouse_401k_roth,
            "spouse_trad_ira": s.spouse_trad_ira,
            "spouse_roth_ira": s.spouse_roth_ira,
            "brokerage": s.brokerage,
            "hsa": s.hsa,
            "cash": s.cash,
            "total_retirement_accounts": s.total_retirement_accounts,
            "total_liquid_non_retirement": s.total_liquid_non_retirement,
            "total_net_worth": s.total_net_worth,
        })
    return {
        "data": rows,
        "inputs_context": {
            "market_return_rate": inputs.assumptions.market_return_rate,
        },
    }


def _handle_bridge_period(snapshots, inputs) -> dict:
    bridge_start, bridge_end = bridge_years(inputs)
    snaps = [s for s in snapshots if bridge_start <= s.year <= bridge_end]
    rows = []
    for s in snaps:
        rows.append({
            "year": s.year,
            "user_age": s.user_age,
            "spouse_age": s.spouse_age,
            "total_net_income": s.total_net_income,
            "total_expenses": s.total_expenses,
            "net_cashflow": s.net_cashflow,
            "early_withdrawal_amount": s.early_withdrawal_amount,
            "sepp_payment": s.sepp_payment,
            "plan_solvent": s.plan_solvent,
            "cash": s.cash,
            "brokerage": s.brokerage,
        })

    total_deficit = sum(-s.net_cashflow for s in snaps if s.net_cashflow < 0)
    total_early_withdrawals = sum(s.early_withdrawal_amount for s in snaps)

    return {
        "data": rows,
        "inputs_context": {
            "bridge_start_year": bridge_start,
            "bridge_end_year": bridge_end,
            "bridge_length_years": max(0, bridge_end - bridge_start + 1),
            "total_bridge_deficit": total_deficit,
            "total_early_withdrawals": total_early_withdrawals,
            "sepp_enabled": inputs.sepp.enabled,
            "roth_conversion_enabled": inputs.roth_conversion.enabled,
            "note": "Bridge period = last W2 stop year through the year before the first person turns 60.",
        },
    }


def _handle_cashflow(snapshots, inputs, start_year, end_year) -> dict:
    snaps = filter_years(snapshots, start_year, end_year)
    rows = []
    for s in snaps:
        rows.append({
            "year": s.year,
            "user_age": s.user_age,
            "spouse_age": s.spouse_age,
            "total_net_income": s.total_net_income,
            "total_expenses": s.total_expenses,
            "net_cashflow": s.net_cashflow,
            "surplus_or_deficit": "surplus" if s.net_cashflow >= 0 else "deficit",
            "early_withdrawal_amount": s.early_withdrawal_amount,
            "plan_solvent": s.plan_solvent,
        })
    return {
        "data": rows,
        "inputs_context": {
            "annual_spending_today": inputs.assumptions.annual_spending_today,
            "inflation_rate": inputs.assumptions.inflation_rate,
            "annual_healthcare_off_employer": inputs.assumptions.annual_healthcare_off_employer,
        },
    }


def _handle_roth_ladder(snapshots, inputs, start_year, end_year) -> dict:
    snaps = filter_years(snapshots, start_year, end_year)
    rows = []
    for s in snaps:
        conversion_tax_cost = (
            compute_federal_tax(s.gross_taxable_income + s.roth_conversion_amount)
            - compute_federal_tax(s.gross_taxable_income)
        )
        rows.append({
            "year": s.year,
            "user_age": s.user_age,
            "spouse_age": s.spouse_age,
            "roth_conversion_amount": s.roth_conversion_amount,
            "conversion_tax_cost": conversion_tax_cost,
            "accessible_roth_seasoned": s.accessible_roth_seasoned,
            "user_roth_ira": s.user_roth_ira,
            "spouse_roth_ira": s.spouse_roth_ira,
        })
    return {
        "data": rows,
        "inputs_context": {
            "roth_conversion_enabled": inputs.roth_conversion.enabled,
            "roth_conversion_start_year": inputs.roth_conversion.start_year,
            "roth_conversion_end_year": inputs.roth_conversion.end_year,
            "roth_conversion_annual_amount": inputs.roth_conversion.annual_amount,
            "roth_conversion_source": inputs.roth_conversion.source,
            "tax_method": _TAX_METHOD,
            "note": (
                "Converted principal is accessible penalty-free after 5 years (Roth conversion ladder). "
                "accessible_roth_seasoned is cumulative conversions ≥5 years old."
            ),
        },
    }


def _handle_sepp(snapshots, inputs) -> dict:
    sepp = inputs.sepp
    if not sepp.enabled:
        return {
            "data": [],
            "inputs_context": {"sepp_enabled": False},
        }

    person_birth = (
        inputs.user.birth_year if sepp.account == "user"
        else inputs.spouse.birth_year
    )
    sepp_end = max(sepp.start_year + 4, person_birth + 59)
    active_snaps = [s for s in snapshots if sepp.start_year <= s.year <= sepp_end]

    rows = []
    for s in active_snaps:
        rows.append({
            "year": s.year,
            "user_age": s.user_age,
            "spouse_age": s.spouse_age,
            "sepp_payment": s.sepp_payment,
        })

    return {
        "data": rows,
        "inputs_context": {
            "sepp_enabled": True,
            "sepp_account": sepp.account,
            "sepp_start_year": sepp.start_year,
            "sepp_end_year": sepp_end,
            "sepp_duration_years": sepp_end - sepp.start_year + 1,
            "sepp_interest_rate": sepp.interest_rate,
            "note": (
                "SEPP (IRS 72(t)) amortization method. Plan must run at least 5 years "
                "or until age 59½, whichever is later. Payments are ordinary taxable income."
            ),
        },
    }


def read_simulation(query: str, start_year: int = None, end_year: int = None) -> dict:
    """Read data from the active simulation snapshot stored in st.session_state.

    Returns a JSON-serializable dict with keys 'data' and 'inputs_context'.
    """
    if "sim_snapshots" not in st.session_state:
        return {"error": "No simulation data found. Run the simulation first."}
    if query not in _VALID_QUERIES:
        return {"error": f"Unknown query '{query}'. Valid queries: {sorted(_VALID_QUERIES)}"}

    snapshots = st.session_state["sim_snapshots"]
    inputs = st.session_state["sim_inputs"]

    if query == "summary":
        return _handle_summary(snapshots, inputs)
    if query == "yearly_detail":
        return _handle_yearly_detail(snapshots, inputs, start_year, end_year)
    if query == "rmds":
        return _handle_rmds(snapshots, inputs, start_year, end_year)
    if query == "income_sources":
        return _handle_income_sources(snapshots, inputs, start_year, end_year)
    if query == "account_balances":
        return _handle_account_balances(snapshots, inputs, start_year, end_year)
    if query == "bridge_period":
        return _handle_bridge_period(snapshots, inputs)
    if query == "cashflow":
        return _handle_cashflow(snapshots, inputs, start_year, end_year)
    if query == "roth_ladder":
        return _handle_roth_ladder(snapshots, inputs, start_year, end_year)
    if query == "sepp":
        return _handle_sepp(snapshots, inputs)


READ_SIMULATION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_simulation",
        "description": (
            "Read data from the current retirement simulation. Use this for any quantitative "
            "question about the plan — balances, income, expenses, solvency, RMDs, etc. "
            "Always call this before answering numeric questions, never guess or fabricate numbers."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "enum": sorted(_VALID_QUERIES),
                    "description": (
                        "The aspect of the simulation to read. "
                        "'summary': high-level solvency, peak/final net worth, bridge deficit, key dates. "
                        "'yearly_detail': all snapshot fields for every year (use start_year/end_year to narrow). "
                        "'rmds': RMD amounts by year plus rmd_covers_pct of expenses. "
                        "'income_sources': W2, sole-prop, rental, SEPP, and RMD income by year. "
                        "'account_balances': all 11 account balances by year. "
                        "'bridge_period': cashflow detail during the pre-59.5 gap between W2 stop and 401k access. "
                        "'cashflow': net cashflow, surplus/deficit flag, early withdrawals by year. "
                        "'roth_ladder': conversion amounts, tax cost, and seasoned accessible balance by year. "
                        "'sepp': SEPP payment schedule and plan parameters."
                    ),
                },
                "start_year": {
                    "type": "integer",
                    "description": "Filter results to years >= start_year (calendar year, e.g. 2035). Optional.",
                },
                "end_year": {
                    "type": "integer",
                    "description": "Filter results to years <= end_year (calendar year, e.g. 2055). Optional.",
                },
            },
            "required": ["query"],
        },
    },
}
