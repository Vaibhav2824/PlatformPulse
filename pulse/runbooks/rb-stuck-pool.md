# DAG stuck: tasks never start (pool has no free slots)
Symptoms: task state stays `scheduled`/`queued`; alert `AirflowTaskStarving`; `airflow_pool_starving_tasks{pool="spark_pool"} > 0`; `open_slots = 0`.
Diagnosis: `get_dag_status` -> pools section; check `slots` of `spark_pool`. Someone set slots to 0 or long-running tasks hold every slot.
Fix: restore pool slots (`airflow pools set spark_pool 2 ...` or Admin -> Pools), or kill the zombie tasks holding slots. Tasks start automatically.
Prevention: alert on starving tasks; change-control on pool config.
