# Eval results (2026-10-22 17:23, model `openai/gpt-oss-120b`)

time-to-summary = agent triage time after the incident opens; detect = chaos trigger -> incident row.

| Failure type | Runs | Accuracy | Median detect (s) | Median time-to-summary (s) | p90 time-to-summary (s) |
|---|---|---|---|---|---|
| oom | 5 | 80% | 28.45 | 27.450000000000003 | 34.7 |
| bad_schema | 5 | 80% | 26.700000000000003 | 19.35 | 30.0 |
| timeout | 5 | 80% | 107.75 | 8.100000000000001 | 8.5 |
| all | 15 | 80% | 30.35 | 17.799999999999997 | 31.8 |
