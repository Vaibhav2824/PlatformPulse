import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402

client = TestClient(app)


def alert(fp="abc", status="firing"):
    return {"alerts": [{"status": status, "fingerprint": fp, "startsAt": "2026-10-22T10:00:00Z",
                        "labels": {"alertname": "AirflowTaskFailed", "dag_id": "sales_daily", "task_id": "run_spark",
                                   "severity": "critical"},
                        "annotations": {"summary": "Task sales_daily.run_spark failed"}}]}


def metric(name):
    for line in client.get("/metrics").text.splitlines():
        if line.startswith(name + " "):
            return float(line.split()[1])


def test_incident_lifecycle_and_metrics():
    client.post("/alertmanager", json=alert())
    client.post("/alertmanager", json=alert())  # duplicate notification
    client.post("/alertmanager", json=alert(status="resolved"))
    rows = client.get("/incidents").json()
    assert len(rows) == 1 and rows[0]["status"] == "open" and rows[0]["dag_id"] == "sales_daily"
    iid = rows[0]["id"]
    assert metric("pulse_incidents_open") == 1

    client.patch(f"/incidents/{iid}", json={"category": "oom", "agent_latency_s": 12.5})
    assert client.post(f"/incidents/{iid}/ack").json()["status"] == "acked"
    assert client.post(f"/incidents/{iid}/resolve", params={"by": "bogus"}).status_code == 422
    r = client.post(f"/incidents/{iid}/resolve", params={"by": "agent"}).json()
    assert r["status"] == "resolved" and r["resolved_by"] == "agent" and r["category"] == "oom"

    assert metric("pulse_incidents_open") == 0
    assert metric("pulse_mtta_seconds") >= 0 and metric("pulse_agent_latency_seconds") == 12.5
    assert metric("pulse_deflection_ratio") == 1.0
    assert 'pulse_incidents_total{category="oom",status="resolved"} 1' in client.get("/metrics").text


def test_support_requests_drive_deflection():
    sid = client.post("/support_requests", json={"user": "U1", "question": "why?", "category": "how_to"}).json()["id"]
    assert client.patch(f"/support_requests/{sid}", json={"outcome": "nope"}).status_code == 422
    client.patch(f"/support_requests/{sid}", json={"outcome": "escalated"})
    assert metric("pulse_deflection_ratio") == 0.5  # 1 agent-resolved incident, 1 escalated request
    assert client.get("/incidents/999").status_code == 404


def test_eval_resolutions_excluded_from_metrics():
    before = client.get("/metrics").text
    client.post("/alertmanager", json=alert(fp="eval-run"))
    iid = client.get("/incidents").json()[0]["id"]
    client.post(f"/incidents/{iid}/resolve", params={"by": "eval"})
    assert client.get(f"/incidents/{iid}").json()["resolved_by"] == "eval"
    assert client.get("/metrics").text == before  # synthetic incident leaves every metric untouched
