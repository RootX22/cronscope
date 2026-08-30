"""Render a crontab as a week-view heatmap: how busy each hour is, and where
jobs collide inside a single minute.

This is the shareable artefact — a self-contained SVG you can drop into a README
or a chat and immediately see the shape of your schedule: the midnight stampede
glowing hot, the quiet small hours, the red rings where several jobs land in the
same minute and spike the load.

Encoding, chosen after a per-job-colour version flooded the whole grid the
moment one job ran every 15 minutes:

  * cell background = number of job firings in that hour (cool → hot)
  * red ring         = 3+ jobs firing in the SAME minute (a real load spike)

Density is the honest signal: it does not fall apart when one job is frequent,
and "where is it hot" is exactly the question the picture should answer.

Design constraints from earlier work in this account: self-contained (no
external fonts or scripts), legible with no animation, dark palette that reads
on either a light or a dark page.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .crontab import Crontab

_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_REF = datetime(2001, 1, 1)          # a Monday, deterministic reference week

# Cool-to-hot heat ramp. Index 0 is the empty-cell base.
_HEAT = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353",
         "#f2c14e", "#f2836b", "#ff5f57"]
_BG = "#0d1117"
_GRID = "#232a33"
_LABEL = "#8b949e"
_TITLE = "#e6edf3"
_COLLISION = "#ff5f57"


def _heat_colour(count: int, hottest: int) -> str:
    """Map a firing count to a heat colour, scaled to the busiest hour."""
    if count <= 0:
        return _HEAT[0]
    if hottest <= 1:
        return _HEAT[3]
    # Buckets 1..len-1 across the observed range, so the scale always uses its
    # full width regardless of whether the peak is 4 firings or 400.
    span = len(_HEAT) - 1
    idx = 1 + round((count - 1) / max(hottest - 1, 1) * (span - 1))
    return _HEAT[min(idx, span)]


def render_week(crontab: Crontab, *, title: str = "crontab") -> str:
    left, top = 62, 82
    cell_w, cell_h = 33, 34
    width = left + 24 * cell_w + 20
    height = top + 7 * cell_h + 58

    jobs = [j for j in crontab.jobs if not j.schedule.is_reboot]
    horizon = _REF + timedelta(days=7)
    # next_run is strictly-after, so scanning from _REF would miss a job that
    # fires exactly at the reference midnight — leaving Monday 00:00 unlit while
    # every other day's midnight shows. Start one minute earlier to include it.
    scan_from = _REF - timedelta(minutes=1)

    hour_count: dict[tuple[int, int], int] = {}     # (day, hour) -> firings
    minute_hits: dict[datetime, int] = {}           # exact minute -> firings

    for job in jobs:
        for run in job.schedule.next_runs(scan_from, 20000):
            if run >= horizon:
                break
            day = (run - _REF).days
            hour_count[(day, run.hour)] = hour_count.get((day, run.hour), 0) + 1
            minute_hits[run] = minute_hits.get(run, 0) + 1

    hottest = max(hour_count.values(), default=0)
    collisions = {(( (w - _REF).days, w.hour))
                  for w, n in minute_hits.items() if n >= 3}
    total_firings = sum(hour_count.values())

    o: list[str] = []
    o.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" '
        f'aria-label="Weekly cron heatmap for {_esc(title)}: '
        f'{len(jobs)} jobs, {total_firings} firings per week, '
        f'{len(collisions)} colliding hour(s)">'
    )
    o.append(f"<title>{_esc(title)} — weekly schedule</title>")
    o.append(f'<rect width="{width}" height="{height}" rx="12" fill="{_BG}"/>')

    o.append(_text(20, 34, _TITLE, 17, f"{_esc(title)} — weekly schedule",
                   weight="700"))
    o.append(_text(20, 55, _LABEL, 12,
                   f"{len(jobs)} job(s) · {total_firings} firings/week · "
                   f"{len(collisions)} hour(s) with a 3+ job pile-up"))

    for h in range(0, 24, 3):
        x = left + h * cell_w + cell_w / 2
        o.append(_text(x, top - 10, _LABEL, 10, f"{h:02d}", anchor="middle"))

    for d, name in enumerate(_DAYS):
        y = top + d * cell_h
        o.append(_text(left - 12, y + cell_h / 2 + 4, _LABEL, 12, name, anchor="end"))
        for h in range(24):
            x = left + h * cell_w
            count = hour_count.get((d, h), 0)
            fill = _heat_colour(count, hottest)
            o.append(
                f'<rect x="{x}" y="{y}" width="{cell_w-3}" height="{cell_h-3}" '
                f'rx="4" fill="{fill}" stroke="{_GRID}" stroke-width="0.5"/>'
            )
            if (d, h) in collisions:
                o.append(
                    f'<rect x="{x+0.5}" y="{y+0.5}" width="{cell_w-4}" '
                    f'height="{cell_h-4}" rx="4" fill="none" '
                    f'stroke="{_COLLISION}" stroke-width="2"/>'
                )

    # Heat legend.
    ly = top + 7 * cell_h + 26
    o.append(_text(left, ly, _LABEL, 10.5, "less"))
    lx = left + 34
    for c in _HEAT[1:]:
        o.append(f'<rect x="{lx}" y="{ly-10}" width="13" height="13" rx="2" fill="{c}"/>')
        lx += 16
    o.append(_text(lx + 4, ly, _LABEL, 10.5, "more firings/hour"))

    # Collision key.
    o.append(f'<rect x="{lx+150}" y="{ly-11}" width="13" height="13" rx="2" '
             f'fill="none" stroke="{_COLLISION}" stroke-width="2"/>')
    o.append(_text(lx + 169, ly, _LABEL, 10.5, "minute collision"))

    o.append("</svg>")
    return "".join(o)


def _text(x, y, fill, size, content, *, anchor="start", weight="400") -> str:
    font = 'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"'
    return (f'<text x="{x}" y="{y}" {font} font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{_esc(content)}</text>')


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
