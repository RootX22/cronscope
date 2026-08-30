"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

from . import __version__
from .crontab import parse_crontab
from .expression import CronError, CronExpression
from .lint import Level, lint
from .svg import render_week

EXIT_OK = 0
EXIT_ISSUES = 1       # lint found something at or above the fail threshold
EXIT_USAGE = 2

_COLOURS = {
    Level.ERROR: "\033[31m",
    Level.WARNING: "\033[33m",
    Level.INFO: "\033[2m",
}
_RESET = "\033[0m"


def _use_colour(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(stream, "isatty") and stream.isatty()


def _read_input(path: str | None) -> str:
    if path in (None, "-"):
        return sys.stdin.read()
    with open(path) as fh:
        return fh.read()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cronscope",
        description="Understand a crontab: predict runs, lint mistakes, visualise the week.",
        epilog="Exit codes: 0 clean, 1 issues at/above --fail-on, 2 usage error.",
    )
    p.add_argument("file", nargs="?",
                   help="crontab file (default: stdin). Use '-' for stdin.")
    p.add_argument("--explain", metavar="EXPR",
                   help="explain a single cron expression and its next runs")
    p.add_argument("--next", type=int, default=5, metavar="N",
                   help="how many upcoming runs to show (default: 5)")
    p.add_argument("--system", action="store_true",
                   help="parse as a system crontab (leading user column)")
    p.add_argument("--svg", metavar="OUT",
                   help="write a weekly-schedule SVG to this path ('-' for stdout)")
    p.add_argument("--title", default="crontab", help="title for the SVG")
    p.add_argument("--json", action="store_true", help="emit lint results as JSON")
    p.add_argument("--fail-on", default="error",
                   choices=["info", "warning", "error", "never"],
                   help="lowest level that exits non-zero (default: error)")
    p.add_argument("-V", "--version", action="version",
                   version=f"cronscope {__version__}")
    return p


def _explain(expr: str, count: int) -> int:
    try:
        schedule = CronExpression.parse(expr)
    except CronError as exc:
        print(f"cronscope: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(f"  {expr}")
    if schedule.is_reboot:
        print("  runs once when cron starts (@reboot); no scheduled time")
        return EXIT_OK
    if schedule.dom_restricted and schedule.dow_restricted:
        print("  note: day-of-month AND day-of-week are both set — runs on EITHER")

    runs = schedule.next_runs(datetime.now(), count)
    if not runs:
        print("  this schedule never runs (no valid fire time)")
        return EXIT_OK
    print(f"  next {len(runs)} run(s):")
    for r in runs:
        print(f"    {r.strftime('%a %Y-%m-%d %H:%M')}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.explain:
        return _explain(args.explain, args.next)

    try:
        text = _read_input(args.file)
    except OSError as exc:
        print(f"cronscope: {exc}", file=sys.stderr)
        return EXIT_USAGE

    crontab = parse_crontab(text, system=args.system)

    if args.svg:
        svg = render_week(crontab, title=args.title)
        if args.svg == "-":
            sys.stdout.write(svg + "\n")
        else:
            with open(args.svg, "w") as fh:
                fh.write(svg)
            print(f"cronscope: wrote {args.svg}", file=sys.stderr)

    issues = lint(crontab, now=datetime.now())

    if args.json:
        payload = {
            "jobs": len(crontab.jobs),
            "parse_errors": [
                {"line": e.line_no, "message": e.message, "raw": e.raw}
                for e in crontab.errors
            ],
            "issues": [
                {"rule": i.rule, "level": i.level.label, "line": i.line_no,
                 "message": i.message, "detail": i.detail}
                for i in issues
            ],
        }
        json.dump(payload, sys.stdout, indent=2)
        print()
    elif not args.svg or args.svg != "-":
        _render_text(crontab, issues, sys.stdout)

    fail_levels = {"info": Level.INFO, "warning": Level.WARNING, "error": Level.ERROR}
    if args.fail_on == "never":
        return EXIT_OK
    threshold = fail_levels[args.fail_on]
    has_parse_errors = bool(crontab.errors)
    if has_parse_errors or any(i.level >= threshold for i in issues):
        return EXIT_ISSUES
    return EXIT_OK


def _render_text(crontab, issues, stream) -> None:
    colour = _use_colour(stream)

    def paint(level, text):
        return f"{_COLOURS[level]}{text}{_RESET}" if colour else text

    print(f"\n  cronscope — {len(crontab.jobs)} job(s)", file=stream)

    for e in crontab.errors:
        print(f"  {paint(Level.ERROR, '[ERROR]')} line {e.line_no}: {e.message}",
              file=stream)
        print(f"          {e.raw}", file=stream)

    if not issues and not crontab.errors:
        print("  no issues found", file=stream)
        return

    print(file=stream)
    for i in issues:
        tag = paint(i.level, f"[{i.level.label.upper()}]")
        print(f"  {tag} line {i.line_no}: {i.message}", file=stream)
        if i.detail:
            print(f"          {i.detail}", file=stream)

    counts: dict[str, int] = {}
    for i in issues:
        counts[i.level.label] = counts.get(i.level.label, 0) + 1
    summary = "  ".join(f"{n} {lvl}" for lvl, n in counts.items()) or "clean"
    print(f"\n  {summary}", file=stream)


if __name__ == "__main__":
    sys.exit(main())
