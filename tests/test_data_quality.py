"""Data quality checks (pytest). Same idea as dbt tests: not_null, unique, totals tie out."""
from pathlib import Path

import pandas as pd
import pymysql
import pytest

PLANTED = Path(__file__).resolve().parent.parent / "data" / "planted_errors.csv"


@pytest.fixture(scope="module")
def conn():
    c = pymysql.connect(host="127.0.0.1", port=3307, user="root",
                        password="rootpw", database="recon")
    yield c
    c.close()


def scalar(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return float(cur.fetchone()[0] or 0)


def test_invoice_grain_is_unique(conn):
    """One invoice per customer x month x GPU type."""
    dups = scalar(conn, """SELECT COUNT(*) FROM (
        SELECT customer_id, billing_month, gpu_type FROM invoices
        GROUP BY 1,2,3 HAVING COUNT(*) > 1) d""")
    assert dups == 0


def test_deduped_usage_has_unique_keys(conn):
    """After removing duplicates (rn = 1), each instance-day appears once."""
    dups = scalar(conn, """SELECT COUNT(*) FROM (
        SELECT customer_id, instance_id, usage_date FROM v_usage_ranked
        WHERE rn = 1 GROUP BY 1,2,3 HAVING COUNT(*) > 1) d""")
    assert dups == 0


def test_reconciliation_grain_is_unique(conn):
    """The reconciliation view has exactly one row per key (no join fan-out)."""
    total = scalar(conn, "SELECT COUNT(*) FROM v_reconciliation")
    distinct = scalar(conn, """SELECT COUNT(*) FROM (
        SELECT DISTINCT customer_id, billing_month, gpu_type FROM v_reconciliation) d""")
    assert total == distinct


def test_no_nulls_in_exceptions(conn):
    nulls = scalar(conn, """SELECT COUNT(*) FROM v_exceptions
        WHERE exception_type IS NULL OR customer_id IS NULL
           OR billing_month IS NULL OR dollars_at_risk IS NULL""")
    assert nulls == 0


def test_usage_hours_tie_out(conn):
    """Raw hours = kept hours + duplicate hours. Nothing lost or invented."""
    raw = scalar(conn, "SELECT SUM(gpu_hours) FROM usage_events")
    rolled = scalar(conn, "SELECT SUM(usage_hours_total + dup_hours) FROM v_usage_by_key")
    assert raw == rolled


def test_invoice_totals_tie_out(conn):
    """Every invoice dollar in the raw table appears in the reconciliation view."""
    raw = scalar(conn, "SELECT SUM(billed_amount) FROM invoices")
    in_view = scalar(conn, "SELECT SUM(billed_amount) FROM v_reconciliation")
    assert raw == in_view


def test_exceptions_match_planted_answer_key(conn):
    """The views must find what the generator planted, to the cent."""
    key = pd.read_csv(PLANTED).groupby("error_type")["dollars_at_risk"].sum()
    with conn.cursor() as cur:
        cur.execute("SELECT exception_type, SUM(dollars_at_risk) FROM v_exceptions GROUP BY 1")
        found = {t: float(d) for t, d in cur.fetchall()}
    for err_type, expected in key.items():
        assert abs(found.get(err_type, 0) - expected) < 0.02, err_type


def test_invoice_without_usage_is_flagged(conn):
    """An invoice with no matching usage must appear in v_exceptions. Rolled back afterwards."""
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO invoices VALUES
            ('INV-TEST1', 1, '2026-11', 'H100', 10, 29.90, '2026-12-05')""")
        cur.execute("""SELECT dollars_at_risk FROM v_exceptions
            WHERE exception_type='invoice_without_usage' AND invoice_id='INV-TEST1'""")
        row = cur.fetchone()
    conn.rollback()
    assert row is not None and abs(float(row[0]) - 29.90) < 0.01
