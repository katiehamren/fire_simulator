"""Shared display helpers for Streamlit tabs."""

import pandas as pd

from engine.models import CURRENT_YEAR


def fmt(n: float) -> str:
    return f"${n:,.0f}"


def to_df(snapshots, inflation_rate: float = 0.03) -> pd.DataFrame:
    df = pd.DataFrame([vars(s) for s in snapshots])
    df["inflation_factor"] = (1 + inflation_rate) ** (df["year"] - CURRENT_YEAR)
    return df


COLORS = {
    "user_401k_pretax":   "#1e3a5f",
    "user_401k_roth":     "#2563eb",
    "user_trad_ira":      "#0e7490",
    "user_roth_ira":      "#22d3ee",
    "spouse_401k_pretax": "#14532d",
    "spouse_401k_roth":   "#16a34a",
    "spouse_trad_ira":    "#15803d",
    "spouse_roth_ira":    "#4ade80",
    "brokerage":           "#d97706",
    "hsa":                 "#7c3aed",
    "cash":                "#9ca3af",
}


def person_ui_label(internal_key: str) -> str:
    """Display label for internal person keys (`user` / `spouse`) in the UI."""
    return {"user": "User", "spouse": "Spouse"}.get(internal_key, internal_key)
