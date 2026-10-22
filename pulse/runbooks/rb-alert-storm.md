# Alert storm / duplicate incidents
Symptoms: many incidents for one root cause; Slack channel flooded.
Diagnosis: group incidents by dag_id and alertname; find the common upstream (pool, scheduler, DB).
Fix: fix the root cause first; ack the rest; tune Alertmanager `group_by` and `group_interval`.
