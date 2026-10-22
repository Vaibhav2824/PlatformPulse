# TASK — 5 h sprint checklist

## 0. Plan + docs (0:00–0:20)
- [x] PRD, ARCHITECTURE, DESIGN, RULES, TASK
- [x] Airflow image build started
- **Done when:** docs committed.

## 1. Platform + chaos (0:20–1:30)
- [x] docker-compose: postgres, airflow (standalone, LocalExecutor), trino (1 GB heap)
- [x] `platform_dags.py` (3 DAGs), `spark_job.py`, `events_bad.csv`, `spark_pool`
- [x] `chaos.py oom|bad_schema|timeout|stuck|restore`
- **Done when:** each of the 4 failures triggers on command and shows its log signature.

## 2. Observability (1:30–2:15)
- [x] statsd-exporter mapping, Prometheus scrape + 5 rules, Alertmanager webhook
- [x] incident service (FastAPI + SQLite) + `test_app.py`
- **Done when:** a chaos run fires an alert and an incident row appears; tests pass.

## 3. Dashboard (2:15–2:45)
- [x] Grafana provisioning + `customer_experience.json`
- [x] incident `/metrics` scraped
- **Done when:** dashboard updates live during a chaos run.

## 4. MCP + agent (2:45–3:45)
- [x] `mcp_server.py` 6 tools, 12 runbooks, fastembed search
- [x] `agent.py` triage + Q&A
- [x] `eval.py` (17 valid runs)
- **Done when:** agent correctly diagnoses each of the 4 types once; eval running.

## 5. Slack (3:45–4:30)
- [x] `slack_manifest.yml`; user creates app + tokens
- [x] alert posts + buttons, auto-summary, `/pulse`, @mention, App Home
- **Done when:** chaos → Slack alert → thread summary → Ack works live. ✅ verified 2026-10-23

## 6. Polish (4:30–5:00)
- [x] README (setup, demo, numbers from eval), REVIEW_LOG, eval table
- [x] SLIDES.md (5 slides), `notebooks/postmortem.ipynb`
- [x] Demo GIF (docs/demo.gif, recorded from a real run)
- **Cut order if late:** notebook → App Home → slides.
