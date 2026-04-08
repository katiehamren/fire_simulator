"""Progressive federal income tax calculator (MFJ brackets from config)."""
import json
from pathlib import Path
from typing import Optional

_CONFIG_PATH = Path(__file__).parent / "tax_brackets.json"


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return json.load(f)


_CONFIG = _load_config()
STANDARD_DEDUCTION: float = _CONFIG["standard_deduction"]
_BRACKETS: list[dict] = sorted(_CONFIG["brackets"], key=lambda b: b["min"])

# 2025 constants (self-employment tax)
_SE_DEDUCTION_FACTOR = 0.9235
_SS_WAGE_BASE_2025 = 176_100
_SS_WAGE_BASE_GROWTH = 0.03


def inflated_brackets(year: int, inflation_rate: float) -> tuple[float, list[dict]]:
    """Return (standard_deduction, brackets) with thresholds inflated from base year."""
    base_year = int(_CONFIG["tax_year"])
    years_elapsed = max(0, year - base_year)
    factor = (1 + inflation_rate) ** years_elapsed
    std_ded = STANDARD_DEDUCTION * factor
    brackets = [{"rate": b["rate"], "min": b["min"] * factor} for b in _BRACKETS]
    return std_ded, brackets


def _tax_from_brackets(gross_income: float, standard_deduction: float, brackets: list[dict]) -> float:
    taxable = max(0.0, gross_income - standard_deduction)
    tax = 0.0
    for i, bracket in enumerate(brackets):
        floor = bracket["min"]
        ceiling = brackets[i + 1]["min"] if i + 1 < len(brackets) else float("inf")
        if taxable <= floor:
            break
        layer = min(taxable, ceiling) - floor
        tax += layer * bracket["rate"]
    return tax


def compute_federal_tax(
    gross_income: float,
    year: Optional[int] = None,
    inflation_rate: float = 0.0,
) -> float:
    """Compute federal income tax on gross ordinary income (MFJ).

    When ``year`` is None, uses frozen base-year brackets (backward compatible).
    When ``year`` is set, inflates brackets and standard deduction by ``inflation_rate``.
    """
    if year is None:
        return _tax_from_brackets(gross_income, STANDARD_DEDUCTION, _BRACKETS)
    std_ded, brackets = inflated_brackets(year, inflation_rate)
    return _tax_from_brackets(gross_income, std_ded, brackets)


def marginal_rate(
    gross_income: float,
    year: Optional[int] = None,
    inflation_rate: float = 0.0,
) -> float:
    """Marginal rate on ordinary income (after standard deduction)."""
    if year is None:
        std_ded = STANDARD_DEDUCTION
        brackets = _BRACKETS
    else:
        std_ded, brackets = inflated_brackets(year, inflation_rate)
    taxable = max(0.0, gross_income - std_ded)
    rate = brackets[0]["rate"]
    for bracket in brackets:
        if taxable > bracket["min"]:
            rate = bracket["rate"]
        else:
            break
    return rate


def effective_rate(
    gross_income: float,
    year: Optional[int] = None,
    inflation_rate: float = 0.0,
) -> float:
    """Effective rate = federal ordinary income tax / gross ordinary income."""
    if gross_income <= 0:
        return 0.0
    return compute_federal_tax(gross_income, year, inflation_rate) / gross_income


def compute_se_tax(se_net_income: float, w2_wages: float = 0.0, year: int = 2026) -> float:
    """Self-employment tax on net SE income (SS capped, Medicare + additional Medicare)."""
    if se_net_income <= 0:
        return 0.0
    taxable_se = se_net_income * _SE_DEDUCTION_FACTOR
    wage_base = _SS_WAGE_BASE_2025 * (1 + _SS_WAGE_BASE_GROWTH) ** max(0, year - 2025)
    ss_room = max(0.0, wage_base - w2_wages)
    ss_taxable = min(taxable_se, ss_room)
    ss_tax = ss_taxable * 0.124
    medicare_tax = taxable_se * 0.029
    combined = w2_wages + taxable_se
    additional_medicare = max(0.0, combined - 250_000) * 0.009
    return ss_tax + medicare_tax + additional_medicare


def compute_ltcg_tax(
    ordinary_taxable: float,
    gains: float,
    year: int = 2026,
    inflation_rate: float = 0.03,
) -> float:
    """Long-term capital gains tax (MFJ); brackets inflate with ``inflation_rate``."""
    if gains <= 0:
        return 0.0
    factor = (1 + inflation_rate) ** max(0, year - 2025)
    bracket_0_max = 96_700 * factor
    bracket_15_max = 600_050 * factor
    total = ordinary_taxable + gains
    if total <= bracket_0_max:
        return 0.0
    if ordinary_taxable >= bracket_15_max:
        return gains * 0.20
    space0 = max(0.0, bracket_0_max - ordinary_taxable)
    gains_at_0 = min(gains, space0)
    remaining = gains - gains_at_0
    if remaining <= 0:
        return 0.0
    start_15 = max(ordinary_taxable, bracket_0_max)
    space15 = max(0.0, bracket_15_max - start_15)
    gains_at_15 = min(remaining, space15)
    gains_at_20 = remaining - gains_at_15
    return gains_at_15 * 0.15 + gains_at_20 * 0.20
