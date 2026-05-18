#!/usr/bin/env python3
"""Run ``generate_datasheet`` for every VDS in the master index **and** PMS.

Collects:
  - all keys from ``all_valve_vds_index.json``; and
  - every code listed under ``valve_assignments`` / ``vds_codes`` in
    ``pms_extracted.json``

so classes that only appear in PMS are covered too.

Usage (repo root)::

    python -m scripts.validate_all_vds_datasheets
    python -m scripts.validate_all_vds_datasheets --index-only
    python -m scripts.validate_all_vds_datasheets --fail-fast
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

INDEX_PATH = REPO_ROOT / "app" / "data" / "all_valve_vds_index.json"
PMS_PATH = REPO_ROOT / "app" / "data" / "pms_extracted.json"


def _vds_from_pms(blob: dict) -> set[str]:
    out: set[str] = set()
    for _spec, d in blob.items():
        if not isinstance(d, dict):
            continue
        for a in d.get("valve_assignments") or []:
            cells = a.get("vds_codes")
            if cells is None:
                cells = [a.get("vds_code")]
            if not isinstance(cells, list):
                cells = [cells]
            for cell in cells:
                if cell is None:
                    continue
                for part in str(cell).split(","):
                    p = part.strip().upper()
                    if p:
                        out.add(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fail-fast", action="store_true", help="Stop on first error")
    ap.add_argument(
        "--index-only",
        action="store_true",
        help="Only VDS keys from all_valve_vds_index.json (skip PMS-only codes).",
    )
    args = ap.parse_args()

    codes: set[str] = set(json.loads(INDEX_PATH.read_text(encoding="utf-8")).keys())
    if not args.index_only and PMS_PATH.exists():
        pms_blob = json.loads(PMS_PATH.read_text(encoding="utf-8"))
        codes |= _vds_from_pms(pms_blob)

    ordered = sorted(codes)
    from app.engine.vds_decoder import decode_vds
    from app.engine.rule_engine import generate_datasheet

    failed: list[tuple[str, str]] = []
    for i, code in enumerate(ordered):
        try:
            dec = decode_vds(code)
            out = generate_datasheet(dec, return_provenance=False)
            if not out:
                failed.append((code, "empty result"))
            elif not str(out.get("valve_standard") or "").strip():
                failed.append((code, "empty valve_standard"))
        except Exception as e:
            failed.append((code, repr(e)))
            if args.fail_fast:
                break
        if (i + 1) % 100 == 0:
            print(f"  progress {i + 1}/{len(ordered)} …", flush=True)

    print(f"Total: {len(ordered)}  Failed: {len(failed)}")
    for c, err in failed[:50]:
        print(f"  {c}: {err}")
    if len(failed) > 50:
        print(f"  … {len(failed) - 50} more")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
