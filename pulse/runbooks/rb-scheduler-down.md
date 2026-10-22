# Airflow scheduler down / no heartbeat
Symptoms: alert `SchedulerHeartbeatMissing`; no new task runs; `rate(airflow_scheduler_heartbeat[1m]) == 0`.
Diagnosis: `docker compose logs airflow`; check metadata DB connectivity and container memory (OOM-killed scheduler).
Fix: restart the airflow container; if the DB is down follow rb-metadata-db.
