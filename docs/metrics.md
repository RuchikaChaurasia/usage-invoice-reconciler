# Metric definitions

> **Hypothetical scenario on synthetic data.** Owners, processes, and thresholds below are
> assumptions I would validate with stakeholders. They are not descriptions of how any real company works.

**Rule:** each metric has one definition, one grain, one source, and one owner. If a number is
shown anywhere else, it must come from the source listed here.

## Grain (the level a row represents)

| Object | Grain | Key |
|---|---|---|
| `usage_events` (raw) | one row per instance per day | `usage_id` (instance + day can repeat when duplicated) |
| `invoices` (raw) | one row per customer x billing month x GPU type | `invoice_id` |
| `v_usage_by_key` | one row per customer x billing month x GPU type | matches the invoice grain |
| `v_reconciliation` | one row per customer x billing month x GPU type | same key; tested for uniqueness |
| `v_exceptions` | one row per exception found | exception type + key |

Usage is daily and invoices are monthly, so usage is rolled up to the invoice grain before any
comparison.

## Metrics

| Metric | Definition | Source | Owner (assumed) |
|---|---|---|---|
| Usage hours (on time) | Sum of GPU hours for de-duplicated usage rows ingested before the invoice date | `v_usage_by_key.usage_hours_on_time` | Data / billing ops |
| Billed hours | Hours on the invoice | `invoices.billed_hours` | Finance |
| Hours difference | Billed hours minus on-time usage hours | `v_reconciliation.hours_diff` | Finance |
| Duplicate hours | Hours in extra copies of the same instance-day (second copy onward) | `v_usage_by_key.dup_hours` | Data / billing ops |
| Late hours | Hours ingested on or after the invoice date | `v_usage_by_key.late_hours` | Data / billing ops |
| Dollars at risk (per exception) | Hours impacted x hourly rate, by type (see below) | `v_exceptions.dollars_at_risk` | Finance |
| Total dollars at risk | Sum of dollars at risk across the exceptions shown | dashboard, from `v_exceptions` | Finance |
| Exceptions | Count of rows in `v_exceptions` | `v_exceptions` | Finance |
| Customers affected | Distinct customers with at least one exception | `v_exceptions` | Finance |
| Totals tie out | Raw usage hours = kept + duplicate hours, and raw invoice dollars = invoice dollars in the reconciliation view, plus invoices with no usage | dashboard badge, pytest | Data |

## Exception types

| Type | Rule | Dollars at risk |
|---|---|---|
| Missing invoice | Usage exists for a customer, month, and GPU type, but no invoice row | Total usage hours x rate |
| Mismatched hours | Invoice exists, but billed hours differ from on-time usage | Absolute hour difference x rate |
| Late-arriving usage | Usage ingested on or after the invoice date | Late hours x rate |
| Duplicate usage | Same customer, instance, and day appears more than once | Duplicate hours x rate |
| Invoice without usage | Invoice exists, but there is no usage for that customer, month, and GPU type | Billed hours x rate |

## Assumptions to confirm with stakeholders
1. **Invoice date** is assumed to be the 5th of the month after the billing month. "Late" is measured against it.
2. **One rate per GPU type** per month. Real pricing (discounts, commitments, credits) is out of scope.
3. **Duplicates** are identified by customer + instance + day, and the lowest `usage_id` is kept.
4. **Overlap:** one customer/month/GPU key could be both late and duplicated. The total is a sum of
   flagged amounts, not a count of unique dollars. In the synthetic data the planted errors do not
   overlap, so the total is exact. In real data I would agree on how to de-duplicate dollars.
5. **Tolerance:** any hour difference is flagged. Finance may prefer a threshold (for example, ignore
   differences under a small amount). That is a question for the business, not a coding decision.

## Questions I would ask before treating these as final
- Which system is the source of truth for usage, and how often does it refresh?
- When is an invoice final, and can invoices be re-issued?
- Are credits, discounts, or reserved-capacity commitments billed outside this comparison?
- Who acts on each exception type, and how quickly?
