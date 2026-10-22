# DAG runs getting slower (DagRunSlow)
Symptoms: alert `DagRunSlow`; successful runs averaging > 60s; risk of hitting execution_timeout.
Diagnosis: compare `airflow_task_duration` trend; Trino: `SELECT dag_id, avg(duration) FROM postgresql.public.task_instance GROUP BY 1`.
Fix: check data volume growth, shuffle partitions, competing jobs on the same pool.
