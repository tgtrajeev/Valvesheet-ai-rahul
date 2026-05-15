"""Render PMS sync status check.

Pings both Render databases, lists spec counts on each side, and shows which
piping classes are in the PMS Generator DB but **not yet** in the Valvesheet
AI DB (i.e. need a sync).

Usage
-----
  python -m scripts.check_render_sync           # full status
  python -m scripts.check_render_sync --diff    # only show out-of-sync specs
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

# Allow `python scripts/check_render_sync.py` and `python -m scripts.check_render_sync`.
if __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

GEN_URL  = os.environ.get("PMS_GENERATOR_DATABASE_URL", "")
VALVE_URL = os.environ.get("VALVE_AGENT_DATABASE_URL", "")


def _check(label: str, url: str) -> tuple[bool, str]:
    if not url:
        return False, "URL not set in .env"
    try:
        c = psycopg2.connect(url, connect_timeout=10)
        with c.cursor() as cur:
            cur.execute("SELECT version()")
            v = cur.fetchone()[0].split(",")[0]
        c.close()
        return True, v
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _gen_inventory() -> list[tuple[str, datetime | None]]:
    c = psycopg2.connect(GEN_URL, connect_timeout=10)
    try:
        with c.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (piping_class)
                       piping_class, updated_at
                FROM pms_cache
                ORDER BY piping_class, updated_at DESC NULLS LAST
                """
            )
            return cur.fetchall()
    finally:
        c.close()


def _valve_inventory() -> list[tuple[str, datetime | None]]:
    c = psycopg2.connect(VALVE_URL, connect_timeout=10)
    try:
        with c.cursor() as cur:
            cur.execute(
                """
                SELECT spec_code, MAX(synced_at)
                FROM pms_sheets
                WHERE project_id = 'render-sync'
                GROUP BY spec_code
                ORDER BY spec_code
                """
            )
            return cur.fetchall()
    finally:
        c.close()


def _fmt_ts(ts: datetime | None) -> str:
    if ts is None:
        return "-"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.strftime("%Y-%m-%d %H:%M UTC")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--diff", action="store_true",
                    help="Only show specs that need syncing (in source but not in valve_agent)")
    args = ap.parse_args()

    print("=" * 70)
    print("PMS Render Sync — Health Check")
    print("=" * 70)
    print()

    # 1. Connectivity
    print("Connectivity:")
    ok_g, msg_g = _check("pms_generator", GEN_URL)
    ok_v, msg_v = _check("valve_agent",   VALVE_URL)
    print(f"  PMS Generator DB (source):  {'OK' if ok_g else 'FAIL'}  {msg_g}")
    print(f"  Valvesheet AI DB (target):  {'OK' if ok_v else 'FAIL'}  {msg_v}")
    print()
    if not (ok_g and ok_v):
        print("Connection failed. Check PMS_GENERATOR_DATABASE_URL and")
        print("VALVE_AGENT_DATABASE_URL in .env.")
        return 1

    # 2. Inventory
    gen_rows = _gen_inventory()
    val_rows = _valve_inventory()
    gen_map = {pc.upper(): ts for pc, ts in gen_rows}
    val_map = {sc.upper(): ts for sc, ts in val_rows}

    def _as_utc(ts: datetime | None) -> datetime | None:
        if ts is None:
            return None
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)

    not_synced = sorted(set(gen_map) - set(val_map))
    stale      = sorted(
        pc for pc in set(gen_map) & set(val_map)
        if gen_map[pc] is not None and val_map[pc] is not None
        and _as_utc(gen_map[pc]) > _as_utc(val_map[pc])  # type: ignore[operator]
    )
    extra_in_valve = sorted(set(val_map) - set(gen_map))

    if not args.diff:
        print(f"PMS Generator DB has  : {len(gen_rows)} piping classes")
        print(f"Valvesheet AI DB has  : {len(val_rows)} synced classes (project='render-sync')")
        print()

    print(f"Out-of-sync summary (run `python -m scripts.sync_from_render` to fix):")
    print(f"  NEW in PMS Generator, NOT in valve_agent : {len(not_synced)}")
    print(f"  STALE in valve_agent (source newer)      : {len(stale)}")
    print(f"  ORPHAN in valve_agent (not in source)    : {len(extra_in_valve)}")
    print()

    def _table(label: str, codes: list[str]) -> None:
        if not codes:
            return
        print(f"--- {label} ({len(codes)}) ---")
        for pc in codes[:30]:
            gts = _fmt_ts(gen_map.get(pc))
            vts = _fmt_ts(val_map.get(pc))
            print(f"  {pc:10}  source={gts:22}  target={vts}")
        if len(codes) > 30:
            print(f"  ...and {len(codes) - 30} more")
        print()

    _table("NEW (need first sync)", not_synced)
    _table("STALE (need re-sync)",  stale)
    _table("ORPHAN (only in valve_agent)", extra_in_valve)

    if not (not_synced or stale or extra_in_valve):
        print("Everything in sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
