#!/usr/bin/env python3
"""PMS Generator × Valvesheet AI smoke matrix.

1. Pulls dropdowns from the PMS Generator API (same source as Generate PMS UI).
2. Builds a compact permutation grid using the last N pressure ratings (default: the
   tubing / EEMUA tail — e.g. ``EEMUA 20 bar``, ``Tubing`` … ``Tubing C``).
3. Calls ``POST /compute-pms`` for each combo (or ``--dry-run``).
   Invalid pairs are skipped (e.g. CUNI is only used with ``150#`` / ``EEMUA 20 bar``,
   not tubing letter ratings — matches PMS Generator catalog / 422 rules).
4. For Valvesheet AI, runs ``generate_datasheet`` for:
   - Baseline piping classes you care about (default: A30, A40, A70, TEST600, PROJ1);
   - One representative DEMO* class if present;
   - Any permutation ``class_code`` that already exists in ``app/data/pms_extracted.json``
     (after you Save + Push from the UI, or sync from generator).

Usage (repo root)::

    python -m scripts.pms_permutation_valvesheet_smoke --max 20
    python -m scripts.pms_permutation_valvesheet_smoke --dry-run
    PMS_API_BASE_URL=https://pms-generator-final.onrender.com/api python -m scripts.pms_permutation_valvesheet_smoke

Environment:
    PMS_API_BASE_URL — optional; defaults to production PMS Generator ``/api`` URL.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_PMS_API = os.environ.get(
    "PMS_API_BASE_URL", "https://pms-generator-final.onrender.com/api"
).rstrip("/")

BASELINE_CLASSES_DEFAULT = ("A30", "A40", "A70", "TEST600", "PROJ1")


def _http_json(url: str, payload: dict | None = None, *, timeout: float = 120) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {url}: {body[:500]}") from e


def _tail_tubing_ratings(active_ratings: list[str], last_n: int) -> list[str]:
    """Use the last *last_n* entries from the server's ordered list (EEMUA + Tubing family)."""
    if last_n <= 0:
        return []
    return active_ratings[-last_n:]


def _collect_vds_for_class(pms_blob: dict, spec: str) -> list[str]:
    data = pms_blob.get(spec)
    if not isinstance(data, dict):
        return []
    out: list[str] = []
    for a in data.get("valve_assignments") or []:
        cell = a.get("vds_codes") or a.get("vds_code") or ""
        if isinstance(cell, list):
            for x in cell:
                out.extend([c.strip().upper() for c in str(x).split(",") if c.strip()])
        else:
            out.extend([c.strip().upper() for c in str(cell).split(",") if c.strip()])
    return sorted(set(out))


def _pick_demo_class(pms_blob: dict) -> str | None:
    demos = sorted(k for k in pms_blob if k.startswith("DEMO") and isinstance(pms_blob[k], dict))
    return demos[0] if demos else None


def _material_ca_pairs(materials: list[str], corrosion_allowances: list[str]) -> list[tuple[str, str]]:
    """Build (material, ca) pairs accepted by PMS Generator ``/compute-pms`` (catalog rules).

    CS may not use NIL; SS316L and CUNI expect NIL (not arbitrary mm CA). Unknown
    materials fall back to the first listed corrosion allowance only.
    """
    cas = list(corrosion_allowances)
    cas_set = set(cas)
    priority_ca_cs = [x for x in ("3 mm", "6 mm", "1.5 mm") if x in cas_set]
    if not priority_ca_cs:
        priority_ca_cs = [c for c in cas if c != "NIL"]

    catalog: dict[str, list[str]] = {
        "CS": priority_ca_cs or cas[:1],
        "CS NACE": priority_ca_cs or cas[:1],
        "LTCS": priority_ca_cs or cas[:1],
        "LTCS NACE": priority_ca_cs or cas[:1],
        "SS316L": [c for c in cas if c == "NIL"],
        "SS316L NACE": [c for c in cas if c == "NIL"],
        "CUNI": [c for c in cas if c == "NIL"],
        "DSS": [c for c in cas if c == "NIL"],
        "SDSS": [c for c in cas if c == "NIL"],
    }
    pairs: list[tuple[str, str]] = []
    for m in materials:
        opts = catalog.get(m)
        if not opts:
            opts = [cas[0]] if cas else []
        for ca in opts:
            if ca in cas_set:
                pairs.append((m, ca))
                break
    return pairs


def _rating_allows_material(rating: str, material: str) -> bool:
    """PMS Generator catalog: CUNI is only valid with 150# or EEMUA 20 bar (not tubing classes)."""
    if material != "CUNI":
        return True
    return (rating or "").strip() in ("150#", "EEMUA 20 bar")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--pms-api",
        default=DEFAULT_PMS_API,
        help="PMS Generator API base (…/api)",
    )
    ap.add_argument(
        "--rating-tail",
        type=int,
        default=5,
        help="Take the last N pressure ratings from the server list (default 5 = EEMUA + Tubing block).",
    )
    ap.add_argument("--max", type=int, default=30, help="Cap permutation count (default 30).")
    ap.add_argument("--dry-run", action="store_true", help="Only print planned compute calls.")
    ap.add_argument(
        "--skip-pms-api",
        action="store_true",
        help="Do not call PMS Generator; only run Valvesheet datasheet checks on baselines.",
    )
    ap.add_argument(
        "--baselines",
        default=",".join(BASELINE_CLASSES_DEFAULT),
        help="Comma-separated piping classes to test in Valvesheet (datasheet build).",
    )
    args = ap.parse_args()
    base_url = args.pms_api.rstrip("/")

    permutation_classes: list[str] = []
    compute_failures = 0

    if args.skip_pms_api:
        print("PMS Generator: skipped (--skip-pms-api)\n")
    else:
        opt = _http_json(f"{base_url}/options/all", None)
        pr = list(opt.get("pressure_ratings") or [])
        dis = set(opt.get("disabled_pressure_ratings") or [])
        active = [r for r in pr if r not in dis]
        ratings = _tail_tubing_ratings(active, args.rating_tail)
        materials = ["CS", "SS316L", "CUNI"]
        cas_all = list(opt.get("corrosion_allowances") or [])
        mat_ca = _material_ca_pairs(materials, cas_all)
        services_all = list(opt.get("services") or [])
        services = []
        for want in ("Hydro Carbon service", "Corrosive Chemical Service"):
            if want in services_all:
                services.append(want)
        if len(services) < 2 and services_all:
            services = [services_all[0], services_all[min(1, len(services_all) - 1)]]
        if len(services) < 1:
            print("ERROR: no services from API", file=sys.stderr)
            return 2

        grid = [
            (r, m, c, s)
            for r, (m, c), s in itertools.product(ratings, mat_ca, services)
            if _rating_allows_material(r, m)
        ][: args.max]

        print(f"PMS API: {base_url}")
        print(f"Active ratings ({len(active)}): last {args.rating_tail} → {ratings}")
        print(f"Material↔CA pairs (catalog-safe): {mat_ca}")
        print(f"Services: {services}")
        print(f"Permutations (capped {args.max}): {len(grid)}")

        if args.dry_run:
            for t in grid:
                print("  would compute:", t)
        else:
            for rating, material, ca, service in grid:
                payload = {
                    "rating": rating,
                    "material": material,
                    "corrosion_allowance": ca,
                    "service": service,
                    "design_pressure_barg": None,
                    "design_temp_c": None,
                    "mdmt_c": None,
                    "joint_type": "Seamless",
                }
                try:
                    r = _http_json(f"{base_url}/compute-pms", payload)
                    cc = str(r.get("class_code") or "").strip().upper()
                    if cc:
                        permutation_classes.append(cc)
                    print(f"  OK {rating!r} + {material} + {ca} + {service[:40]}… → {cc or '?'}")
                except Exception as e:
                    compute_failures += 1
                    print(f"  FAIL {rating!r} + {material} + {ca}: {e}")
        print()

    pms_path = REPO_ROOT / "app" / "data" / "pms_extracted.json"
    if not pms_path.exists():
        print("No pms_extracted.json — skip Valvesheet checks.")
        return 0

    pms_blob = json.loads(pms_path.read_text(encoding="utf-8"))
    baselines = [x.strip().upper() for x in args.baselines.split(",") if x.strip()]
    demo = _pick_demo_class(pms_blob)
    if demo:
        baselines = list(dict.fromkeys([*baselines, demo]))

    # Datasheet pass: baselines + permutation hits already in JSON
    to_test_specs = list(dict.fromkeys(baselines))
    for cc in sorted(set(permutation_classes)):
        if cc in pms_blob and cc not in to_test_specs:
            to_test_specs.append(cc)

    print("\n--- Valvesheet generate_datasheet ---")
    from app.engine.vds_decoder import decode_vds
    from app.engine.rule_engine import generate_datasheet

    failed: list[tuple[str, str]] = []
    total = 0
    for spec in to_test_specs:
        codes = _collect_vds_for_class(pms_blob, spec)
        if not codes:
            print(f"  {spec}: no VDS in pms_extracted (skipped)")
            continue
        print(f"  {spec}: {len(codes)} VDS")
        for c in codes:
            total += 1
            try:
                dec = decode_vds(c)
                out = generate_datasheet(dec, return_provenance=False)
                if not out or not str(out.get("valve_standard") or "").strip():
                    failed.append((c, "empty valve_standard"))
            except Exception as e:
                failed.append((c, repr(e)))

    print(f"\nDatasheet checks: {total} codes, {len(failed)} failures")
    for c, err in failed[:30]:
        print(f"  {c}: {err}")
    if len(failed) > 30:
        print(f"  … and {len(failed) - 30} more")
    if compute_failures:
        print(f"\nPMS compute-pms failures: {compute_failures} (see above)")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
