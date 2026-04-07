"""Progressive federal income tax calculator (MFJ brackets from config)."""
import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "tax_brackets.json"


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return json.load(f)


_CONFIG = _load_config()
STANDARD_DEDUCTION: float = _CONFIG["standard_deduction"]
_BRACKETS: list[dict] = sorted(_CONFIG["brackets"], key=lambda b: b["min"])


def compute_federal_tax(gross_income: float) -> float:
    """Compute federal income tax on gross ordinary income (MFJ).

    Applies the standard deduction, then progressive brackets.
    Returns total tax owed (≥ 0).
    """
    taxable = max(0.0, gross_income - STANDARD_DEDUCTION)
    tax = 0.0
    for i, bracket in enumerate(_BRACKETS):
        floor = bracket["min"]
        ceiling = _BRACKETS[i + 1]["min"] if i + 1 < len(_BRACKETS) else float("inf")
        if taxable <= floor:
            break
        layer = min(taxable, ceiling) - floor
        tax += layer * bracket["rate"]
    return tax


def marginal_rate(gross_income: float) -> float:
    """Return the marginal tax rate for the given gross income (after std deduction)."""
    taxable = max(0.0, gross_income - STANDARD_DEDUCTION)
    rate = _BRACKETS[0]["rate"]
    for bracket in _BRACKETS:
        if taxable > bracket["min"]:
            rate = bracket["rate"]
        else:
            break
    return rate


def effective_rate(gross_income: float) -> float:
    """Return the effective tax rate = tax / gross_income. Returns 0 if income ≤ 0."""
    if gross_income <= 0:
        return 0.0
    return compute_federal_tax(gross_income) / gross_income
