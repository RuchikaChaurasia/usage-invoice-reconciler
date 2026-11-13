-- PORTABILITY NOTES (MySQL vs Snowflake):
--  * Date math: MySQL uses DATE_ADD/STR_TO_DATE; Snowflake uses DATEADD/TO_DATE.
--  * FULL OUTER JOIN: Snowflake supports it; MySQL needs LEFT JOIN UNION RIGHT JOIN.
--  * Window functions (ROW_NUMBER) work the same in both.

-- Layer 1: rank duplicate usage copies and flag late-arriving rows.
-- Duplicates = same customer + instance + day. Keep the lowest usage_id (rn = 1).
-- Late = ingested on/after the invoice date (assumed to be the 5th of the next month).
CREATE OR REPLACE VIEW v_usage_ranked AS
SELECT
  u.usage_id, u.customer_id, u.instance_id, u.gpu_type, u.usage_date,
  u.billing_month, u.gpu_hours, u.rate_per_hour, u.ingested_at,
  ROW_NUMBER() OVER (
    PARTITION BY u.customer_id, u.instance_id, u.usage_date
    ORDER BY u.usage_id
  ) AS rn,
  CASE WHEN u.ingested_at >= DATE_ADD(
         STR_TO_DATE(CONCAT(u.billing_month, '-05'), '%Y-%m-%d'), INTERVAL 1 MONTH)
       THEN 1 ELSE 0 END AS is_late
FROM usage_events u;

-- Layer 2: GRAIN = one row per customer x billing_month x gpu_type (the invoice grain).
CREATE OR REPLACE VIEW v_usage_by_key AS
SELECT
  customer_id, billing_month, gpu_type,
  MAX(rate_per_hour) AS rate_per_hour,
  COALESCE(SUM(CASE WHEN rn = 1 THEN gpu_hours END), 0)                 AS usage_hours_total,
  COALESCE(SUM(CASE WHEN rn = 1 AND is_late = 0 THEN gpu_hours END), 0) AS usage_hours_on_time,
  COALESCE(SUM(CASE WHEN rn = 1 AND is_late = 1 THEN gpu_hours END), 0) AS late_hours,
  SUM(CASE WHEN rn = 1 AND is_late = 1 THEN 1 ELSE 0 END)               AS late_rows,
  COALESCE(SUM(CASE WHEN rn > 1 THEN gpu_hours END), 0)                 AS dup_hours,
  SUM(CASE WHEN rn > 1 THEN 1 ELSE 0 END)                               AS dup_rows
FROM v_usage_ranked
GROUP BY customer_id, billing_month, gpu_type;

-- Layer 3: usage next to invoice. LEFT JOIN keeps usage with no invoice.
-- hours_diff compares the invoice to usage that had arrived by invoice day.
CREATE OR REPLACE VIEW v_reconciliation AS
SELECT
  k.customer_id, k.billing_month, k.gpu_type, k.rate_per_hour,
  k.usage_hours_total, k.usage_hours_on_time,
  k.late_hours, k.late_rows, k.dup_hours, k.dup_rows,
  i.invoice_id, i.billed_hours, i.billed_amount, i.invoice_date,
  i.billed_hours - k.usage_hours_on_time AS hours_diff
FROM v_usage_by_key k
LEFT JOIN invoices i
  ON  i.customer_id   = k.customer_id
  AND i.billing_month = k.billing_month
  AND i.gpu_type      = k.gpu_type;

-- Layer 4: one row per exception, with dollars at risk.
CREATE OR REPLACE VIEW v_exceptions AS
SELECT 'missing_invoice' AS exception_type, customer_id, billing_month, gpu_type,
       invoice_id, usage_hours_total AS hours_impacted,
       ROUND(usage_hours_total * rate_per_hour, 2) AS dollars_at_risk,
       1 AS rows_affected
FROM v_reconciliation
WHERE invoice_id IS NULL
UNION ALL
SELECT 'mismatched_hours', customer_id, billing_month, gpu_type,
       invoice_id, ABS(hours_diff),
       ROUND(ABS(hours_diff) * rate_per_hour, 2), 1
FROM v_reconciliation
WHERE invoice_id IS NOT NULL AND hours_diff <> 0
UNION ALL
SELECT 'late_arriving_usage', customer_id, billing_month, gpu_type,
       invoice_id, late_hours,
       ROUND(late_hours * rate_per_hour, 2), late_rows
FROM v_reconciliation
WHERE late_rows > 0
UNION ALL
SELECT 'duplicate_usage', customer_id, billing_month, gpu_type,
       invoice_id, dup_hours,
       ROUND(dup_hours * rate_per_hour, 2), dup_rows
FROM v_reconciliation
WHERE dup_rows > 0;
