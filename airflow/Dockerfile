FROM apache/airflow:slim-2.10.5-python3.11
USER root
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jre-headless procps \
    && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
USER airflow
RUN pip install --no-cache-dir "apache-airflow[postgres,statsd]==2.10.5" \
    --constraint https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.11.txt
# pyspark kept outside the Airflow constraints file (it pins a conflicting py4j)
RUN pip install --no-cache-dir "pyspark==3.5.5"
