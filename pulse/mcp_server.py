"""PlatformPulse MCP server (stdio): 6 read-only tools over Prometheus, Airflow, the incident DB and Trino."""
import os
import pathlib
import re
from urllib.parse import quote

import httpx
import numpy as np
import trino
from mcp.server.fastmcp import FastMCP

AIRFLOW = os.getenv("AIRFLOW_URL", "http://localhost:8080") + "/api/v1"
PROM = os.getenv("PROM_URL", "http://localhost:9090")
INCIDENTS = os.getenv("INCIDENT_URL", "http://localhost:8000")
TRINO_HOST = os.getenv("TRINO_HOST", "localhost")
AIRFLOW_AUTH = ("admin", "admin")  # dev-only
RUNBOOK_DIR = pathlib.Path(__file__).parent / "runbooks"
MAX_ROWS = 50
ERROR_RE = re.compile(r"error|exception|timeout|timed out|killed|heap|unresolved|cannot resolve|failed", re.I)
READ_ONLY_SQL = re.compile(r"^\s*(select|show|describe|explain|with)\b", re.I)

mcp = FastMCP("platformpulse")
http = httpx.Client(timeout=20)


def af(path, **params):
    r = http.get(AIRFLOW + path, params=params, auth=AIRFLOW_AUTH)
    r.raise_for_status()
    return r.json()


@mcp.tool()
def query_prometheus(promql: str) -> list[dict]:
    """Run an instant PromQL query against Prometheus.
    Useful series: airflow_ti_finish{dag_id,task_id,state} (counter), airflow_pool_open_slots{pool},
    airflow_pool_starving_tasks{pool}, airflow_pool_scheduled_slots{pool}, airflow_scheduler_heartbeat,
    up{job}, ALERTS{alertstate="firing"}, pulse_incidents_open."""
    r = http.get(f"{PROM}/api/v1/query", params={"query": promql}).json()
    if r.get("status") != "success":
        return [{"error": r.get("error")}]
    data = r["data"]
    if data["resultType"] in ("scalar", "string"):
        return [{"value": data["result"][1]}]
    return [{"metric": s["metric"], "value": s["value"][1]} for s in data["result"]][:MAX_ROWS]


@mcp.tool()
def get_dag_status(dag_id: str = "") -> dict:
    """Latest 3 runs (with task states, try numbers, pool) for one DAG, or all DAGs if dag_id is empty.
    Also returns pool slot usage, which explains tasks stuck in 'scheduled'/'queued'."""
    dags = [dag_id] if dag_id else [d["dag_id"] for d in af("/dags")["dags"]]
    runs = []
    for d in dags:
        for run in af(f"/dags/{d}/dagRuns", order_by="-execution_date", limit=3)["dag_runs"]:
            tis = af(f"/dags/{d}/dagRuns/{quote(run['dag_run_id'], safe='')}/taskInstances")["task_instances"]
            runs.append({"dag_id": d, "run_id": run["dag_run_id"], "state": run["state"], "conf": run.get("conf"),
                         "start": run["start_date"], "end": run["end_date"],
                         "tasks": [{k: t[k] for k in ("task_id", "state", "try_number", "pool", "duration")} for t in tis]})
    pools = [{k: p[k] for k in ("name", "slots", "open_slots", "running_slots", "queued_slots", "scheduled_slots")}
             for p in af("/pools")["pools"]]
    return {"runs": runs, "pools": pools}


@mcp.tool()
def get_task_logs(dag_id: str, run_id: str, task_id: str = "run_spark", try_number: int = 1) -> dict:
    """Error lines plus the tail of a task instance's log. try_number comes from get_dag_status."""
    url = f"{AIRFLOW}/dags/{dag_id}/dagRuns/{quote(run_id, safe='')}/taskInstances/{task_id}/logs/{max(try_number, 1)}"
    r = http.get(url, auth=AIRFLOW_AUTH, headers={"Accept": "text/plain"})
    if r.status_code == 404:
        return {"note": "no log: the task never started (check its state and pool slots)"}
    r.raise_for_status()
    lines = r.text.splitlines()
    errors = list(dict.fromkeys(l.strip()[:300] for l in lines if ERROR_RE.search(l)))[:30]
    return {"error_lines": errors, "tail": "\n".join(lines[-25:])[-2000:]}


@mcp.tool()
def get_incidents(status: str = "", limit: int = 10) -> list[dict]:
    """Recent incidents from the incident service. status: open | acked | resolved | '' for all."""
    rows = http.get(f"{INCIDENTS}/incidents", params={"status": status or None, "limit": limit}).json()
    keep = ("id", "alertname", "dag_id", "task_id", "severity", "summary", "status", "category", "created_at", "resolved_by")
    return [{k: r[k] for k in keep} for r in rows]


_runbooks = None


def _index():
    global _runbooks
    if _runbooks is None:
        from fastembed import TextEmbedding  # slow import, only when first needed
        model = TextEmbedding("BAAI/bge-small-en-v1.5")
        docs = [(p.stem, p.read_text(encoding="utf-8")) for p in sorted(RUNBOOK_DIR.glob("*.md"))]
        vecs = np.array(list(model.embed([text for _, text in docs])))
        _runbooks = (model, docs, vecs / np.linalg.norm(vecs, axis=1, keepdims=True))
    return _runbooks


@mcp.tool()
def search_runbooks(query: str, k: int = 3) -> list[dict]:
    """Semantic search over the team runbooks. Pass the error message or symptom. Returns runbook ids to cite."""
    model, docs, vecs = _index()
    qv = np.array(list(model.query_embed(query)))[0]
    scores = vecs @ (qv / np.linalg.norm(qv))
    return [{"id": docs[i][0], "title": docs[i][1].splitlines()[0].lstrip("# "), "score": round(float(scores[i]), 3),
             "excerpt": docs[i][1][:600]} for i in np.argsort(-scores)[:k]]


@mcp.tool()
def run_trino_query(sql: str) -> dict:
    """Read-only SQL via Trino. Catalogs: postgresql.public (Airflow metadata: dag_run, task_instance, slot_pool,
    log) and tpch. Example: SELECT dag_id, state, count(*) FROM postgresql.public.task_instance GROUP BY 1, 2"""
    if not READ_ONLY_SQL.match(sql) or ";" in sql.strip().rstrip(";"):
        return {"error": "only a single SELECT/SHOW/DESCRIBE/EXPLAIN/WITH statement is allowed"}
    cur = trino.dbapi.connect(host=TRINO_HOST, port=8080, user="pulse-agent", catalog="postgresql", schema="public").cursor()
    cur.execute(sql.strip().rstrip(";"))
    rows = cur.fetchmany(MAX_ROWS)
    return {"columns": [c[0] for c in cur.description], "rows": [[str(v) for v in r] for r in rows]}


if __name__ == "__main__":
    mcp.run()
