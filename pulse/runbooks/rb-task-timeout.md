# Airflow task timeout (execution_timeout exceeded)
Symptoms: `AirflowTaskTimeout: Timeout`, task killed after `execution_timeout` (90s), job log stops mid-step (e.g. "reading upstream partition").
Diagnosis: is an upstream source slow or hanging? Compare duration with past runs (`airflow_task_duration`, or Trino over `postgresql.public.task_instance`).
Fix: unblock or fail the upstream dependency; if data volume legitimately grew, raise `execution_timeout` and add retries with backoff.
Prevention: per-source read timeouts inside the job; DagRunSlow alert as early warning.
