# Security Policy

## Reporting a vulnerability

Email **henrry.220267@gmail.com** with `SECURITY` in the subject line, or open a
[private security advisory](../../security/advisories/new).

Please don't open a public issue for anything exploitable.

Include what you have: the affected file, what an attacker gets out of it, and
a way to reproduce if you have one. A rough report beats a polished one that
never gets sent.

I'll acknowledge within 72 hours and tell you whether I think it's a real issue
and roughly when it'll be fixed.

## Supported versions

The latest release on `main`. This is a small project — there are no backported
security branches.

## Scope

Findings that count:

- A `next_run` that reports the wrong fire time, or a lint rule that reports a
  schedule as clean when it never runs. cronscope's whole value is being right
  about when jobs run; a wrong answer here is the serious defect.
- Any code path that executes, installs, or edits a crontab. cronscope only
  reads and reasons about text; running anything would be a defect regardless
  of impact.

Findings that don't:

- A lint rule being too strict (a false positive). Worth an issue, not a
  security one.
- Non-standard cron extensions (seconds, `L`/`W`/`#`) not being modelled — those
  are feature requests.
