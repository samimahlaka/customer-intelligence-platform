-- Phase 4: validate raw load row counts and basic non-emptiness.
-- Expected counts match the processed CSVs validated in data generation.

USE DATABASE CIP_DB;
USE SCHEMA RAW;

SELECT 'customers' AS table_name, COUNT(*) AS row_count FROM CUSTOMERS
UNION ALL
SELECT 'subscriptions', COUNT(*) FROM SUBSCRIPTIONS
UNION ALL
SELECT 'billing', COUNT(*) FROM BILLING
UNION ALL
SELECT 'transactions', COUNT(*) FROM TRANSACTIONS
UNION ALL
SELECT 'support_tickets', COUNT(*) FROM SUPPORT_TICKETS
UNION ALL
SELECT 'usage_events', COUNT(*) FROM USAGE_EVENTS
ORDER BY table_name;

-- Spot-check: each table has expected columns populated for at least one row.
SELECT 'customers_sample' AS check_name, CUSTOMER_ID, GENDER, IS_CHURNED
FROM CUSTOMERS
LIMIT 3;

SELECT 'subscriptions_sample' AS check_name, CUSTOMER_ID, TENURE_MONTHS, MONTHLY_CHARGES
FROM SUBSCRIPTIONS
LIMIT 3;

SELECT 'billing_sample' AS check_name, CUSTOMER_ID, PAYMENT_METHOD, TOTAL_CHARGES
FROM BILLING
LIMIT 3;

SELECT 'transactions_sample' AS check_name, TRANSACTION_ID, TRANSACTION_DATE, AMOUNT
FROM TRANSACTIONS
LIMIT 3;

SELECT 'support_tickets_sample' AS check_name, TICKET_ID, STATUS, CLOSED_AT
FROM SUPPORT_TICKETS
LIMIT 3;

SELECT 'usage_events_sample' AS check_name, EVENT_ID, EVENT_TYPE, QUANTITY, UNIT
FROM USAGE_EVENTS
LIMIT 3;

-- Open tickets should allow null closed_at / satisfaction fields.
SELECT
  STATUS,
  COUNT(*) AS tickets,
  SUM(IFF(CLOSED_AT IS NULL, 1, 0)) AS null_closed_at
FROM SUPPORT_TICKETS
GROUP BY STATUS
ORDER BY STATUS;
