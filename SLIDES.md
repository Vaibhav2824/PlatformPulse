---
marp: true
theme: default
paginate: true
---

# PlatformPulse
### An AI support copilot for a mini data platform
Airflow + PySpark + Trino · Prometheus/Grafana · PagerDuty-style incidents · MCP agent in Slack

---

## The problem: support toil
- A job breaks → an alert fires → someone digs through metrics, logs and runbooks → posts in Slack → tracks it to resolution
- The same 4 failure shapes come up again and again: **OOM, bad schema, timeout, stuck DAG**
- Goal: the agent does the digging, and humans make the call

---

## Architecture
- **Platform:** Airflow (LocalExecutor) running PySpark, Trino over the Airflow metadata, `chaos.py` to break it
- **Observability:** StatsD → Prometheus (5 rules) → Alertmanager → incident service (open/ack/resolve, MTTA/MTTR)
- **Agent:** Groq `gpt-oss-120b` ⇄ **my MCP server** (6 tools across Prometheus, Airflow, the incident DB and Trino)
- **Surface:** Slack Bolt (alerts + buttons, `/pulse`, @mention, App Home) and a Grafana CX dashboard

---

## Results (measured)
| Failure type | Model | Runs | Accuracy | Median detect (s) | Median time-to-summary (s) | p90 time-to-summary (s) |
|---|---|---|---|---|---|---|
| oom | `openai/gpt-oss-120b` | 4 | 100% | 28.4 | 27.5 | 34.7 |
| bad_schema | `openai/gpt-oss-120b` | 4 | 100% | 26.7 | 19.4 | 30.0 |
| timeout | `openai/gpt-oss-120b` | 4 | 100% | 107.8 | 8.1 | 8.5 |
| stuck | `openai/gpt-oss-20b` | 5 | 80% | 46.1 | 57.4 | 147.7 |
| all | `all` | 17 | 94% | 40.6 | 19.4 | 34.7 |

- Every incident records `resolved_by = agent | human`, and that gives the **deflection rate** on the dashboard

---

## What I learned
- Test alert rules against real failures: `starving_tasks` **never fired** on a truly stuck pool
- The prompt is the tool budget. Telling the agent to skip SQL in triage cut its tool calls
- Check vendor catalogs live, since the default model had been retired
- All AI corrections are in `REVIEW_LOG.md`
