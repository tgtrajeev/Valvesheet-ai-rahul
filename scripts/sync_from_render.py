"""Sync PMS class data from the Render-deployed PMS Generator DB into the
Valvesheet AI DB and the local ``pms_extracted.json`` cache.

Usage
-----
  python -m scripts.sync_from_render                 # sync all 87 specs
  python -m scripts.sync_from_render --spec A1       # sync one spec
  python -m scripts.sync_from_render --local-only    # skip the Render DB write
  python -m scripts.sync_from_render --remote-only   # skip the local file write
"""
from __future__ import annotations

import argparse
import logging
import sys

# Allow ``python -m scripts.sync_from_render`` and ``python scripts/sync_from_render.py``.
if __package__ is None:
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.pms.render_sync import sync_all, sync_one  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sync_from_render")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", help="Sync only this piping class (e.g. A1, B25, F10)")
    ap.add_argument("--local-only", action="store_true",
                    help="Write only to app/data/pms_extracted.json (skip Render valve_agent DB)")
    ap.add_argument("--remote-only", action="store_true",
                    help="Write only to valve_agent.pms_sheets (skip local pms_extracted.json)")
    args = ap.parse_args()

    write_local  = not args.remote_only
    write_remote = not args.local_only

    if args.spec:
        data = sync_one(args.spec, write_local=write_local, write_remote=write_remote)
        if data is None:
            log.error("No row for piping_class=%s in pms_generator.pms_cache", args.spec)
            return 1
        log.info("Synced %s: %d valve assignments, %d pipe schedule rows, %d pt ratings",
                 data["spec_code"], len(data["valve_assignments"]),
                 len(data["pipe_schedule"]), len(data["pt_ratings"]))
        return 0

    result = sync_all(write_local=write_local, write_remote=write_remote)
    log.info("Sync complete: %s", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
