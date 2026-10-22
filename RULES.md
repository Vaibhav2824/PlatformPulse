# RULES — sprint working agreement

1. **Phase gates.** Don't start phase N+1 until phase N's "done when" in `TASK.md` is verified by running it, not by reading code.
2. **Ponytail / YAGNI.** Fewest files, stdlib first, no abstraction with one implementation, no config for values that never change. Deliberate corners get a `ponytail:` comment naming the ceiling.
3. **Pinned versions.** Every image and Python package is pinned. No `latest`.
4. **No secrets in git.** Tokens live only in `.env` (gitignored). `.env.example` lists the names. Dev-only creds (`admin/admin`) are allowed and labelled as such.
5. **Memory cap.** Every service has `mem_limit`; the stack stays under 8 GB. Check `docker stats` after each phase.
6. **₹0.** Free tiers (Groq, Slack free workspace) and OSS only.
7. **Critical review of AI output.** Every time Claude Code's output is wrong and gets corrected, add an entry to `REVIEW_LOG.md`: what it produced, what was wrong, the fix, why.
8. **Measured claims only.** Resume bullets and README numbers come from `eval/results.md`, never estimated.
9. **Tests: one runnable check per non-trivial module.** Incident service has `test_app.py`; the agent is verified by `eval.py`. The 80%-coverage/TDD rule is waived for this 5 h sprint — logged here on purpose.
10. **Read-only agent.** MCP tools only read (Trino accepts `SELECT/SHOW/DESCRIBE/EXPLAIN` only, row-capped). The agent recommends; humans remediate.
11. **One `docker compose up`.** Anything that needs a manual step is written in the README.
