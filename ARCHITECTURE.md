# Architecture — PlatformPulse

```
 ┌──────────────── Mini Data Platform (Docker Compose) ─────────────────┐
 │  Airflow ── runs ──► PySpark jobs (local mode)      Trino (1 node)    │
 │     │  chaos.py → conf {"chaos": oom|bad_schema|timeout|stuck}        │
 │     └─ StatsD ─► statsd-exporter ─┐          Trino ─► Airflow Postgres│
 └───────────────────────────────────┼───────────────────────────────────┘
                                     ▼
                 Prometheus ──► Alertmanager ── webhook ──► Incident Service (FastAPI + SQLite)
                     │  ▲ scrapes /metrics (MTTA, MTTR, deflection) ──────────┘
                     ▼
              Grafana "Customer Experience" dashboard
                                     
   pulse container:
     slack_app.py (Bolt, Socket Mode) ── polls incidents ──► posts alert + buttons
          │ runs
          ▼
     agent.py (Groq, OpenAI-compatible tool loop) ──stdio──► mcp_server.py
          tools: query_prometheus · get_dag_status · get_task_logs
                 get_incidents · search_runbooks · run_trino_query
```

## Components
| Service | Image | Role | Port (host) | Mem cap |
|---|---|---|---|---|
| postgres | postgres:16-alpine | Airflow metadata DB | — | 256 MB |
| airflow | custom (slim-2.10.5 + JDK17 + pyspark 3.5) | `standalone`, LocalExecutor, runs Spark local mode | 8080 | 2.5 GB |
| trino | trinodb/trino:470 | SQL over `tpch` + Airflow Postgres; heap 1 GB | 8081 | 1.5 GB |
| statsd-exporter | prom/statsd-exporter:v0.28.0 | Airflow StatsD → Prometheus | 9102 | 64 MB |
| prometheus | prom/prometheus:v3.1.0 | scrape 5s, 5 alert rules | 9090 | 300 MB |
| alertmanager | prom/alertmanager:v0.28.0 | webhook → incident service | 9093 | 64 MB |
| incident | python:3.11-slim + FastAPI | incident lifecycle, `/metrics` | 8000 | 128 MB |
| grafana | grafana/grafana:11.4.0 | provisioned dashboard, anonymous viewer | 3000 | 256 MB |
| pulse | python:3.11-slim | Slack app + agent + MCP server + eval | — | 768 MB |
| **Total** | | | | **≈ 5.8 GB** (Docker VM has 8 GB) |

## Data flow (happy path of a failure)
1. `chaos.py oom` → Airflow REST `POST /dags/sales_daily/dagRuns {conf:{chaos:"oom"}}`.
2. Spark job dies with `java.lang.OutOfMemoryError`; Airflow emits `airflow.ti.finish.sales_daily.run_spark.failed` over StatsD.
3. statsd-exporter maps it to `airflow_ti_finish{dag_id,task_id,state}`; Prometheus rule `AirflowTaskFailed` fires.
4. Alertmanager POSTs to `incident:8000/alertmanager`; a new incident row (status `open`) is created.
5. `slack_app.py` sees the new incident (5 s poll), posts it to `#platform-alerts` with Ack / Summarize / Runbook / Resolve buttons and kicks off the agent.
6. Agent calls MCP tools (DAG status → task logs → Prometheus → runbook search), returns `{category, summary, evidence, runbook}`, posts it in the thread, PATCHes the incident category.
7. Engineer clicks **Ack** (MTTA) and **Resolve** with `resolved_by=agent|human` (MTTR, deflection). Grafana shows it all.

## Why these choices
- **Single Airflow container (`standalone`)** — scheduler + webserver + triggerer in one process tree saves ~1 GB vs split services on an 8 GB VM.
- **Airflow 2.10.5, not 3.x** — stable StatsD metric names and `/api/v1` basic auth; no time budget for Airflow 3's auth manager/component split.
- **Trino over Airflow Postgres** — gives the agent real SQL over task history without a Hive metastore.
- **Polling instead of push to Slack** — the bot is the only Slack writer; no internal HTTP endpoint needed. *Ceiling:* 5 s latency.
- **MCP over stdio inside pulse** — no extra container/port; any MCP client (Claude Desktop) can also launch it.
