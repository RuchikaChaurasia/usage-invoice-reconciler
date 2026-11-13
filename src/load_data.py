"""Load the generated CSVs into the raw MySQL tables. Safe to re-run (empties tables first)."""
from pathlib import Path

import pandas as pd
import pymysql

DATA = Path(__file__).resolve().parent.parent / "data"
TABLES = ["customers", "usage_events", "invoices"]   # parents first (foreign keys)

conn = pymysql.connect(host="127.0.0.1", port=3307, user="root",
                       password="rootpw", database="recon")
with conn.cursor() as cur:
    for t in reversed(TABLES):                        # children first when deleting
        cur.execute(f"DELETE FROM {t}")
    for t in TABLES:
        df = pd.read_csv(DATA / f"{t}.csv")
        cols = ", ".join(df.columns)
        marks = ", ".join(["%s"] * len(df.columns))
        rows = df.astype(object).where(df.notna(), None).values.tolist()
        cur.executemany(f"INSERT INTO {t} ({cols}) VALUES ({marks})", rows)
        print(f"{t}: {len(rows)} rows loaded")
conn.commit()
conn.close()
