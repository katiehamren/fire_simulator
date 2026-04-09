"""Saved scenario persistence and preset loading."""

import json
import re
from datetime import datetime
from pathlib import Path

import streamlit as st

# Resolved from package: retirement_simulator/saved_scenarios/
SAVED_DIR = Path(__file__).resolve().parent.parent / "saved_scenarios"

# All sidebar widget keys that represent simulation inputs (excludes UI-only keys).
SCENARIO_KEYS = [
    "u_birth", "u_stop", "s_birth", "s_stop", "end_yr",
    "u_w2", "u_raise", "s_w2", "s_raise",
    "sp_net", "sp_gr", "sp_years",
    "rrent", "rrg", "rvac", "rexp", "rpropval", "rland",
    "u401p", "u401r", "utira", "urira",
    "s401p", "s401r", "stira", "srira",
    "brok", "hsa", "cash_bal",
    "u401k_mode", "u401k_amt", "u401k_pct",
    "s401k_mode", "s401k_amt", "s401k_pct",
    "uirac", "sirac", "brokc", "hsa_mode", "hsa_yr",
    "solo_ee", "solo_ee_type", "solo_er_pct", "solo_er_type",
    "mret_preset", "mret", "inf", "bbasis", "spend",
    "hc_mode", "hc_flat", "aca_bench", "aca_arp", "aca_oop",
    "spend_override_enabled", "spend_override_year", "spend_override_pct",
    "rc_enabled", "rc_start", "rc_end", "rc_amount", "rc_source",
    "sepp_enabled", "sepp_start", "sepp_account", "sepp_rate",
]


def _slug(name: str) -> str:
    """Convert a scenario name to a safe filename stem."""
    return re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "_")


def list_saved() -> list[str]:
    SAVED_DIR.mkdir(exist_ok=True)
    names = []
    for p in sorted(SAVED_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            names.append(data.get("name", p.stem))
        except Exception:
            pass
    return names


def _json_default(obj):
    """Convert numpy scalars (returned by Streamlit widgets) to JSON-native types."""
    if hasattr(obj, 'item'):   # numpy scalar → Python int/float/bool
        return obj.item()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def save_scenario(name: str) -> None:
    SAVED_DIR.mkdir(exist_ok=True)
    payload = {
        "name": name,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": {k: st.session_state[k] for k in SCENARIO_KEYS if k in st.session_state},
    }
    (SAVED_DIR / f"{_slug(name)}.json").write_text(json.dumps(payload, indent=2, default=_json_default))


def load_saved(name: str) -> dict:
    for p in SAVED_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            if data.get("name") == name:
                return data["inputs"]
        except Exception:
            pass
    return {}


def delete_saved(name: str) -> None:
    for p in SAVED_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            if data.get("name") == name:
                p.unlink()
                return
        except Exception:
            pass


def apply_inputs(inputs: dict) -> None:
    """Load a dict of widget key→value into session state and rerun.

    Only keys in SCENARIO_KEYS are applied so obsolete keys (e.g. legacy taxr)
    in older saved JSON are ignored.  Handles migration for scenarios saved
    before the ACA healthcare model was added.
    """
    data = dict(inputs)

    # Migration: old scenarios have "hccost" but no "hc_mode".
    # Treat them as flat-cost healthcare using the saved hccost value.
    if "hc_mode" not in data and "hccost" in data:
        data["hc_mode"] = "flat"
        data["hc_flat"] = data["hccost"]

    st.session_state.update({k: v for k, v in data.items() if k in SCENARIO_KEYS})
    st.rerun()
