"""PagerDuty-style incident service: Alertmanager webhook in, open/ack/resolve lifecycle, Prometheus metrics out."""
import os
import sqlite3
import time
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

DB_PATH = os.getenv("DB_PATH", "incidents.db")
SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY, fingerprint TEXT, starts_at TEXT, alertname TEXT, dag_id TEXT, task_id TEXT,
  severity TEXT, summary TEXT, status TEXT DEFAULT 'open', category TEXT,
  created_at REAL, acked_at REAL, resolved_at REAL, resolved_by TEXT,
  slack_ts TEXT, agent_summary TEXT, agent_latency_s REAL,
  UNIQUE (fingerprint, starts_at));
CREATE TABLE IF NOT EXISTS support_requests (
  id INTEGER PRIMARY KEY, user TEXT, question TEXT, category TEXT, outcome TEXT DEFAULT 'open', created_at REAL);
-- eval-harness incidents are synthetic: kept for audit, excluded from customer-facing metrics
CREATE VIEW IF NOT EXISTS real_incidents AS SELECT * FROM incidents WHERE resolved_by IS NOT 'eval';
"""


def q(sql, args=()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            cur = conn.execute(sql, args)
            return [dict(r) for r in cur.fetchall()], cur.lastrowid
    finally:
        conn.close()


with sqlite3.connect(DB_PATH) as _c:
    _c.executescript(SCHEMA)

app = FastAPI(title="PlatformPulse incident service")


def get_or_404(table, id_):
    rows, _ = q(f"SELECT * FROM {table} WHERE id = ?", (id_,))
    if not rows:
        raise HTTPException(404, f"{table} {id_} not found")
    return rows[0]


@app.post("/alertmanager")
def alertmanager_webhook(payload: dict):
    for a in payload.get("alerts", []):
        if a.get("status") != "firing":
            continue  # lifecycle is owned by humans/agent, not by the alert clearing
        labels, ann = a.get("labels", {}), a.get("annotations", {})
        q("INSERT OR IGNORE INTO incidents (fingerprint, starts_at, alertname, dag_id, task_id, severity, summary, created_at)"
          " VALUES (?,?,?,?,?,?,?,?)",
          (a.get("fingerprint"), a.get("startsAt"), labels.get("alertname"), labels.get("dag_id") or labels.get("pool"),
           labels.get("task_id"), labels.get("severity"), ann.get("summary"), time.time()))
    return {"received": len(payload.get("alerts", []))}


@app.get("/incidents")
def list_incidents(status: Optional[str] = None, since_id: int = 0, limit: int = 50):
    sql, args = "SELECT * FROM incidents WHERE id > ?", [since_id]
    if status:
        sql += " AND status = ?"
        args.append(status)
    rows, _ = q(sql + " ORDER BY id DESC LIMIT ?", (*args, min(limit, 200)))
    return rows


@app.get("/incidents/{id_}")
def get_incident(id_: int):
    return get_or_404("incidents", id_)


class IncidentPatch(BaseModel):
    category: Optional[str] = None
    slack_ts: Optional[str] = None
    agent_summary: Optional[str] = None
    agent_latency_s: Optional[float] = None


@app.patch("/incidents/{id_}")
def patch_incident(id_: int, body: IncidentPatch):
    get_or_404("incidents", id_)
    fields = body.model_dump(exclude_none=True)  # keys come from the model, safe to interpolate
    if fields:
        q(f"UPDATE incidents SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), id_))
    return get_or_404("incidents", id_)


@app.post("/incidents/{id_}/ack")
def ack(id_: int):
    get_or_404("incidents", id_)
    q("UPDATE incidents SET acked_at = COALESCE(acked_at, ?), status = CASE WHEN status = 'open' THEN 'acked' ELSE status END"
      " WHERE id = ?", (time.time(), id_))
    return get_or_404("incidents", id_)


@app.post("/incidents/{id_}/resolve")
def resolve(id_: int, by: Literal["agent", "human", "eval"]):
    get_or_404("incidents", id_)
    now = time.time()
    q("UPDATE incidents SET status = 'resolved', resolved_at = COALESCE(resolved_at, ?), resolved_by = COALESCE(resolved_by, ?),"
      " acked_at = COALESCE(acked_at, ?) WHERE id = ?", (now, by, now, id_))
    return get_or_404("incidents", id_)


class SupportRequest(BaseModel):
    user: str
    question: str
    category: str = "other"


class SupportOutcome(BaseModel):
    outcome: Literal["deflected", "escalated"]


@app.post("/support_requests")
def create_support_request(body: SupportRequest):
    _, rowid = q("INSERT INTO support_requests (user, question, category, created_at) VALUES (?,?,?,?)",
                 (body.user, body.question[:2000], body.category, time.time()))
    return get_or_404("support_requests", rowid)


@app.patch("/support_requests/{id_}")
def set_outcome(id_: int, body: SupportOutcome):
    get_or_404("support_requests", id_)
    q("UPDATE support_requests SET outcome = ? WHERE id = ?", (body.outcome, id_))
    return get_or_404("support_requests", id_)


def _label(v):
    return str(v or "unknown").replace("\\", "\\\\").replace('"', '\\"')


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    """Recomputed from the DB on every scrape, so it survives restarts."""
    one = lambda sql: q(sql)[0][0]  # noqa: E731
    open_n = one("SELECT COUNT(*) n FROM real_incidents WHERE status != 'resolved'")["n"]
    lines = [f"pulse_incidents_open {open_n}"]
    for r in q("SELECT category, status, COUNT(*) n FROM real_incidents GROUP BY 1, 2")[0]:
        lines.append(f'pulse_incidents_total{{category="{_label(r["category"])}",status="{r["status"]}"}} {r["n"]}')
    for r in q("SELECT category, outcome, COUNT(*) n FROM support_requests GROUP BY 1, 2")[0]:
        lines.append(f'pulse_support_requests_total{{category="{_label(r["category"])}",outcome="{r["outcome"]}"}} {r["n"]}')
    s = one("""SELECT
        (SELECT AVG(acked_at - created_at) FROM real_incidents WHERE acked_at IS NOT NULL) mtta,
        (SELECT AVG(resolved_at - created_at) FROM real_incidents WHERE resolved_at IS NOT NULL) mttr,
        (SELECT AVG(agent_latency_s) FROM real_incidents WHERE agent_latency_s IS NOT NULL) latency,
        (SELECT COUNT(*) FROM real_incidents WHERE resolved_by = 'agent')
          + (SELECT COUNT(*) FROM support_requests WHERE outcome = 'deflected') deflected,
        (SELECT COUNT(*) FROM real_incidents WHERE resolved_by IS NOT NULL)
          + (SELECT COUNT(*) FROM support_requests WHERE outcome != 'open') closed""")
    lines += [f"pulse_mtta_seconds {s['mtta'] or 0}", f"pulse_mttr_seconds {s['mttr'] or 0}",
              f"pulse_agent_latency_seconds {s['latency'] or 0}",
              f"pulse_deflection_ratio {s['deflected'] / s['closed'] if s['closed'] else 0}"]
    return "\n".join(lines) + "\n"
