# Slow or failing Trino query
Symptoms: user reports a query hanging, `Query exceeded per-node memory limit`, `EXCEEDED_TIME_LIMIT`.
Diagnosis: run `EXPLAIN` on the query; check for missing filters, cross joins, `SELECT *` on wide tables.
Fix: push filters down, aggregate early, add LIMIT; for Airflow metadata use `postgresql.public` tables with date filters.
