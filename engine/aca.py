"""Simplified ACA premium tax credit estimator for retirement planning.

Uses the 2025 ACA framework (enhanced PTC from ARP/IRA extension).
All dollar thresholds inflate with the provided rate from the 2025 base year.
"""

_FPL_2_PERSON_2025 = 20_440
_FPL_ANNUAL_GROWTH = 0.02

_BENCHMARK_SILVER_2025 = 28_000
_BENCHMARK_ANNUAL_GROWTH = 0.05

# ARP-extended applicable percentage table (% of income household pays)
# (lower_fpl_pct, upper_fpl_pct, lower_contribution_pct, upper_contribution_pct)
_ARP_TABLE = [
    (0,   150, 0.00,  0.00),
    (150, 200, 0.00,  0.02),
    (200, 250, 0.02,  0.04),
    (250, 300, 0.04,  0.06),
    (300, 400, 0.06,  0.085),
    (400, 999, 0.085, 0.085),
]

_CLIFF_TABLE = [
    (0,   150, 0.00,  0.00),
    (150, 200, 0.00,  0.02),
    (200, 250, 0.02,  0.04),
    (250, 300, 0.04,  0.06),
    (300, 400, 0.06,  0.085),
]


def estimate_aca_premium(
    magi: float,
    year: int,
    household_size: int = 2,
    inflation_rate: float = 0.03,
    benchmark_override: float = None,
    arp_extended: bool = True,
) -> dict:
    """Estimate annual ACA premium after subsidies.

    Returns dict with premium, subsidy, benchmark, fpl_pct, contribution_pct.
    """
    years_from_base = max(0, year - 2025)
    fpl = _FPL_2_PERSON_2025 * (1 + _FPL_ANNUAL_GROWTH) ** years_from_base
    benchmark = (
        (benchmark_override or _BENCHMARK_SILVER_2025)
        * (1 + _BENCHMARK_ANNUAL_GROWTH) ** years_from_base
    )

    fpl_pct = (magi / fpl) * 100 if fpl > 0 else 999.0

    table = _ARP_TABLE if arp_extended else _CLIFF_TABLE

    if not arp_extended and fpl_pct > 400:
        return {
            "premium": benchmark,
            "subsidy": 0.0,
            "benchmark": benchmark,
            "fpl_pct": fpl_pct,
            "contribution_pct": None,
        }

    contribution_pct = 0.0
    for lo, hi, lo_pct, hi_pct in table:
        if lo <= fpl_pct < hi:
            frac = (fpl_pct - lo) / (hi - lo) if hi > lo else 0.0
            contribution_pct = lo_pct + frac * (hi_pct - lo_pct)
            break
    else:
        contribution_pct = table[-1][3]

    expected_contribution = magi * contribution_pct
    subsidy = max(0.0, benchmark - expected_contribution)
    premium = max(0.0, benchmark - subsidy)

    return {
        "premium": premium,
        "subsidy": subsidy,
        "benchmark": benchmark,
        "fpl_pct": fpl_pct,
        "contribution_pct": contribution_pct,
    }
