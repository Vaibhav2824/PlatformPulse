# Trino coordinator down or unresponsive
Symptoms: `TargetDown` for job trino; queries fail with connection refused; Trino OOM `ExitOnOutOfMemoryError`.
Diagnosis: `docker compose logs trino`; heap is capped at 1 GB, large joins can exhaust it.
Fix: restart trino; add `LIMIT`/filters to heavy queries; raise `-Xmx` only if RAM budget allows.
