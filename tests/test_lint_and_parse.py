"""Crontab parsing, lint rules, and the SVG renderer."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

from cronscope.crontab import parse_crontab
from cronscope.lint import Level, lint
from cronscope.svg import render_week

NOW = datetime(2026, 1, 1, 0, 0)


def rules(text, *, system=False):
    ct = parse_crontab(text, system=system)
    return {i.rule for i in lint(ct, now=NOW)}


# ── crontab parsing ─────────────────────────────────────────────────────────

def test_parses_jobs_and_skips_comments_and_blanks():
    ct = parse_crontab("# c\n\n0 0 * * * /a\n*/5 * * * * /b\n")
    assert len(ct.jobs) == 2
    assert ct.jobs[0].command == "/a"
    assert ct.jobs[0].line_no == 3


def test_captures_environment_assignments():
    ct = parse_crontab('MAILTO="ops@x.com"\nPATH=/usr/bin\n0 0 * * * /a\n')
    assert ct.env["MAILTO"] == "ops@x.com"
    assert ct.env["PATH"] == "/usr/bin"
    assert len(ct.jobs) == 1


def test_macro_jobs_parse():
    ct = parse_crontab("@daily /backup\n@reboot /warmup\n")
    assert len(ct.jobs) == 2
    assert ct.jobs[1].schedule.is_reboot


def test_system_crontab_has_user_column():
    ct = parse_crontab("0 0 * * * root /backup\n", system=True)
    assert ct.jobs[0].user == "root"
    assert ct.jobs[0].command == "/backup"


def test_malformed_line_is_captured_as_error_not_a_crash():
    ct = parse_crontab("99 0 * * * /a\n0 0 * * * /good\n")
    assert len(ct.errors) == 1
    assert ct.errors[0].line_no == 1
    assert len(ct.jobs) == 1          # the good line still parsed


def test_schedule_without_command_is_an_error():
    ct = parse_crontab("0 0 * * *\n")
    assert ct.errors and not ct.jobs


# ── lint rules ──────────────────────────────────────────────────────────────

def test_never_runs_flagged():
    assert "never-runs" in rules("0 0 30 2 * /a >/dev/null\n")


def test_never_runs_is_error_level():
    issues = lint(parse_crontab("0 0 31 4 * /a >/dev/null\n"), now=NOW)
    assert any(i.rule == "never-runs" and i.level == Level.ERROR for i in issues)


def test_dom_dow_trap_flagged():
    assert "dom-dow-or" in rules("0 0 13 * 5 /a >/dev/null\n")


def test_dom_dow_trap_not_flagged_when_one_is_star():
    assert "dom-dow-or" not in rules("0 0 13 * * /a >/dev/null\n")
    assert "dom-dow-or" not in rules("0 0 * * 5 /a >/dev/null\n")


def test_every_minute_flagged():
    assert "every-minute" in rules("* * * * * /a >/dev/null\n")


def test_unescaped_percent_flagged():
    assert "percent-literal" in rules("0 0 * * * echo %Y >/dev/null\n")


def test_escaped_percent_not_flagged():
    assert "percent-literal" not in rules("0 0 * * * echo \\%Y >/dev/null\n")


def test_missing_redirect_flagged_but_suppressed_by_empty_mailto():
    assert "no-redirect" in rules("0 0 * * * /a\n")
    assert "no-redirect" not in rules('MAILTO=""\n0 0 * * * /a\n')


def test_collision_flagged_for_midnight_stampede():
    text = ("0 0 * * * /a >/dev/null\n"
            "0 0 * * * /b >/dev/null\n"
            "0 0 * * * /c >/dev/null\n")
    assert "collision" in rules(text)


def test_no_collision_when_staggered():
    text = ("0 0 * * * /a >/dev/null\n"
            "1 0 * * * /b >/dev/null\n"
            "2 0 * * * /c >/dev/null\n")
    assert "collision" not in rules(text)


def test_clean_crontab_has_no_issues():
    text = 'MAILTO=""\n30 3 * * 1 /weekly >/dev/null 2>&1\n'
    assert lint(parse_crontab(text), now=NOW) == []


# ── svg ─────────────────────────────────────────────────────────────────────

def test_svg_is_well_formed_xml():
    ct = parse_crontab("0 0 * * * /a\n*/15 * * * * /b\n")
    svg = render_week(ct, title="test")
    root = ET.fromstring(svg)                 # raises on malformed XML
    assert root.tag.endswith("svg")


def test_svg_reports_collisions_in_its_label():
    text = ("0 0 * * * /a\n0 0 * * * /b\n0 0 * * * /c\n")
    svg = render_week(parse_crontab(text))
    root = ET.fromstring(svg)
    label = root.get("aria-label", "")
    assert "colliding" in label
    # 7 midnights in the reference week each collide.
    assert "7 colliding" in label


def test_svg_handles_empty_crontab():
    svg = render_week(parse_crontab("# nothing here\n"))
    assert ET.fromstring(svg).tag.endswith("svg")


def test_svg_ignores_reboot_jobs():
    # @reboot has no schedule; it must not crash the renderer.
    svg = render_week(parse_crontab("@reboot /warmup\n0 0 * * * /a\n"))
    assert ET.fromstring(svg) is not None
