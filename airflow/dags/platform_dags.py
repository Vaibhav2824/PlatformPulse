"""Three PySpark DAGs. Each runs spark_job.py; chaos.py injects failures via dag_run.conf."""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

for dag_id in ("sales_daily", "events_ingest", "user_metrics"):
    with DAG(
        dag_id,
        start_date=datetime(2026, 1, 1),
        schedule="*/15 * * * *",  # background healthy traffic for the dashboard
        catchup=False,
        max_active_runs=2,
        tags=["platformpulse"],
    ) as dag:
        BashOperator(
            task_id="run_spark",
            bash_command=f"python /opt/airflow/jobs/spark_job.py {dag_id} {{{{ dag_run.conf.get('chaos', 'none') }}}}",
            pool="spark_pool",
            execution_timeout=timedelta(seconds=90),
            retries=0,
        )
    globals()[dag_id] = dag
