# PlatformPulse

**An AI support copilot for a mini data platform.** Airflow runs PySpark jobs, Trino serves SQL, and I break both on purpose. PlatformPulse detects each failure, opens a PagerDuty-style incident, and posts it to Slack. An LLM agent then diagnoses it through a **custom MCP server** and writes the root cause, evidence and runbook into the incident's Slack thread. A Grafana "Customer Experience" dashboard tracks health, MTTA/MTTR and agent deflection.

It's the day-to-day work of an Application Support Engineering team, reproduced at laptop scale for ₹0.

```
 Airflow ─runs─► PySpark (local)      Trino ─► Airflow metadata (Postgres)
    │  chaos.py: oom · bad_schema · timeout · stuck
    └─StatsD─► statsd-exporter ─► Prometheus ─► Alertmanager ─webhook─► Incident service (FastAPI+SQLite)
                                      │  ▲──────────── /metrics (MTTA, MTTR, deflection) ────┘
                                      ▼
                               Grafana CX dashboard
 Slack (Bolt, Socket Mode) ◄─► agent.py (Groq, tool calling) ─stdio─► mcp_server.py (6 tools, 4 backends)
```
Details: [ARCHITECTURE.md](ARCHITECTURE.md) · [DESIGN.md](DESIGN.md) · [PRD.md](PRD.md)

## Results (measured; see `eval/results.md`)

The eval injects each of the 4 failure types 5 times, interleaved, and runs the whole loop each time: chaos → alert → incident → agent triage. Raw rows are in [`eval/results.csv`](eval/results.csv).

<!-- EVAL_TABLE -->

## Quick start
Requirements: Docker Desktop (8 GB for WSL2), a free [Groq](https://console.groq.com) key, and a free Slack workspace.

```bash
cp .env.example .env          # add GROQ_API_KEY, SLACK_BOT_TOKEN, SLACK_APP_TOKEN
docker compose up -d --build  # ~5.8 GB budget, ~2.2 GB idle
```
| UI | URL |
|---|---|
| Airflow (admin/admin, dev only) | http://localhost:8080 |
| Grafana CX dashboard | http://localhost:3000 |
| Prometheus alerts | http://localhost:9090/alerts |
| Incident API (OpenAPI docs) | http://localhost:8000/docs |

**Slack app:** go to api.slack.com/apps → *Create New App* → *From a manifest* and paste [`slack_manifest.yml`](slack_manifest.yml). Create an app-level token with `connections:write` (`xapp-…`), install the app (`xoxb-…`), create a public `#platform-alerts` channel, and `/invite @PlatformPulse`.

## Break it
```bash
python chaos.py oom          # Spark driver Java heap OOM        (sales_daily)
python chaos.py bad_schema   # renamed input columns -> AnalysisException (events_ingest)
python chaos.py timeout      # job hangs -> AirflowTaskTimeout   (user_metrics)
python chaos.py stuck        # spark_pool set to 0 slots -> task never starts
python chaos.py restore      # put the pool back
```
Within ~15–30 s an alert fires and an incident is created. Slack then gets the alert with **Ack · Summarize · Runbook · Resolve** buttons, and the agent posts its diagnosis in the thread.

## What's in it
| Piece | Notes |
|---|---|
| `airflow/` | Airflow 2.10.5 slim + JDK 17 + PySpark 3.5, `standalone` with LocalExecutor, 3 DAGs from one file |
| `observability/` | statsd mapping, 5 alert rules (task failed, stuck pool, scheduler heartbeat, slow DAG, target down), Alertmanager webhook |
| `incident_service/` | open → ack → resolve lifecycle, dedupe on fingerprint+startsAt, `resolved_by=agent\|human`, support requests, Prometheus `/metrics` computed from the DB. Tested with `pytest` |
| `pulse/mcp_server.py` | MCP tools: `query_prometheus`, `get_dag_status`, `get_task_logs`, `get_incidents`, `search_runbooks` (fastembed bge-small over 12 runbooks), `run_trino_query` (read-only, row-capped) |
| `pulse/agent.py` | Tool-calling loop over MCP stdio, `openai/gpt-oss-120b` on Groq, retries on 429 and malformed tool calls, strict JSON output |
| `pulse/slack_app.py` | Alert posts + buttons, auto-triage in thread, `/pulse`, @mention Q&A with Solved/Escalate (deflection), App Home |
| `grafana/` | dashboard-as-code: service health, task outcomes, pool slots, incidents by category, MTTA/MTTR, support requests, deflection, agent latency |
| `pulse/eval.py` | the measured numbers above |
| `notebooks/postmortem.ipynb` | postmortem analysis of the eval + incident data |

The agent is **read-only by design**: it recommends, humans remediate. Trino only accepts single `SELECT/SHOW/DESCRIBE/EXPLAIN/WITH` statements.

## Using the MCP server elsewhere
`mcp_server.py` is a standard stdio MCP server, so Claude Desktop or any other MCP client can launch it:
```json
{"mcpServers": {"platformpulse": {"command": "docker", "args": ["compose", "-f", "<repo>/docker-compose.yml", "run", "--rm", "-i", "--no-deps", "pulse", "python", "mcp_server.py"]}}}
```

## AI-assisted development
Built with Claude Code in a 5-hour sprint. Every case where its output was wrong is logged with the fix in [REVIEW_LOG.md](REVIEW_LOG.md). Examples: an alert rule that never fired on a truly stuck pool, a retired LLM model, and Python-3.12-only syntax in a 3.11 container.

## Runbooks
[`pulse/runbooks/`](pulse/runbooks) has 12 runbooks: OOM, schema mismatch, timeout, stuck pool, scheduler down, metadata DB, Trino down/slow, slow DAG, target down, alert storm, disk full.
