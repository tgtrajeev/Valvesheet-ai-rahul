from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = REPO_ROOT / "docs" / "ISSUE_FIX_LOG.md"
OUT_DIR = REPO_ROOT / "reports" / "daily"


def _run_git(args: list[str]) -> str:
    try:
        out = subprocess.check_output(
            ["git", *args],
            cwd=str(REPO_ROOT),
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return out.strip()
    except Exception as e:
        return f"(git unavailable: {type(e).__name__})"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _extract_log_section(log_text: str, day: str) -> str:
    """Return the markdown for the given day from ISSUE_FIX_LOG.md.

    We keep it intentionally simple: pull all lines from the first heading that
    starts with `## {day}` until the next `## ` heading (or EOF).
    """
    lines = log_text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        # We allow extra suffix text after the date, e.g.:
        #   "## 2026-05-11 — BS-prefixed ball VDS must not generate"
        if ln.strip().startswith(f"## {day}"):
            start = i
            break
    if start is None:
        return ""
    out: list[str] = []
    for ln in lines[start:]:
        if out and ln.startswith("## "):
            break
        out.append(ln)
    return "\n".join(out).strip()


def _git_commits_since(day: dt.date) -> str:
    since = f"{day.isoformat()} 00:00:00"
    # One line per commit, local timezone.
    return _run_git(["log", f"--since={since}", "--pretty=format:%h  %s"])


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate daily manager update report.")
    ap.add_argument(
        "--date",
        default="today",
        help="Report date in YYYY-MM-DD, or 'today' (default).",
    )
    ap.add_argument(
        "--out",
        default="",
        help="Output path (markdown). Default: reports/daily/YYYY-MM-DD.md",
    )
    args = ap.parse_args()

    if args.date == "today":
        day = dt.date.today()
    else:
        day = dt.date.fromisoformat(args.date)

    day_str = day.isoformat()
    out_path = Path(args.out) if args.out else (OUT_DIR / f"{day_str}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    log_text = _read_text(LOG_PATH)
    log_section = _extract_log_section(log_text, day_str)
    commits = _git_commits_since(day)

    who = os.environ.get("USERNAME") or os.environ.get("USER") or ""

    body = []
    body.append(f"## Daily update — {day_str}")
    if who:
        body.append(f"- Owner: {who}")
    body.append("")

    body.append("### Issues fixed / changes made")
    if log_section:
        body.append(log_section)
    else:
        body.append(f"(No entries found in `{LOG_PATH.as_posix()}` for `{day_str}`.)")
    body.append("")

    body.append("### Commits (today)")
    if commits and not commits.startswith("(git unavailable"):
        body.append("```")
        body.append(commits)
        body.append("```")
    else:
        body.append(commits or "(No commits found.)")
    body.append("")

    out_path.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

