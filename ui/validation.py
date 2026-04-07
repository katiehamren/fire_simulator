"""Input validation warnings for the simulator."""

from engine.models import CURRENT_YEAR, SimInputs
from engine.simulator import _compute_w2_401k
from engine.tax_calc import compute_federal_tax

from .formatting import fmt

K401_EE_LIMIT_2026 = 23_500   # IRS employee elective deferral limit
IRA_LIMIT_2026 = 7_000   # IRA annual contribution limit (under 50)


def validate_inputs(inputs: SimInputs) -> list[tuple[str, str]]:
    """Return (level, message) pairs — level is 'error' or 'warning'."""
    issues: list[tuple[str, str]] = []
    m = lambda n: f"`{fmt(n)}`"

    _k_w2_0  = inputs.user_w2.gross_annual   if inputs.user.w2_stop_year   > CURRENT_YEAR else 0.0
    _h_w2_0  = inputs.spouse_w2.gross_annual if inputs.spouse.w2_stop_year > CURRENT_YEAR else 0.0
    _sp_0    = inputs.sole_prop.net_annual
    _lim_0   = float(K401_EE_LIMIT_2026)
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

    if inputs.contributions.user_ira > IRA_LIMIT_2026:
        issues.append(("warning",
            f"User's IRA contribution ({m(inputs.contributions.user_ira)}/yr) exceeds "
            f"the {CURRENT_YEAR} annual IRA limit ({m(IRA_LIMIT_2026)}). "
            "Over-contributions face a 6% annual excise tax."))
    if inputs.contributions.spouse_ira > IRA_LIMIT_2026:
        issues.append(("warning",
            f"Spouse's IRA contribution ({m(inputs.contributions.spouse_ira)}/yr) exceeds "
            f"the {CURRENT_YEAR} annual IRA limit ({m(IRA_LIMIT_2026)})."))

    last_retire = max(inputs.user.w2_stop_year, inputs.spouse.w2_stop_year)
    if inputs.end_year < last_retire + 15:
        issues.append(("warning",
            f"Simulation ends in {inputs.end_year}, only "
            f"{inputs.end_year - last_retire} years after the last W2 stop. "
            f"Consider extending to at least {last_retire + 25} to model late-retirement risk."))

    if inputs.user.w2_stop_year <= CURRENT_YEAR:
        issues.append(("warning",
            f"User's W2 stop year ({inputs.user.w2_stop_year}) is in the past — "
            "no W2 income for User will be modeled."))
    if inputs.spouse.w2_stop_year <= CURRENT_YEAR:
        issues.append(("warning",
            f"Spouse's W2 stop year ({inputs.spouse.w2_stop_year}) is in the past — "
            "no W2 income for Spouse will be modeled."))

    return issues
