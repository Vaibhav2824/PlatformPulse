"""Triage / Q&A agent: Groq tool-calling loop over the PlatformPulse MCP server (stdio).

usage: python agent.py --incident 3      |      python agent.py --ask "why did sales_daily fail?"
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import BadRequestError, OpenAI, RateLimitError

MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
INCIDENTS = os.getenv("INCIDENT_URL", "http://localhost:8000")
MCP_SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")
MAX_STEPS = 8
TOOL_RESULT_CHARS = 4000
TRIAGE_CATEGORIES = {"oom", "bad_schema", "timeout", "stuck", "other"}
QA_CATEGORIES = {"incident", "data_question", "how_to", "other"}

TRIAGE_PROMPT = """You are PlatformPulse, the on-call triage agent for a data platform (Airflow running PySpark jobs, Trino, Prometheus).
Investigate with tools before answering. Usual path: get_dag_status (find the failed or never-started task and its
try_number) -> get_task_logs -> search_runbooks with the key error line -> query_prometheus if useful.
Skip run_trino_query during triage unless the logs are missing and you need run history.
Classify into exactly one category:
- oom: java.lang.OutOfMemoryError / Java heap space / memory kill
- bad_schema: AnalysisException, unresolved or missing column, schema mismatch
- timeout: AirflowTaskTimeout / execution_timeout exceeded
- stuck: task never starts (scheduled/queued forever), pool has 0 open slots, starving tasks
- other: anything else
Reply with ONLY a JSON object, no prose around it:
{"category": "...", "summary": "2-3 sentences for Slack: what broke, root cause, impact",
 "evidence": ["short quotes from logs or metrics"], "runbook": "<id from search_runbooks>", "next_step": "one concrete action"}"""

QA_PROMPT = """You are PlatformPulse, a support copilot for engineers using a data platform (Airflow + PySpark, Trino, Prometheus).
Answer the user's question using tools for live facts (DAG status, logs, metrics, incidents, runbooks, read-only SQL).
Be concise and concrete; cite runbook ids when relevant.
Reply with ONLY a JSON object: {"category": "incident|data_question|how_to|other", "answer": "slack-formatted answer"}"""

llm = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=os.getenv("GROQ_API_KEY", "missing"))


def chat(messages, tools):
    kw = {"model": MODEL, "messages": messages, "temperature": 0}
    if tools:
        kw.update(tools=tools, tool_choice="auto")
    for _ in range(6):
        try:
            return llm.chat.completions.create(**kw).choices[0].message
        except RateLimitError as e:
            time.sleep(min(60.0, float(e.response.headers.get("retry-after", 10))))
        except BadRequestError as e:
            if "tool_use_failed" not in str(e):
                raise
            # model emitted a malformed tool call; retrying at temperature 0 usually recovers
    raise RuntimeError("LLM unavailable after retries")


def parse_json(text, categories):
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        out = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        out = {}
    out.setdefault("summary", out.get("answer") or (text or "").strip())
    if out.get("category") not in categories:
        out["category"] = "other"
    return out


async def run_agent(system, user, categories):
    params = StdioServerParameters(command=sys.executable, args=[MCP_SERVER], env=dict(os.environ))
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.inputSchema}}
                 for t in (await session.list_tools()).tools]
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        trace = []
        for _ in range(MAX_STEPS):
            msg = chat(messages, tools)
            if not msg.tool_calls:
                return {**parse_json(msg.content, categories), "tools_used": trace}
            messages.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                trace.append(tc.function.name)
                try:
                    res = await session.call_tool(tc.function.name, json.loads(tc.function.arguments or "{}"))
                    text = "\n".join(getattr(c, "text", "") for c in res.content)
                except Exception as e:  # bad args etc. go back to the model, not up the stack
                    text = f"tool error: {e}"
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": text[:TOOL_RESULT_CHARS]})
        messages.append({"role": "user", "content": "Stop calling tools and answer now with the JSON object."})
        return {**parse_json(chat(messages, None).content, categories), "tools_used": trace}


def triage_incident(incident_id):
    """Diagnose one incident, write the result back to the incident service. Returns (result, seconds)."""
    inc = httpx.get(f"{INCIDENTS}/incidents/{incident_id}").raise_for_status().json()
    user = (f"Incident #{inc['id']}: alert {inc['alertname']} (severity {inc['severity']}) on "
            f"{'pool' if inc['alertname'] == 'AirflowTaskStarving' else 'DAG'} {inc['dag_id']}"
            f"{' task ' + inc['task_id'] if inc['task_id'] else ''}. Alert text: {inc['summary']}. Diagnose it.")
    t0 = time.time()
    result = asyncio.run(run_agent(TRIAGE_PROMPT, user, TRIAGE_CATEGORIES))
    latency = round(time.time() - t0, 1)
    httpx.patch(f"{INCIDENTS}/incidents/{incident_id}", json={
        "category": result["category"], "agent_summary": json.dumps(result), "agent_latency_s": latency})
    return result, latency


def ask(question):
    return asyncio.run(run_agent(QA_PROMPT, question, QA_CATEGORIES))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--incident", type=int)
    g.add_argument("--ask")
    a = p.parse_args()
    if a.incident:
        res, secs = triage_incident(a.incident)
        print(json.dumps({**res, "latency_s": secs}, indent=2))
    else:
        print(json.dumps(ask(a.ask), indent=2))
