"""Generate SYNTHETIC GPU usage + invoice data with planted errors.
All names, rates, and volumes are made up. Nothing here reflects any real company's billing."""
import random
from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

SEED = 42
OUT = Path(__file__).resolve().parent.parent / "data"
MONTHS = [(2026, 8), (2026, 9), (2026, 10)]
RATES = {"H100": 2.99, "A100": 1.79, "B200": 4.99}   # illustrative, made up
N_CUSTOMERS = 25
KEY = ["customer_id", "billing_month", "gpu_type"]   # invoice grain

random.seed(SEED)


def month_label(y, m):
    return f"{y}-{m:02d}"


def invoice_date_for(y, m):
    return date(y + (m == 12), m % 12 + 1, 5)        # invoiced on the 5th of next month


def at_midnight(d):
    return datetime.combine(d, datetime.min.time())


def key_mask(df, key):
    return (df.customer_id == key[0]) & (df.billing_month == key[1]) & (df.gpu_type == key[2])


# ---- 1. Clean customers + daily usage ---------------------------------
customers, usage, usage_id = [], [], 1
for cid in range(1, N_CUSTOMERS + 1):
    customers.append({"customer_id": cid, "customer_name": f"Customer {cid:02d}",
                      "segment": random.choice(["Startup", "Enterprise", "Research"])})
    for n in range(random.randint(2, 4)):            # 2-4 GPU instances per customer
        instance_id, gpu = f"i-{cid:03d}-{n + 1}", random.choice(list(RATES))
        for y, m in MONTHS:
            for day in range(1, monthrange(y, m)[1] + 1):
                if random.random() < 0.10:           # instance idle ~10% of days
                    continue
                d = date(y, m, day)
                usage.append({"usage_id": usage_id, "customer_id": cid, "instance_id": instance_id,
                              "gpu_type": gpu, "usage_date": d, "billing_month": month_label(y, m),
                              "gpu_hours": random.randint(4, 24), "rate_per_hour": RATES[gpu],
                              "ingested_at": at_midnight(d + timedelta(days=1)) + timedelta(hours=2)})
                usage_id += 1
usage_df = pd.DataFrame(usage)

# ---- 2. Split invoice keys into disjoint groups, one per error type ----
keys = [tuple(k) for k in usage_df[KEY].drop_duplicates().values.tolist()]
random.shuffle(keys)
missing_keys, mismatch_keys, late_keys, dup_keys = keys[:4], keys[4:10], keys[10:16], keys[16:]
planted = []   # the answer key: what we planted, and the expected dollars at risk

# ---- 3. Late-arriving usage: last 2 days of the month land AFTER invoicing
late_ids = set()
for key in late_keys:
    y, m = map(int, key[1].split("-"))
    arrival = at_midnight(invoice_date_for(y, m) + timedelta(days=3))
    for idx, r in usage_df[key_mask(usage_df, key)].sort_values("usage_date").tail(2).iterrows():
        usage_df.loc[idx, "ingested_at"] = arrival
        late_ids.add(int(r.usage_id))
        planted.append({"error_type": "late_arriving_usage", "customer_id": key[0],
                        "billing_month": key[1], "gpu_type": key[2], "usage_id": int(r.usage_id),
                        "dollars_at_risk": round(r.gpu_hours * r.rate_per_hour, 2)})

# ---- 4. Build invoices from what had arrived by invoice time (no dups yet)
invoices = {}
for i, key in enumerate(sorted(keys), start=1):
    sub = usage_df[key_mask(usage_df, key) & ~usage_df.usage_id.isin(late_ids)]
    hours = int(sub.gpu_hours.sum())
    y, m = map(int, key[1].split("-"))
    invoices[key] = {"invoice_id": f"INV-{i:05d}", "customer_id": key[0], "billing_month": key[1],
                     "gpu_type": key[2], "billed_hours": hours,
                     "billed_amount": round(hours * RATES[key[2]], 2),
                     "invoice_date": invoice_date_for(y, m)}

# ---- 5. Mismatched hours: invoice hours are off from usage
for key in mismatch_keys:
    delta = random.choice([-12, -8, 8, 15])
    inv = invoices[key]
    inv["billed_hours"] += delta
    inv["billed_amount"] = round(inv["billed_hours"] * RATES[key[2]], 2)
    planted.append({"error_type": "mismatched_hours", "customer_id": key[0], "billing_month": key[1],
                    "gpu_type": key[2], "invoice_id": inv["invoice_id"],
                    "dollars_at_risk": round(abs(delta) * RATES[key[2]], 2)})

# ---- 6. Missing invoices: usage exists, invoice row is dropped
for key in missing_keys:
    inv = invoices.pop(key)
    planted.append({"error_type": "missing_invoice", "customer_id": key[0], "billing_month": key[1],
                    "gpu_type": key[2], "invoice_id": inv["invoice_id"],
                    "dollars_at_risk": inv["billed_amount"]})

# ---- 7. Duplicate usage rows: exact copy of an event with a new usage_id
pool = usage_df[usage_df[KEY].apply(tuple, axis=1).isin(dup_keys)]
dups, next_id = [], usage_df.usage_id.max() + 1
for _, r in pool.sample(40, random_state=SEED).iterrows():
    row = r.to_dict()
    row["usage_id"] = int(next_id)
    next_id += 1
    dups.append(row)
    planted.append({"error_type": "duplicate_usage", "customer_id": r.customer_id,
                    "billing_month": r.billing_month, "gpu_type": r.gpu_type,
                    "usage_id": row["usage_id"],
                    "dollars_at_risk": round(r.gpu_hours * r.rate_per_hour, 2)})
usage_df = pd.concat([usage_df, pd.DataFrame(dups)], ignore_index=True)

# ---- 8. Write CSVs -----------------------------------------------------
OUT.mkdir(exist_ok=True)
pd.DataFrame(customers).to_csv(OUT / "customers.csv", index=False)
usage_df.sort_values("usage_id").to_csv(OUT / "usage_events.csv", index=False)
pd.DataFrame(invoices.values()).sort_values("invoice_id").to_csv(OUT / "invoices.csv", index=False)
planted_df = pd.DataFrame(planted)
planted_df.to_csv(OUT / "planted_errors.csv", index=False)

print(f"customers={len(customers)} usage_rows={len(usage_df)} invoices={len(invoices)}")
print(planted_df.groupby("error_type").agg(n=("dollars_at_risk", "size"),
                                           dollars=("dollars_at_risk", "sum")).round(2))
