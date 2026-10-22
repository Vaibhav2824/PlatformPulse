"""Eval: 4 failure types x N runs. chaos -> alert -> incident -> agent triage.
Writes /eval/results.csv and /eval/results.md. usage: python eval.py [runs_per_type]"""
import csv
import os
import statistics
import sys
import time

import httpx

import chaos
from agent import MODEL, triage_incident

INCIDENTS = os.getenv("INCIDENT_URL", "http://localhost:8000")
OUT = os.getenv("EVAL_DIR", "/eval")
TYPES = ["oom", "bad_schema", "timeout", "stuck"]
DETECT_TIMEOUT_S = 300
STUCK_COOLDOWN_S = 30
FIELDS = ["model", "run", "expected", "predicted", "correct", "incident_id", "detect_s", "triage_s", "total_s", "tools_used"]


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
    try:
        if not inc:
            return {"model": MODEL, "run": n, "expected": chaos_type, "predicted": "no_incident", "correct": False}
        # triage while the platform is still broken, like a real on-call would
        result, triage_s = triage_incident(inc["id"])
    except Exception as e:  # one bad run (e.g. LLM rate limit) is a data point, not a crash
        while getattr(e, "exceptions", None):  # unwrap anyio ExceptionGroups to the real cause
            e = e.exceptions[0]
        print(f"run {n} {chaos_type} errored: {type(e).__name__}: {e}", flush=True)
        return {"model": MODEL, "run": n, "expected": chaos_type, "predicted": "error", "correct": False, "incident_id": inc["id"]}
    finally:
        if chaos_type == "stuck":
            chaos.set_pool(chaos.POOL_SLOTS)
            time.sleep(STUCK_COOLDOWN_S)  # let the alert clear so the next stuck run opens a new incident
    correct = result["category"] == chaos_type
    httpx.post(f"{INCIDENTS}/incidents/{inc['id']}/resolve", params={"by": "agent" if correct else "human"})
    detect_s = round(inc["created_at"] - t0, 1)
    return {"model": MODEL, "run": n, "expected": chaos_type, "predicted": result["category"], "correct": correct,
            "incident_id": inc["id"], "detect_s": detect_s, "triage_s": triage_s,
            "total_s": round(detect_s + triage_s, 1), "tools_used": ">".join(result.get("tools_used", []))}


def p90(xs):
    return sorted(xs)[max(0, int(round(0.9 * len(xs))) - 1)]


def write_md(rows):
    for r in rows:  # rows read back from CSV are strings
        r["correct"] = str(r["correct"]) == "True"
        for k in ("detect_s", "triage_s"):
            r[k] = float(r[k]) if r.get(k) not in (None, "") else None
    lines = ["| Failure type | Model | Runs | Accuracy | Median detect (s) | Median time-to-summary (s) | p90 time-to-summary (s) |",
             "|---|---|---|---|---|---|---|"]
    groups = sorted({(r["expected"], r["model"]) for r in rows}, key=lambda g: (TYPES.index(g[0]), g[1]))
    for t, m in groups + [("all", "all")]:
        rs = [r for r in rows if t == "all" or (r["expected"], r["model"]) == (t, m)]
        ok = [r for r in rs if r.get("triage_s") is not None]
        if not rs:
            continue
        acc = sum(r["correct"] for r in rs) / len(rs)
        tts = [r["triage_s"] for r in ok]
        det = [r["detect_s"] for r in ok]
        lines.append(f"| {t} | `{m}` | {len(rs)} | {acc:.0%} | {round(statistics.median(det), 1) if det else '-'} | "
                     f"{round(statistics.median(tts), 1) if tts else '-'} | {p90(tts) if tts else '-'} |")
    with open(os.path.join(OUT, "results.md"), "w") as f:
        f.write(f"# Eval results ({time.strftime('%Y-%m-%d %H:%M')}, Groq models per row)\n\n"
                "time-to-summary = agent triage time after the incident opens; detect = chaos trigger -> incident row.\n\n"
                + "\n".join(lines) + "\n")


if __name__ == "__main__":
    # usage: eval.py [runs=5] [types=oom,bad_schema,timeout,stuck] [first_run_number=1]; appends to results.csv
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    types = sys.argv[2].split(",") if len(sys.argv) > 2 else TYPES
    first = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "results.csv")
    is_new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        if is_new:
            w.writeheader()
        for n in range(first, first + runs):
            for t in types:  # interleaved so the same DAG's alert clears between its runs
                row = run_one(n, t)
                w.writerow(row)
                f.flush()
                print(row, flush=True)
    with open(path, newline="") as f:
        write_md(list(csv.DictReader(f)))
    print(open(os.path.join(OUT, "results.md")).read())
