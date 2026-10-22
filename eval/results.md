# Eval results (2026-10-22 18:14, Groq models per row)

time-to-summary = agent triage time after the incident opens; detect = chaos trigger -> incident row.

| Failure type | Model | Runs | Accuracy | Median detect (s) | Median time-to-summary (s) | p90 time-to-summary (s) |
|---|---|---|---|---|---|---|
| oom | `openai/gpt-oss-120b` | 4 | 100% | 28.4 | 27.5 | 34.7 |
| bad_schema | `openai/gpt-oss-120b` | 4 | 100% | 26.7 | 19.4 | 30.0 |
| timeout | `openai/gpt-oss-120b` | 4 | 100% | 107.8 | 8.1 | 8.5 |
| stuck | `openai/gpt-oss-20b` | 5 | 80% | 46.1 | 57.4 | 147.7 |
| all | `all` | 17 | 94% | 40.6 | 19.4 | 34.7 |
