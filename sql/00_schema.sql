CREATE TABLE customers (
  customer_id   INT PRIMARY KEY,
  customer_name VARCHAR(100) NOT NULL,
  segment       VARCHAR(20)  NOT NULL
);

-- GRAIN: one row per usage event (instance, day). usage_id is a surrogate key.
-- No UNIQUE constraint on (customer_id, instance_id, usage_date) on purpose:
-- raw tables accept what the source sends, and duplicates get caught downstream.
CREATE TABLE usage_events (
  usage_id      INT PRIMARY KEY,
  customer_id   INT           NOT NULL,
  instance_id   VARCHAR(20)   NOT NULL,
  gpu_type      VARCHAR(10)   NOT NULL,
  usage_date    DATE          NOT NULL,
  billing_month CHAR(7)       NOT NULL,
  gpu_hours     DECIMAL(10,2) NOT NULL,
  rate_per_hour DECIMAL(10,2) NOT NULL,
  ingested_at   DATETIME      NOT NULL,
  FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

-- GRAIN: one row per customer x billing_month x gpu_type.
CREATE TABLE invoices (
  invoice_id    VARCHAR(12) PRIMARY KEY,
  customer_id   INT           NOT NULL,
  billing_month CHAR(7)       NOT NULL,
  gpu_type      VARCHAR(10)   NOT NULL,
  billed_hours  DECIMAL(10,2) NOT NULL,
  billed_amount DECIMAL(12,2) NOT NULL,
  invoice_date  DATE          NOT NULL,
  FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);
