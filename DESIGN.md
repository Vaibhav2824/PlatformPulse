# DESIGN â€” PlatformPulse

## 1. DAGs and chaos
One file `airflow/dags/platform_dags.py` builds 3 DAGs: `sales_daily`, `events_ingest`, `user_metrics`. Each has one task `run_spark`:
`BashOperator(python /opt/airflow/jobs/spark_job.py <dag_id> {{ dag_run.conf.get('chaos','none') }})`, `pool=spark_pool` (2 slots), `execution_timeout=90s`, `retries=0`, no schedule (manual/chaos triggered).

| `chaos.py <type>` | DAG | Mechanism | Expected log signature |
|---|---|---|---|
| `oom` | sales_daily | driver 512m, `.collect()` of ~200M rows | `java.lang.OutOfMemoryError: Java heap space` |
| `bad_schema` | events_ingest | reads `data/events_bad.csv` (renamed/missing columns) | `AnalysisException ... UNRESOLVED_COLUMN` |
| `timeout` | user_metrics | job sleeps 300 s | `AirflowTaskTimeout` |
| `stuck` | user_metrics | PATCH pool `spark_pool` slots=0, then trigger | task stays `scheduled`, never runs |
| `restore` | â€” | pool slots=2 | â€” |

## 2. Metrics (statsd-exporter mapping)
| StatsD | Prometheus |
|---|---|
| `airflow.ti.finish.<dag>.<task>.<state>` | `airflow_ti_finish{dag_id,task_id,state}` |
| `airflow.dag.<dag>.<task>.duration` | `airflow_task_duration{dag_id,task_id}` |
| `airflow.dagrun.duration.<state>.<dag>` | `airflow_dagrun_duration{dag_id,state}` |
| `airflow.pool.<metric>.<pool>` | `airflow_pool_<metric>{pool}` (open_slots, queued_slots, scheduled_slots, starving_tasks) |
| `airflow.scheduler_heartbeat` | `airflow_scheduler_heartbeat` |

## 3. Alert rules (`observability/alerts.yml`)
| Alert | Expr | For | Severity |
|---|---|---|---|
| AirflowTaskFailed | `increase(airflow_ti_finish{state="failed"}[1m]) > 0` | 0s | critical |
| AirflowTaskStarving | `max by (pool) (airflow_pool_starving_tasks) > 0` | 30s | critical |
| SchedulerHeartbeatMissing | `rate(airflow_scheduler_heartbeat[1m]) == 0` | 1m | critical |
| DagRunSlow | `airflow_dagrun_duration{state="success"} > 120000` | 0s | warning |
| TargetDown | `up == 0` | 30s | warning |

Alertmanager: `group_by: ['...']` (one notification per distinct alert), `group_wait: 5s`, `repeat_interval: 4h`, `send_resolved: true`, receiver = webhook `http://incident:8000/alertmanager`.

## 4. Incident service
SQLite at `/data/incidents.db`.

```
incidents(id PK, fingerprint, starts_at, alertname, dag_id, task_id, severity, summary,
          status open|acked|resolved, category, created_at, acked_at, resolved_at,
          resolved_by agent|human|null, slack_ts, agent_summary, agent_latency_s)
  UNIQUE(fingerprint, starts_at)
support_requests(id PK, user, question, category, outcome open|deflected|escalated, created_at)
```

| Endpoint | Purpose |
|---|---|
| `POST /alertmanager` | firing â†’ insert (dedupe on fingerprint+startsAt); resolved â†’ no-op on lifecycle (humans/agent close incidents) |
| `GET /incidents?status=&since_id=` | list, newest first |
| `GET /incidents/{id}` | one |
| `PATCH /incidents/{id}` | set `category`, `slack_ts`, `agent_summary`, `agent_latency_s` |
| `POST /incidents/{id}/ack` | sets `acked_at` |
| `POST /incidents/{id}/resolve?by=agent|human` | sets `resolved_at`, `resolved_by` |
| `POST /support_requests`, `PATCH /support_requests/{id}` | Q&A logging + outcome |
| `GET /metrics` | gauges recomputed from DB each scrape |

Metrics: `pulse_incidents_open`, `pulse_incidents_total{category,status}`, `pulse_mtta_seconds`, `pulse_mttr_seconds` (averages over resolved), `pulse_support_requests_total{category,outcome}`, `pulse_deflection_ratio` (agent-resolved incidents + deflected requests) / (all closed).

## 5. MCP server (`pulse/mcp_server.py`, FastMCP, stdio)
| Tool | Backend | Returns |
|---|---|---|
| `query_prometheus(promql)` | Prometheus `/api/v1/query` | compact `[{metric, value}]` |
| `get_dag_status(dag_id=None)` | Airflow REST | latest runs + task states |
| `get_task_logs(dag_id, run_id, task_id="run_spark", try_number=1)` | Airflow REST | last ~3 KB of log |
| `get_incidents(status=None, limit=10)` | incident service | rows |
| `search_runbooks(query, k=3)` | fastembed bge-small over `runbooks/*.md` | `[{id, title, score, excerpt}]` |
| `run_trino_query(sql)` | Trino (`tpch`, `postgresql`=Airflow DB) | rows, max 50; non-SELECT rejected |

## 6. Agent (`pulse/agent.py`)
- MCP stdio client â†’ list tools â†’ convert to OpenAI tool schema â†’ Groq (`GROQ_MODEL`, default `openai/gpt-oss-120b`) loop, max 8 steps, temperature 0.
- Retries: 429 (sleep per `retry-after`), `tool_use_failed` (re-ask).
- **Triage mode** output (JSON): `{"category": "oom|bad_schema|timeout|stuck|other", "summary": str, "evidence": [str], "runbook": "<runbook id>"}`.
- **Q&A mode** output: `{"category": "incident|data_question|how_to|other", "answer": str}`.
- CLI: `python agent.py --incident <id>` / `python agent.py --ask "..."`.

## 7. Slack UX (`pulse/slack_app.py`, Bolt Socket Mode)
- **Alert post** (`#platform-alerts`): `:rotating_light: [critical] AirflowTaskFailed â€” sales_daily.run_spark` + buttons **Ack Â· Summarize Â· Runbook Â· Resolve (agent) Â· Resolve (human)**. Agent summary auto-posts in thread, with `:robot_face: triaged in 14.2s`.
- **`/pulse`**: open incidents, last DAG states, MTTA/MTTR, deflection.
- **@mention**: agent Q&A answer in thread + **Solved âœ… / Escalate ðŸ™‹** buttons â†’ support request outcome.
- **App Home**: same health summary as `/pulse`, refreshed on open.

## 8. Grafana "Customer Experience" dashboard
Rows: **Platform health** (target up per job, scheduler heartbeat, task success/fail rate per DAG) Â· **Incidents** (open now, trend by category, MTTA, MTTR) Â· **Support** (requests by category, deflection ratio, agent latency).

## 9. Eval (`pulse/eval.py`)
Interleaved `[oom, bad_schema, timeout, stuck] Ã— 5`. Per run: `chaos.py <type>` â†’ wait for new incident (`since_id`) â†’ run agent â†’ record `expected, predicted, correct, detect_s, triage_s, total_s` â†’ `chaos.py restore` for stuck â†’ resolve incident. Output `eval/results.csv` + `eval/results.md` (per-type accuracy, median/p90 time-to-summary).
