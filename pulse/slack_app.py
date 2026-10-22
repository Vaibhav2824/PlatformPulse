"""PlatformPulse Slack app (Bolt, Socket Mode): incident alerts + buttons, auto-triage in thread, /pulse,
@mention Q&A with deflection tracking, App Home health tab."""
import json
import logging
import os
import pathlib
import re
import sys
import threading
import time

import httpx
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from agent import ask, triage_incident

INCIDENTS = os.getenv("INCIDENT_URL", "http://localhost:8000")
PROM = os.getenv("PROM_URL", "http://localhost:9090")
CHANNEL = os.getenv("SLACK_CHANNEL", "platform-alerts")
RUNBOOK_DIR = pathlib.Path(__file__).parent / "runbooks"
POLL_S = 5
STATUS_EMOJI = {"open": ":rotating_light:", "acked": ":eyes:", "resolved": ":white_check_mark:"}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pulse")
BOT_TOKEN, APP_TOKEN = os.getenv("SLACK_BOT_TOKEN", ""), os.getenv("SLACK_APP_TOKEN", "")
if not (BOT_TOKEN.startswith("xoxb-") and len(BOT_TOKEN) > 20 and APP_TOKEN.startswith("xapp-") and len(APP_TOKEN) > 20):
    # exit 0 so `restart: on-failure` doesn't loop; the agent CLI and eval still work without Slack
    log.warning("Slack tokens not set: Slack app disabled")
    sys.exit(0)
app = App(token=BOT_TOKEN)


def section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}


def button(text, action_id, value, style=None):
    b = {"type": "button", "text": {"type": "plain_text", "text": text}, "action_id": action_id, "value": str(value)}
    return {**b, "style": style} if style else b


def incident_blocks(inc):
    target = f"{inc['dag_id']}.{inc['task_id']}" if inc.get("task_id") else inc["dag_id"]
    text = (f"{STATUS_EMOJI.get(inc['status'], '')} *[{inc['severity']}] {inc['alertname']}* â€” `{target}`\n{inc['summary']}\n"
            f"Incident *#{inc['id']}* Â· status *{inc['status']}*" + (f" Â· category `{inc['category']}`" if inc.get("category") else ""))
    blocks = [section(text)]
    if inc["status"] == "resolved":
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Resolved by *{inc['resolved_by']}*"}]})
        return blocks
    buttons = ([button("Ack", "ack", inc["id"], "primary")] if inc["status"] == "open" else []) + [
        button("Summarize", "summarize", inc["id"]), button("Runbook", "runbook", inc["id"]),
        button("Resolve (agent fix)", "resolve_agent", inc["id"]), button("Resolve (human)", "resolve_human", inc["id"], "danger")]
    return blocks + [{"type": "actions", "elements": buttons}]


def summary_text(res, secs):
    ev = "\n".join(f"â€¢ `{e[:200]}`" for e in res.get("evidence", [])[:4])
    return (f":robot_face: *Triage: `{res['category']}`* (in {secs}s)\n{res.get('summary', '')}\n{ev}\n"
            f"*Next step:* {res.get('next_step', '-')}\n*Runbook:* `{res.get('runbook', '-')}`")


def summarize(incident_id, channel, ts):
    try:
        res, secs = triage_incident(incident_id)
        app.client.chat_postMessage(channel=channel, thread_ts=ts, text=summary_text(res, secs))
        inc = httpx.get(f"{INCIDENTS}/incidents/{incident_id}").json()
        app.client.chat_update(channel=channel, ts=ts, text=inc["summary"], blocks=incident_blocks(inc))
    except Exception as e:
        log.exception("triage failed")
        app.client.chat_postMessage(channel=channel, thread_ts=ts, text=f":warning: agent triage failed: {e}")


def poll_incidents():
    """ponytail: 5s polling of the incident service; switch to a push webhook if latency matters."""
    rows = httpx.get(f"{INCIDENTS}/incidents", params={"limit": 1}).json()
    seen = rows[0]["id"] if rows else 0  # only alert on incidents created after startup
    while True:
        try:
            for inc in reversed(httpx.get(f"{INCIDENTS}/incidents", params={"since_id": seen}).json()):
                seen = max(seen, inc["id"])
                r = app.client.chat_postMessage(channel=CHANNEL, text=f"[{inc['severity']}] {inc['alertname']} {inc['dag_id']}",
                                                blocks=incident_blocks(inc))
                httpx.patch(f"{INCIDENTS}/incidents/{inc['id']}", json={"slack_ts": r["ts"]})
                threading.Thread(target=summarize, args=(inc["id"], r["channel"], r["ts"]), daemon=True).start()
        except Exception:
            log.exception("poll failed")
        time.sleep(POLL_S)


def refresh_message(body, inc):
    app.client.chat_update(channel=body["channel"]["id"], ts=body["message"]["ts"], text=inc["summary"], blocks=incident_blocks(inc))


@app.action(re.compile(r"^(ack|resolve_agent|resolve_human)$"))
def on_lifecycle(ack, body):
    ack()
    action = body["actions"][0]
    iid = action["value"]
    if action["action_id"] == "ack":
        inc = httpx.post(f"{INCIDENTS}/incidents/{iid}/ack").json()
    else:
        inc = httpx.post(f"{INCIDENTS}/incidents/{iid}/resolve", params={"by": action["action_id"].split("_")[1]}).json()
    refresh_message(body, inc)
    app.client.chat_postMessage(channel=body["channel"]["id"], thread_ts=body["message"]["ts"],
                                text=f"<@{body['user']['id']}> marked incident #{iid} *{inc['status']}*")


@app.action("summarize")
def on_summarize(ack, body):
    ack()
    summarize(int(body["actions"][0]["value"]), body["channel"]["id"], body["message"]["ts"])


@app.action("runbook")
def on_runbook(ack, body):
    ack()
    inc = httpx.get(f"{INCIDENTS}/incidents/{body['actions'][0]['value']}").json()
    rb = json.loads(inc["agent_summary"]).get("runbook", "") if inc.get("agent_summary") else ""
    path = RUNBOOK_DIR / f"{pathlib.Path(rb).stem}.md"
    text = f":book: *{rb}*\n{path.read_text(encoding='utf-8')}" if rb and path.exists() else ":hourglass: no runbook yet â€” triage still running"
    app.client.chat_postMessage(channel=body["channel"]["id"], thread_ts=body["message"]["ts"], text=text)


def prom(expr):
    try:
        return httpx.get(f"{PROM}/api/v1/query", params={"query": expr}).json()["data"]["result"]
    except Exception:
        return []


def health_blocks():
    up = " ".join(f"{':large_green_circle:' if s['value'][1] == '1' else ':red_circle:'} {s['metric']['job']}" for s in prom("up"))
    scalar = lambda e: float(prom(e)[0]["value"][1]) if prom(e) else 0.0  # noqa: E731
    fails = ", ".join(f"{s['metric']['dag_id']}: {float(s['value'][1]):.0f}"
                      for s in prom('sum by (dag_id) (increase(airflow_ti_finish{state="failed"}[1h]))')) or "none"
    open_inc = [i for i in httpx.get(f"{INCIDENTS}/incidents", params={"limit": 50}).json() if i["status"] != "resolved"]
    inc_lines = "\n".join(f"{STATUS_EMOJI[i['status']]} #{i['id']} {i['alertname']} `{i['dag_id']}` {i.get('category') or ''}"
                          for i in open_inc[:8]) or "No open incidents :tada:"
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "PlatformPulse â€” platform health"}},
        section(f"*Services:* {up or 'no data'}"),
        section(f"*Task failures (1h):* {fails}"),
        section(f"*MTTA* {scalar('pulse_mtta_seconds'):.0f}s Â· *MTTR* {scalar('pulse_mttr_seconds'):.0f}s Â· "
                f"*Deflection* {scalar('pulse_deflection_ratio'):.0%} Â· *Agent time-to-summary* {scalar('pulse_agent_latency_seconds'):.1f}s"),
        {"type": "divider"},
        section(f"*Open incidents ({len(open_inc)})*\n{inc_lines}"),
    ]


@app.command("/pulse")
def on_pulse(ack, respond):
    ack()
    respond(blocks=health_blocks(), text="PlatformPulse health")


@app.event("app_home_opened")
def on_home(event, client):
    client.views_publish(user_id=event["user"], view={"type": "home", "blocks": health_blocks()})


@app.event("app_mention")
def on_mention(event, say):
    question = re.sub(r"<@[^>]+>", "", event["text"]).strip()
    thread = event.get("thread_ts") or event["ts"]
    say(text=":mag: looking into itâ€¦", thread_ts=thread)
    try:
        res = ask(question)
    except Exception as e:
        log.exception("ask failed")
        say(text=f":warning: agent failed: {e}", thread_ts=thread)
        return
    sr = httpx.post(f"{INCIDENTS}/support_requests",
                    json={"user": event["user"], "question": question, "category": res["category"]}).json()
    answer = res.get("answer") or res.get("summary", "")
    say(thread_ts=thread, text=answer, blocks=[
        section(answer),
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"category `{res['category']}` Â· tools: {', '.join(res.get('tools_used', []))}"}]},
        {"type": "actions", "elements": [button("Solved âœ…", "sr_deflected", sr["id"], "primary"),
                                         button("Escalate to on-call ðŸ™‹", "sr_escalated", sr["id"])]}])


@app.action(re.compile(r"^sr_(deflected|escalated)$"))
def on_support_outcome(ack, body):
    ack()
    action = body["actions"][0]
    outcome = action["action_id"].removeprefix("sr_")
    httpx.patch(f"{INCIDENTS}/support_requests/{action['value']}", json={"outcome": outcome})
    blocks = [b for b in body["message"]["blocks"] if b["type"] != "actions"] + [
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"<@{body['user']['id']}> marked this *{outcome}*"}]}]
    app.client.chat_update(channel=body["channel"]["id"], ts=body["message"]["ts"], text=body["message"]["text"], blocks=blocks)


if __name__ == "__main__":
    threading.Thread(target=poll_incidents, daemon=True).start()
    SocketModeHandler(app, APP_TOKEN).start()
