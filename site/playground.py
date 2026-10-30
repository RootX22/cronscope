"""Bridge between the browser page and cronscope, run inside Pyodide.

The page passes the visitor's local time in, because Python in the browser does
not know the visitor's time zone, and next-run predictions are only useful in it.
Results go back as JSON so the page never touches Python objects directly.
"""

from __future__ import annotations

import json
from datetime import datetime

from cronscope import CronError, CronExpression, lint, parse_crontab
from cronscope.svg import render_week

UPCOMING_RUNS = 3
EXPLAIN_RUNS = 5


def analyse(text: str, system: bool, now_iso: str) -> str:
    now = datetime.fromisoformat(now_iso)
    crontab = parse_crontab(text, system=system)
    jobs = [
        {
            "line": job.line_no,
            "expr": job.expr,
            "command": job.command,
            "user": job.user,
            "reboot": job.schedule.is_reboot,
            "runs": [] if job.schedule.is_reboot else [
                run.isoformat() for run in job.schedule.next_runs(now, UPCOMING_RUNS)
            ],
        }
        for job in crontab.jobs
    ]
    return json.dumps({
        "jobs": jobs,
        "errors": [
            {"line": e.line_no, "message": e.message, "raw": e.raw} for e in crontab.errors
        ],
        "issues": [
            {"rule": i.rule, "level": i.level.label, "line": i.line_no,
             "message": i.message, "detail": i.detail}
            for i in lint(crontab, now=now)
        ],
        "svg": render_week(crontab, title="your crontab"),
    })


def explain(expr: str, now_iso: str) -> str:
    try:
        schedule = CronExpression.parse(expr)
    except CronError as exc:
        return json.dumps({"error": str(exc)})
    runs = [] if schedule.is_reboot else schedule.next_runs(
        datetime.fromisoformat(now_iso), EXPLAIN_RUNS)
    return json.dumps({
        "reboot": schedule.is_reboot,
        "either": schedule.dom_restricted and schedule.dow_restricted,
        "runs": [run.isoformat() for run in runs],
    })
