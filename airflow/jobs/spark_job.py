"""PySpark local-mode jobs with chaos hooks. Usage: spark_job.py <dag_id> <chaos>"""
import sys
import time

from pyspark.sql import SparkSession, functions as F

dag_id, chaos = sys.argv[1], sys.argv[2]
print(f"job={dag_id} chaos={chaos}", flush=True)

spark = (
    SparkSession.builder.master("local[2]").appName(dag_id)
    .config("spark.driver.memory", "512m")
    .config("spark.driver.maxResultSize", "0")  # let a big collect hit the heap, not this guard
    .config("spark.ui.enabled", "false")
    .config("spark.sql.shuffle.partitions", "4")
    .getOrCreate()
)
spark.sparkContext.setLogLevel("WARN")

if chaos == "timeout":
    print("reading upstream partition (hangs)...", flush=True)
    time.sleep(300)

if chaos == "oom":
    # pulls ~10 GB of rows to a 512m driver
    spark.range(0, 200_000_000, numPartitions=32).selectExpr("id", "repeat('x', 50) AS pad").collect()

if dag_id == "events_ingest":
    if chaos == "bad_schema":
        df = spark.read.option("header", True).csv("/opt/airflow/data/events_bad.csv")
    else:
        df = spark.range(100_000).selectExpr(
            "id AS event_id", "CAST(id % 500 AS INT) AS user_id",
            "CASE WHEN id % 3 = 0 THEN 'click' ELSE 'view' END AS event_type")
    out = df.groupBy("event_type").agg(F.countDistinct("user_id").alias("users"))
elif dag_id == "sales_daily":
    df = spark.range(200_000).selectExpr(
        "id AS order_id", "element_at(array('APAC','EMEA','NA'), CAST(id % 3 AS INT) + 1) AS region",
        "(id % 97) * 1.5 AS amount")
    out = df.groupBy("region").agg(F.sum("amount").alias("revenue"))
else:
    df = spark.range(50_000).selectExpr("CAST(id % 1000 AS INT) AS user_id", "id % 60 AS session_min")
    out = df.groupBy("user_id").agg(F.avg("session_min").alias("avg_session")).agg(F.count("*").alias("users"))

out.write.mode("overwrite").parquet(f"/tmp/out/{dag_id}")
out.show()
print("job succeeded", flush=True)
spark.stop()
