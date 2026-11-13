"""Exceptions dashboard for a finance user. SYNTHETIC demo data only."""
from datetime import datetime
from decimal import Decimal

import pandas as pd
import pymysql
import streamlit as st

st.set_page_config(page_title="Usage-to-Invoice Reconciliation", layout="wide")

# Tighten the empty space above the sidebar title (cosmetic)
st.markdown("""
<style>
[data-testid="stSidebarHeader"] { height: 2.25rem; min-height: 0; padding-bottom: 0; }
[data-testid="stSidebarUserContent"] { padding-top: 0.25rem; }
</style>
""", unsafe_allow_html=True)

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
summary_box = st.sidebar.container()
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

# ---------------- Header, trust signals, KPIs ----------------
by_type = f.groupby("exception_type").dollars_at_risk.sum()

# Compact summary at the top of the sidebar. The sidebar stays put while the page scrolls.
with summary_box:
    st.markdown("## Usage-to-Invoice Reconciliation")
    st.caption("Synthetic demo data")
    st.markdown("**At a glance**")
    st.markdown(f"### ${f.dollars_at_risk.sum():,.0f} at risk")
    st.caption(f"{len(f)} exceptions across {f.customer_id.nunique()} customers")
    st.divider()

st.title("Usage-to-Invoice Reconciliation")
st.caption("Synthetic demo data. Not real customer or billing data.")
if totals_tie_out():
    st.success("Totals tie out: usage hours and invoice dollars reconcile between raw tables and views.")
else:
    st.error("Totals do NOT tie out. Do not trust these numbers until the data checks pass.")
st.caption(f"Last refreshed: {datetime.now():%Y-%m-%d %H:%M:%S}")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total dollars at risk", f"${f.dollars_at_risk.sum():,.2f}")
k2.metric("Exceptions", len(f))
k3.metric("Customers affected", f.customer_id.nunique())
with k4:
    top = LABELS[by_type.idxmax()] if not by_type.empty else "-"
    top_val = f"${by_type.max():,.0f}" if not by_type.empty else ""
    st.markdown(
        f"<div style='font-size:0.875rem;margin-bottom:0.25rem'>Largest category</div>"
        f"<div style='font-size:1.75rem;line-height:1.2;word-break:break-word'>{top}</div>"
        f"<div style='font-size:0.875rem;opacity:0.7'>{top_val}</div>",
        unsafe_allow_html=True)

if not by_type.empty:
    import altair as alt
    chart_df = (by_type.rename(index=LABELS).rename("Dollars at risk")
                .reset_index().rename(columns={"exception_type": "Exception"}))
    base = alt.Chart(chart_df).encode(
        y=alt.Y("Exception:N", sort="-x", title=None, axis=alt.Axis(labelLimit=250)),
        x=alt.X("Dollars at risk:Q", title=None, axis=alt.Axis(format="$,.0f")),
    )
    bars = base.mark_bar()
    labels = base.mark_text(align="left", dx=4).encode(
        text=alt.Text("Dollars at risk:Q", format="$,.0f"))
    st.altair_chart((bars + labels).properties(height=200, width="container"))

# ---------------- Exceptions table + export ----------------
st.subheader("Exceptions, largest dollars first")
show = f[["exception_type", "customer_name", "segment", "billing_month", "gpu_type",
          "invoice_id", "hours_impacted", "dollars_at_risk"]].copy()
show["exception_type"] = show.exception_type.map(LABELS)
show = show.rename(columns={
    "exception_type": "Exception", "customer_name": "Customer", "segment": "Segment",
    "billing_month": "Month", "gpu_type": "GPU", "invoice_id": "Invoice",
    "hours_impacted": "Hours impacted", "dollars_at_risk": "Dollars at risk"})
show["Invoice"] = show["Invoice"].fillna("No invoice")
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
