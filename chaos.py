#!/usr/bin/env python3
"""Break the platform on purpose.

usage: python chaos.py oom|bad_schema|timeout|stuck|restore
"""
import base64
import json
import os
import sys
import urllib.request

AIRFLOW = os.getenv("AIRFLOW_URL", "http://localhost:8080") + "/api/v1"
AUTH = "Basic " + base64.b64encode(b"admin:admin").decode()  # dev-only creds
TARGET = {"oom": "sales_daily", "bad_schema": "events_ingest", "timeout": "user_metrics", "stuck": "user_metrics"}
POOL_SLOTS = 2


def call(method, path, body=None):
    req = urllib.request.Request(
        AIRFLOW + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": AUTH, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def set_pool(slots):
    call("PATCH", "/pools/spark_pool", {"name": "spark_pool", "slots": slots})


def trigger(chaos):
    """Inject one failure; returns (dag_id, dag_run_id)."""
    if chaos == "stuck":
        set_pool(0)  # a "misconfigured" pool: task can never get a slot
    run = call("POST", f"/dags/{TARGET[chaos]}/dagRuns", {"conf": {"chaos": chaos}})
    return run["dag_id"], run["dag_run_id"]


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "restore":
        set_pool(POOL_SLOTS)
        print(f"spark_pool restored to {POOL_SLOTS} slots")
    elif mode in TARGET:
        print("triggered", *trigger(mode))
    else:
        sys.exit(__doc__)
