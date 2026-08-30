"""Parse a whole crontab file into jobs, keeping line numbers for diagnostics.

Handles the shapes a real crontab takes:
  * comments (# ...) and blank lines
  * environment assignments (MAILTO="", PATH=/usr/bin) — captured, not run
  * five-field entries and @macro entries
  * an optional leading user column (system crontabs in /etc/cron.d and
    /etc/crontab have one; a user's own crontab does not)

The user-column ambiguity is resolved structurally: if, after the schedule, the
first remaining token is a bare word and the token after it exists, and treating
the first as a user leaves a plausible command, we keep it — but only in
system mode, which the caller selects. Guessing per-line would misread commands
that happen to start with a bare word.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .expression import CronError, CronExpression

_ENV_ASSIGN = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')


@dataclass
class Job:
    line_no: int
    schedule: CronExpression
    command: str
    raw: str
    user: str = ""            # populated only for system crontabs

    @property
    def expr(self) -> str:
        return self.schedule.raw


@dataclass
class ParseError:
    line_no: int
    raw: str
    message: str


@dataclass
class Crontab:
    jobs: list[Job] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    errors: list[ParseError] = field(default_factory=list)


def parse_crontab(text: str, *, system: bool = False) -> Crontab:
    """Parse crontab text. `system=True` expects a leading user column."""
    result = Crontab()

    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        env = _ENV_ASSIGN.match(stripped)
        if env and not stripped.startswith("@"):
            key, val = env.group(1), env.group(2)
            # Strip one layer of matching quotes, as cron does.
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            result.env[key] = val
            continue

        try:
            job = _parse_job_line(i, stripped, system=system)
            result.jobs.append(job)
        except CronError as exc:
            result.errors.append(ParseError(i, stripped, str(exc)))

    return result


def _parse_job_line(line_no: int, line: str, *, system: bool) -> Job:
    user = ""

    if line.startswith("@"):
        macro, _, rest = line.partition(" ")
        if system:
            user, rest = _split_user(rest)
        schedule = CronExpression.parse(macro)
        command = rest.strip()
    else:
        parts = line.split(None, 5)
        if len(parts) < 6:
            # Not enough columns for five schedule fields plus a command.
            raise CronError(f"expected 5 schedule fields and a command: {line!r}")
        schedule = CronExpression.parse(" ".join(parts[:5]))
        rest = parts[5]
        if system:
            user, rest = _split_user(rest)
        command = rest.strip()

    if not command:
        raise CronError("schedule has no command")

    return Job(line_no=line_no, schedule=schedule, command=command,
               raw=line, user=user)


def _split_user(rest: str) -> tuple[str, str]:
    """Peel a leading user column off a system-crontab command."""
    bits = rest.split(None, 1)
    if not bits:
        return "", rest
    if len(bits) == 1:
        return bits[0], ""
    return bits[0], bits[1]
