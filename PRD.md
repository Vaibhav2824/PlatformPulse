# PRD — PlatformPulse

## Problem
Application Support Engineers (ASE) on a data platform spend their day on the same loop: an Airflow/Spark job breaks, an alert fires, someone digs through metrics and task logs, finds the runbook, posts an update in Slack, and tracks the incident to resolution. Most of that is manual toil that an agent with the right tools can do in seconds.

## Users
- **On-call / support engineer** — gets the alert in Slack, wants a diagnosis + runbook, not raw logs.
- **Platform customer (data engineer)** — asks "why did my DAG fail?" in Slack, wants a straight answer.
- **Team lead** — wants customer-experience numbers: health, MTTA/MTTR, deflection.

## Goals
1. Reproduce a real (small) data platform and break it on command in 4 ways: **OOM, bad schema, timeout, stuck DAG**.
2. Detect every failure automatically and open a PagerDuty-style incident (open → ack → resolve).
3. An LLM agent, via a custom MCP server, triages the incident (category + summary + evidence + runbook) and posts it in the Slack thread.
4. A Grafana "Customer Experience" dashboard built from raw telemetry.
5. Measure the agent honestly: triage accuracy and time-to-summary over 4 types × 5 runs.

## Success metrics
| Metric | Target | Source |
|---|---|---|
| Triage accuracy (4 types × 5 runs) | ≥ 90% | `eval/results.md` |
| Time-to-summary (incident open → agent summary) | < 60 s median | `eval/results.md` |
| Agent deflection rate | shown live | Grafana, incident DB |
| MTTA / MTTR | shown live | Grafana, incident DB |
| Stack memory | < 8 GB | `docker stats` |
| Cost | ₹0 | free tiers + OSS only |

## In scope
Airflow (LocalExecutor) + 3 PySpark DAGs, Trino, `chaos.py`, statsd-exporter, Prometheus (5 rules), Alertmanager, FastAPI incident service, Grafana dashboard as code, MCP server (6 tools), Groq tool-calling agent, Slack Bolt app (alerts + buttons, `/pulse`, @mention, App Home), eval, README/REVIEW_LOG/slides/notebook.

## Non-goals
Multi-node anything, auth/SSO, HA, real PagerDuty, a hosted LLM, a public URL (Socket Mode only), auto-remediation (the agent recommends; humans act).

## JD gap → component
| JD requirement | Component |
|---|---|
| Slack API, bots, webhooks | Bolt app (buttons, `/pulse`, @mention, App Home); Alertmanager → FastAPI webhook |
| Observability (Prometheus, Grafana, PagerDuty) | StatsD → Prometheus → Alertmanager; incident service mimics PagerDuty lifecycle |
| CX dashboards from raw telemetry | Provisioned Grafana dashboard: health, incident trends, MTTA/MTTR, requests by category, deflection |
| MCP servers + multi-tool agents | Own MCP server, 6 tools over 4 backends (Prometheus, Airflow, incident DB, Trino) |
| Agents for triage / summaries / runbooks | Agent classifies, pulls metrics + logs, summarizes in thread, links runbook |
| Big data (Spark, Airflow, Trino, notebooks) | Airflow running PySpark, Trino over Airflow metadata, postmortem notebook |
| Reducing toil | Every incident/request records agent-vs-human resolution → deflection rate |
| AI-assisted dev with critical review | `REVIEW_LOG.md` |
| Docs + portfolio | README, runbooks, one `docker compose up`, slides |
