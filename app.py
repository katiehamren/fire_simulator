"""
Early Retirement Simulator — Streamlit web app.

Run with:  streamlit run app.py

UI layout and tab renderers live under ``ui/`` (see ``ui/main.py``, ``ui/tabs/``).

Key simplifications in v1:
- Federal tax from progressive MFJ brackets (config) on W2 + sole prop income
- Roth IRA fully accessible for withdrawals (real rule: contributions only pre-59.5)
- No Social Security modeling
- No Roth conversion ladder optimization (Phase 2)
- Healthcare cost is a flat annual input; user should tune to their ACA/MAGI situation
"""
import chatbot.env  # noqa: F401 — load .env into os.environ before other imports

import streamlit as st

from ui.main import main

# ── PAGE CONFIG ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Early Retirement Simulator",
    page_icon="🏖️",
    layout="wide",
    initial_sidebar_state="expanded",
)


if __name__ == "__main__":
    main()
