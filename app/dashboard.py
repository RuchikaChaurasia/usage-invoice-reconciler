"""Exceptions dashboard for a finance user. SYNTHETIC demo data only."""
from datetime import datetime
from decimal import Decimal

import pandas as pd
import pymysql
import streamlit as st

st.set_page_config(page_title="Usage-to-Invoice Reconciliation", layout="wide")

LABELS = {
    "missing_invoice": "Missing invoice",
    "mismatched_hours": "Mismatched hours",
    "late_arriving_usage": "Late-arriving usage",
    "duplicate_usage": "Duplicate usage",
}
WHAT_IT_MEANS = {
    "missing_invoice": "The customer used GPUs this month but no invoice exists. "
                       "Dollars at risk = the full usage value that was never billed.",
    "mismatched_hours": "An invoice exists, but its hours differ from the usage records. "
                        "Dollars at risk = the hour difference x the hourly rate.",
    "late_arriving_usage": "Some usage was recorded after the invoice was issued, so the invoice "
                           "could not include it. Dollars at risk = value of the late usage.",
    "duplicate_usage": "The same instance-day appears more than once in the usage feed. The extra "
                       "copies are ignored in the comparison. Dollars at risk = value of the extra copies.",
}


@st.cache_data(ttl=60)
def run(sql, params=None):
    """Run a query and return a DataFrame. Cached for 60 seconds."""
    conn = pymysql.connect(host="127.0.0.1", port=3307, user="root",
                           password="rootpw", database="recon")
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
    finally:
        conn.close()
    df = pd.DataFrame(rows, columns=cols)
    for c in df.columns:                      # MySQL DECIMAL -> float for display
        if df[c].map(lambda x: isinstance(x, Decimal)).any():
            df[c] = df[c].astype(float)
    return df


def totals_tie_out():
    """Same idea as the pytest tie-out checks: nothing lost or invented."""
    a = run("SELECT SUM(gpu_hours) AS v FROM usage_events").v.iloc[0]
    b = run("SELECT SUM(usage_hours_total + dup_hours) AS v FROM v_usage_by_key").v.iloc[0]
    c = run("SELECT SUM(billed_amount) AS v FROM invoices").v.iloc[0]
    d = run("SELECT SUM(billed_amount) AS v FROM v_reconciliation").v.iloc[0]
    return abs(a - b) < 0.01 and abs(c - d) < 0.01


# ---------------- Data ----------------
exc = run("""
    SELECT e.exception_type, e.customer_id, c.customer_name, c.segment,
           e.billing_month, e.gpu_type, e.invoice_id,
           e.hours_impacted, e.dollars_at_risk, e.rows_affected
    FROM v_exceptions e
    JOIN customers c ON c.customer_id = e.customer_id
""")

# ---------------- Sidebar filters ----------------
st.sidebar.header("Filters")
months = sorted(exc.billing_month.unique())
sel_months = st.sidebar.multiselect("Billing month", months, default=months)
types = list(LABELS)
sel_types = st.sidebar.multiselect("Exception type", types, default=types,
                                   format_func=LABELS.get)
gpus = sorted(exc.gpu_type.unique())
sel_gpus = st.sidebar.multiselect("GPU type", gpus, default=gpus)
sel_cust = st.sidebar.selectbox("Customer", ["All"] + sorted(exc.customer_name.unique()))
if st.sidebar.button("Refresh data"):
    st.cache_data.clear()

f = exc[exc.billing_month.isin(sel_months)
        & exc.exception_type.isin(sel_types)
        & exc.gpu_type.isin(sel_gpus)]
if sel_cust != "All":
    f = f[f.customer_name == sel_cust]
f = f.sort_values("dollars_at_risk", ascending=False)

# ---------------- Sticky header: title + KPIs stay visible while scrolling ----------------
st.markdown("""
<style>
.st-key-sticky_header {
    position: sticky;
    top: 2.875rem;
    z-index: 999;
    background-color: #ffffff;
    padding: 0.5rem 0 0.75rem 0;
    border-bottom: 1px solid rgba(128, 128, 128, 0.3);
}
@media (prefers-color-scheme: dark) {
    .st-key-sticky_header { background-color: #0e1117; }
}
</style>
""", unsafe_allow_html=True)

by_type = f.groupby("exception_type").dollars_at_risk.sum()

with st.container(key="sticky_header"):
    st.markdown("### Usage-to-Invoice Reconciliation")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total dollars at risk", f"${f.dollars_at_risk.sum():,.2f}")
    k2.metric("Exceptions", len(f))
    k3.metric("Customers affected", f.customer_id.nunique())
    k4.metric("Largest category", LABELS[by_type.idxmax()] if not by_type.empty else "-")

st.caption("Synthetic demo data. Not real customer or billing data.")
if totals_tie_out():
    st.success("Totals tie out: usage hours and invoice dollars reconcile between raw tables and views.")
else:
    st.error("Totals do NOT tie out. Do not trust these numbers until the data checks pass.")
st.caption(f"Last refreshed: {datetime.now():%Y-%m-%d %H:%M:%S}")

if not by_type.empty:
    st.bar_chart(by_type.rename(index=LABELS))

# ---------------- Exceptions table + export ----------------
st.subheader("Exceptions, largest dollars first")
show = f[["exception_type", "customer_name", "segment", "billing_month", "gpu_type",
          "invoice_id", "hours_impacted", "dollars_at_risk"]].copy()
show["exception_type"] = show.exception_type.map(LABELS)
show = show.rename(columns={
    "exception_type": "Exception", "customer_name": "Customer", "segment": "Segment",
    "billing_month": "Month", "gpu_type": "GPU", "invoice_id": "Invoice",
    "hours_impacted": "Hours impacted", "dollars_at_risk": "Dollars at risk"})
st.dataframe(show, hide_index=True,
             column_config={"Dollars at risk": st.column_config.NumberColumn(format="$%.2f")})
st.download_button("Download these exceptions as CSV",
                   show.to_csv(index=False).encode("utf-8"), "exceptions.csv", "text/csv")

# ---------------- Drill-down ----------------
st.subheader("Drill down")
if f.empty:
    st.info("No exceptions match the current filters.")
else:
    opts = f.reset_index(drop=True)
    labels = [f"{r.customer_name} | {r.billing_month} | {r.gpu_type} | "
              f"{LABELS[r.exception_type]} | ${r.dollars_at_risk:,.2f}"
              for r in opts.itertuples()]
    i = st.selectbox("Pick an exception", range(len(opts)), format_func=lambda n: labels[n])
    r = opts.iloc[i]
    st.info(WHAT_IT_MEANS[r.exception_type])

    key = (int(r.customer_id), r.billing_month, r.gpu_type)
    recon = run("""SELECT billed_hours, usage_hours_on_time, late_hours, dup_hours
                   FROM v_reconciliation
                   WHERE customer_id=%s AND billing_month=%s AND gpu_type=%s""", key).iloc[0]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Billed hours", "No invoice" if pd.isna(recon.billed_hours) else f"{recon.billed_hours:,.0f}")
    m2.metric("Usage hours (on time)", f"{recon.usage_hours_on_time:,.0f}")
    m3.metric("Late hours", f"{recon.late_hours:,.0f}")
    m4.metric("Duplicate hours", f"{recon.dup_hours:,.0f}")

    rows = run("""SELECT usage_id, instance_id, usage_date, gpu_hours, rn, is_late, ingested_at
                  FROM v_usage_ranked
                  WHERE customer_id=%s AND billing_month=%s AND gpu_type=%s
                  ORDER BY usage_date, rn""", key)
    if not rows.empty:
        rows["status"] = rows.apply(
            lambda x: "Duplicate (not counted)" if x.rn > 1
            else ("Late (after invoice)" if x.is_late == 1 else "Counted"), axis=1)
        only_problem = st.checkbox(
            "Show only rows that explain the exception",
            value=r.exception_type in ("duplicate_usage", "late_arriving_usage"))
        if only_problem:
            rows = rows[rows.status != "Counted"]
        st.caption("Underlying usage records for this customer, month, and GPU type")
        st.dataframe(rows[["usage_id", "instance_id", "usage_date", "gpu_hours",
                           "status", "ingested_at"]], hide_index=True)
