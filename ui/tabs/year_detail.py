"""Year-by-year detail and export tab."""
import io

import pandas as pd
import streamlit as st

from ..formatting import fmt


def render_detail(df: pd.DataFrame):
    st.header("Year-by-Year Detail")

    display_cols = [
        "year", "user_age", "spouse_age",
        "user_w2_gross", "spouse_w2_gross", "sole_prop_net", "rental_cashflow",
        "taxes_paid", "total_net_income",
        "spending", "healthcare", "total_expenses", "net_cashflow",
        "brokerage", "total_retirement_accounts", "total_net_worth",
        "early_withdrawal_amount", "user_rmd", "spouse_rmd", "plan_solvent",
    ]

    col_labels = {
        "year": "Year", "user_age": "User Age", "spouse_age": "Spouse Age",
        "user_w2_gross": "User W2", "spouse_w2_gross": "Spouse W2",
        "sole_prop_net": "Sole Prop", "rental_cashflow": "Rental CF",
        "taxes_paid": "Taxes", "total_net_income": "Net Income",
        "spending": "Spending", "healthcare": "Healthcare",
        "total_expenses": "Expenses", "net_cashflow": "Cash Flow",
        "brokerage": "Brokerage", "total_retirement_accounts": "Retirement",
        "total_net_worth": "Net Worth",
        "early_withdrawal_amount": "Early W/D",
        "user_rmd": "User RMD", "spouse_rmd": "Spouse RMD",
        "plan_solvent": "Solvent",
    }

    currency_cols = [
        "user_w2_gross", "spouse_w2_gross", "sole_prop_net", "rental_cashflow",
        "taxes_paid", "total_net_income", "spending", "healthcare", "total_expenses",
        "net_cashflow", "brokerage", "total_retirement_accounts",
        "total_net_worth", "early_withdrawal_amount", "user_rmd", "spouse_rmd",
    ]

    display_df = df[display_cols].copy()
    display_df.rename(columns=col_labels, inplace=True)

    def highlight(row):
        if not row["Solvent"]:
            return ["background-color: #fee2e2; color: #991b1b"] * len(row)
        if row["User RMD"] > 0 or row["Spouse RMD"] > 0:
            return ["background-color: #ede9fe; color: #5b21b6"] * len(row)
        if row["Early W/D"] > 0:
            return ["background-color: #fef9c3; color: #854d0e"] * len(row)
        return [""] * len(row)

    format_map = {col_labels[c]: "${:,.0f}" for c in currency_cols}

    styled = (
        display_df.style
        .apply(highlight, axis=1)
        .format(format_map, na_rep="—")
    )

    st.dataframe(styled, width="stretch", height=520)
    st.caption(
        "🟡 Yellow row = early retirement account withdrawal (10% IRS penalty applies). "
        "🟣 Purple row = RMD year (mandatory withdrawal from pre-tax accounts at age 73+). "
        "🔴 Red row = plan insolvency (expenses exceed all available assets)."
    )

    st.divider()
    st.subheader("Export")
    col_csv, col_xlsx = st.columns(2)

    csv_bytes = display_df.to_csv(index=False).encode("utf-8")
    col_csv.download_button(
        "Download CSV",
        data=csv_bytes,
        file_name="retirement_simulation.csv",
        mime="text/csv",
        width="stretch",
    )

    xlsx_buf = io.BytesIO()
    with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
        display_df.to_excel(writer, index=False, sheet_name="Simulation")
    col_xlsx.download_button(
        "Download Excel",
        data=xlsx_buf.getvalue(),
        file_name="retirement_simulation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
