# Disk full / no space left on device
Symptoms: `No space left on device`, `IOException` writing parquet or logs, Postgres refusing writes.
Diagnosis: `docker system df`; check airflow log volume and /tmp/out job outputs.
Fix: prune old logs (`airflow db clean`), delete stale outputs, `docker system prune` unused images.
