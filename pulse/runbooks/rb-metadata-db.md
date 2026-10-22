# Airflow metadata database unreachable
Symptoms: `OperationalError: could not connect to server`, `psycopg2` errors in scheduler/webserver logs, UI 500s.
Diagnosis: `docker compose ps postgres`; `pg_isready`; disk and connection count.
Fix: restart postgres; reduce connection pool size; scheduler recovers on its own afterwards.
