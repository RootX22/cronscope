"""Lint rules: the cron mistakes that cause real incidents.

Each rule is a small function returning zero or more Issues. The rules that
carry the most weight are the ones catching a job that *silently does the wrong
thing* — a schedule that never fires, or the day-of-month/day-of-week trap —
because those produce no error and no log; the job just isn't there when you
needed it, or fires on days you never intended.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum

from .crontab import Crontab, Job


class Level(IntEnum):
    INFO = 0
    WARNING = 1
    ERROR = 2

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass
class Issue:
    rule: str
    level: Level
    line_no: int
    message: str
    detail: str = ""


def lint(crontab: Crontab, *, now: datetime | None = None) -> list[Issue]:
    now = now or datetime.now()
    issues: list[Issue] = []
    for job in crontab.jobs:
        issues.extend(_never_runs(job, now))
        issues.extend(_dom_dow_trap(job))
        issues.extend(_too_frequent(job))
        issues.extend(_missing_redirect(job, crontab))
        issues.extend(_percent_unescaped(job))
    issues.extend(_collisions(crontab))
    issues.sort(key=lambda i: (i.line_no, -int(i.level)))
    return issues


def _never_runs(job: Job, now: datetime) -> list[Issue]:
    """A schedule with no next run in eight years never fires. The classic is
    a day-of-month that cannot occur in the chosen month — 30 February, 31 April."""
    if job.schedule.is_reboot:
        return []
    if job.schedule.next_run(now) is None:
        return [Issue(
            rule="never-runs", level=Level.ERROR, line_no=job.line_no,
            message="This schedule never runs",
            detail=("No valid fire time exists — usually a day-of-month that "
                    "cannot occur in the given month (e.g. Feb 30, Apr 31)."),
        )]
    return []


def _dom_dow_trap(job: Job) -> list[Issue]:
    """Both day fields restricted means OR, not AND — a frequent surprise."""
    s = job.schedule
    if s.is_reboot:
        return []
    if s.dom_restricted and s.dow_restricted:
        return [Issue(
            rule="dom-dow-or", level=Level.WARNING, line_no=job.line_no,
            message="Day-of-month AND day-of-week are both set: this runs on EITHER",
            detail=("cron runs the job when the day-of-month OR the weekday "
                    "matches — not only when both do. '0 0 13 * 5' runs every "
                    "Friday and on the 13th, not only Friday the 13th. If you "
                    "meant one specific day, leave the other as '*'."),
        )]
    return []


def _too_frequent(job: Job) -> list[Issue]:
    """Every-minute jobs are usually a mistake or a load risk; flag as info."""
    s = job.schedule
    if s.is_reboot:
        return []
    if len(s.minutes) == 60 and len(s.hours) == 24:
        return [Issue(
            rule="every-minute", level=Level.INFO, line_no=job.line_no,
            message="Runs every minute",
            detail=("1440 times a day. Intended for some jobs, a resource risk "
                    "for heavy ones — make sure this is deliberate."),
        )]
    return []


def _missing_redirect(job: Job, crontab: Crontab) -> list[Issue]:
    """Un-redirected output is emailed by cron. Without MAILTO that is either
    noise the operator never reads or, worse, command output leaking by email."""
    if job.schedule.is_reboot:
        return []
    cmd = job.command
    if ">" in cmd or "2>&1" in cmd or "| mail" in cmd:
        return []
    # If MAILTO is empty, cron discards output and there is nothing to warn about.
    if crontab.env.get("MAILTO", None) == "":
        return []
    return [Issue(
        rule="no-redirect", level=Level.INFO, line_no=job.line_no,
        message="Output is not redirected",
        detail=("Anything the command prints is emailed by cron. Append "
                "'>/var/log/<job>.log 2>&1', or set MAILTO=\"\" to discard it."),
    )]


def _percent_unescaped(job: Job) -> list[Issue]:
    """An unescaped % in a cron command is turned into a newline and everything
    after it is fed to the command on stdin — a genuinely baffling failure."""
    cmd = job.command
    # A % preceded by a backslash is escaped and fine.
    stripped = cmd.replace("\\%", "")
    if "%" in stripped:
        return [Issue(
            rule="percent-literal", level=Level.WARNING, line_no=job.line_no,
            message="Unescaped '%' in command",
            detail=("cron converts an unescaped '%' to a newline and passes the "
                    "remainder as stdin. This breaks date formats like "
                    "date +%Y. Escape each '%' as '\\%'."),
        )]
    return []


def _collisions(crontab: Crontab) -> list[Issue]:
    """Jobs that fire at the same minute pile their load on top of each other.

    Detected by sampling the next fire times of every job over a window and
    counting minutes where three or more land together — the classic midnight
    stampede where every daily job runs at 00:00.
    """
    base = datetime(2001, 1, 1)         # a fixed reference; Monday, non-leap year
    horizon = base + timedelta(days=7)
    hits: dict[datetime, list[Job]] = {}

    for job in crontab.jobs:
        if job.schedule.is_reboot:
            continue
        for run in job.schedule.next_runs(base, 2016):   # a week of minutes max
            if run > horizon:
                break
            hits.setdefault(run, []).append(job)

    worst = max((len(js) for js in hits.values()), default=0)
    if worst < 3:
        return []

    # Report the single worst pile-up rather than every colliding minute, so the
    # output points at the problem instead of drowning in it.
    when, jobs = max(hits.items(), key=lambda kv: len(kv[1]))
    lines = ", ".join(f"line {j.line_no}" for j in jobs)
    return [Issue(
        rule="collision", level=Level.WARNING, line_no=jobs[0].line_no,
        message=f"{len(jobs)} jobs fire in the same minute",
        detail=(f"At {when.strftime('%a %H:%M')} these all run at once ({lines}). "
                "Simultaneous heavy jobs cause load spikes — stagger them across "
                "a few minutes."),
    )]
