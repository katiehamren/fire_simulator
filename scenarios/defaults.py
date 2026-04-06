"""
Preset scenario templates — complete snapshots of all sidebar widget keys.
Loaded via the Scenarios panel; cannot be deleted by the user.
"""

# Each entry is a full set of sidebar widget key → raw widget value mappings.
# Slider values are the display value (before dividing by 100).

_BASE = {
    # People & Timeline
    "u_birth": 1989, "u_stop": 2029,
    "s_birth": 1987, "s_stop": 2036,
    "end_yr": 2075,
    # W2 & Sole Prop Income
    "u_w2": 120_000, "u_raise": 3.0,
    "s_w2": 150_000, "s_raise": 3.0,
    "sp_net": 40_000, "sp_gr": 5.0, "sp_years": 20,
    # Rental
    "rrent": 2_500, "rrg": 3.0, "rvac": 5.0, "rexp": 30.0,
    # Account Balances
    "u401p": 150_000, "u401r": 0, "utira": 0, "urira": 30_000,
    "s401p": 250_000, "s401r": 0, "stira": 0, "srira": 20_000,
    "brok": 100_000, "hsa": 15_000, "cash_bal": 50_000,
    # Contributions (401k auto-maxed; solo 401k off by default)
    "uirac": 7_000, "sirac": 7_000, "brokc": 20_000,
    "solo_ee": 0, "solo_ee_type": "pretax", "solo_er_pct": 0, "solo_er_type": "pretax",
    # Assumptions
    "taxr": 22.0, "mret_preset": "Base (7%)", "inf": 3.0,
    "spend": 90_000, "hccost": 24_000,
}

PRESETS: dict[str, dict] = {
    "Base Case": _BASE,
    "User retires 2026 — aggressive growth": {
        **_BASE,
        "u_stop": 2026,
        "mret_preset": "Optimistic (9%)",
    },
    "User retires 2028 — conservative returns": {
        **_BASE,
        "u_stop": 2028,
        "mret_preset": "Conservative (5%)",
    },
    "Both retire 2030 — base returns": {
        **_BASE,
        "u_stop": 2030,
        "s_stop": 2030,
    },
}
