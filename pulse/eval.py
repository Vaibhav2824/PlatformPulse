"""Eval: 4 failure types x N runs. chaos -> alert -> incident -> agent triage.
Writes /eval/results.csv and /eval/results.md. usage: python eval.py [runs_per_type]"""
import csv
import os
import statistics
import sys
import time

import httpx

import chaos
from agent import triage_incident

INCIDENTS = os.getenv("INCIDENT_URL", "http://localhost:8000")
OUT = os.getenv("EVAL_DIR", "/eval")
TYPES = ["oom", "bad_schema", "timeout", "stuck"]
DETECT_TIMEOUT_S = 300
FIELDS = ["run", "expected", "predicted", "correct", "incident_id", "detect_s", "triage_s", "total_s", "tools_used"]


def last_incident_id():
    rows = httpx.get(f"{INCIDENTS}/incidents", params={"limit": 1}).json()
    return rows[0]["id"] if rows else 0


def wait_for_incident(since_id, chaos_type):
    alert = "AirflowTaskStarving" if chaos_type == "stuck" else "AirflowTaskFailed"
    target = "spark_pool" if chaos_type == "stuck" else chaos.TARGET[chaos_type]
    deadline = time.time() + DETECT_TIMEOUT_S
    while time.time() < deadline:
        for inc in httpx.get(f"{INCIDENTS}/incidents", params={"since_id": since_id}).json():
            if inc["alertname"] == alert and inc["dag_id"] == target:
                return inc
        time.sleep(2)
    return None


def run_one(n, chaos_type):
    since = last_incident_id()
    t0 = time.time()
    chaos.trigger(chaos_type)
    inc = wait_for_incident(since, chaos_type)
    if chaos_type == "stuck":
        chaos.set_pool(chaos.POOL_SLOTS)
    if not inc:
        return {"run": n, "expected": chaos_type, "predicted": "no_incident", "correct": False}
    result, triage_s = triage_incident(inc["id"])
    correct = result["category"] == chaos_type
    httpx.post(f"{INCIDENTS}/incidents/{inc['id']}/resolve", params={"by": "agent" if correct else "human"})
    detect_s = round(inc["created_at"] - t0, 1)
    return {"run": n, "expected": chaos_type, "predicted": result["category"], "correct": correct,
            "incident_id": inc["id"], "detect_s": detect_s, "triage_s": triage_s,
            "total_s": round(detect_s + triage_s, 1), "tools_used": ">".join(result.get("tools_used", []))}


def p90(xs):
    return sorted(xs)[max(0, int(round(0.9 * len(xs))) - 1)]


def write_md(rows):
    lines = ["| Failure type | Runs | Accuracy | Median detect (s) | Median time-to-summary (s) | p90 time-to-summary (s) |",
             "|---|---|---|---|---|---|"]
    for t in TYPES + ["all"]:
        rs = [r for r in rows if t in ("all", r["expected"])]
        ok = [r for r in rs if r.get("triage_s") is not None]
        if not rs:
            continue
        acc = sum(r["correct"] for r in rs) / len(rs)
        tts = [r["triage_s"] for r in ok]
        det = [r["detect_s"] for r in ok]
        lines.append(f"| {t} | {len(rs)} | {acc:.0%} | {statistics.median(det) if det else '-'} | "
                     f"{statistics.median(tts) if tts else '-'} | {p90(tts) if tts else '-'} |")
    with open(os.path.join(OUT, "results.md"), "w") as f:
        f.write(f"# Eval results ({time.strftime('%Y-%m-%d %H:%M')}, model `{os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b')}`)\n\n"
                "time-to-summary = agent triage time after the incident opens; detect = chaos trigger -> incident row.\n\n"
                + "\n".join(lines) + "\n")


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    os.makedirs(OUT, exist_ok=True)
    rows = []
    with open(os.path.join(OUT, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        for n in range(1, runs + 1):
            for t in TYPES:  # interleaved so the same DAG's alert clears between its runs
                row = run_one(n, t)
                rows.append(row)
                w.writerow(row)
                f.flush()
                print(row, flush=True)
    write_md(rows)
    print(open(os.path.join(OUT, "results.md")).read())
