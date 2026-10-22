# Monitoring target down (TargetDown)
Symptoms: `up == 0` for a scrape job (airflow statsd-exporter, incident-service, trino).
Diagnosis: `docker compose ps`; curl the target's /metrics from the prometheus container.
Fix: restart the service; if statsd-exporter is down, Airflow metrics are lost until it returns (UDP).
