# Spark driver/executor out of memory (OOM)
Symptoms: task failed; log shows `java.lang.OutOfMemoryError: Java heap space`, `GC overhead limit exceeded`, py4j `Answer from Java side is empty`, or exit code 137.
Diagnosis: find the action that pulls data to the driver (`collect()`, `toPandas()`, broadcast of a large table). Check `spark.driver.memory` (jobs run local mode with 512m).
Fix: replace `collect()` with a write or `take(n)`; aggregate before collecting; raise `spark.driver.memory` only if the data is legitimately bigger. Re-run the DAG.
Prevention: code review rule "no unbounded collect"; dashboard alert on task failures by DAG.
