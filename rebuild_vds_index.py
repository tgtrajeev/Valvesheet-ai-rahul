"""
rebuild_vds_index.py
====================
Scans pms_extracted.json for ALL piping classes and their valve_assignments,
identifies NEW VDS codes vs. the existing vds_index.json, prints a full report,
and writes an updated vds_index.json that preserves old entries and adds new ones.

Usage:
    python rebuild_vds_index.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).parent
PMS_JSON   = BASE / "app" / "data" / "pms_extracted.json"
INDEX_JSON = BASE / "app" / "data" / "projects" / "fpso-albacora" / "vds_index.json"
RS_INDEX   = BASE / "app" / "data" / "projects" / "render-sync" / "vds_index.json"


# ── helpers ────────────────────────────────────────────────────────────────

def iter_vds_codes(raw_codes: list) -> list[str]:
    """Normalise comma-separated VDS code cells (matches vds_builder.py)."""
    out: list[str] = []
    for raw in raw_codes or []:
        if not isinstance(raw, str):
            continue
        for part in raw.split(","):
            code = part.strip().upper()
            if code:
                out.append(code)
    return list(dict.fromkeys(out))


def entry_key(e: dict) -> tuple:
    return (
        e["vds_code"],
        e["piping_class"],
        e.get("valve_type", ""),
        e.get("nps_min"),
        e.get("nps_max"),
    )


# ── main ───────────────────────────────────────────────────────────────────

def main():
    # 1. Load PMS data
    print(f"\n{'='*70}")
    print("PMS → VDS Index Rebuild Report")
    print(f"{'='*70}\n")

    pms_data: dict = json.loads(PMS_JSON.read_text(encoding="utf-8"))
    print(f"📋  Loaded {len(pms_data)} piping classes from pms_extracted.json\n")

    # 2. Build complete new index from pms_extracted
    new_entries: list[dict] = []
    class_to_vds: dict[str, list[str]] = {}
    all_vds_from_pms: set[str] = set()

    for spec_code, pc in pms_data.items():
        vas = pc.get("valve_assignments") or []
        vds_for_class: list[str] = []

        for va in vas:
            codes = iter_vds_codes(va.get("vds_codes") or [])
            for code in codes:
                all_vds_from_pms.add(code)
                vds_for_class.append(code)
                new_entries.append({
                    "vds_code":    code,
                    "piping_class": spec_code,
                    "valve_type":  (va.get("valve_type") or "").upper(),
                    "nps_min":     va.get("nps_min"),
                    "nps_max":     va.get("nps_max"),
                })

        class_to_vds[spec_code] = sorted(set(vds_for_class))

    # 3. Load existing index
    existing_entries: list[dict] = []
    existing_keys: set[tuple] = set()
    if INDEX_JSON.exists():
        idx = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        existing_entries = idx.get("entries") or []
        existing_keys = {entry_key(e) for e in existing_entries}
        existing_vds_codes: set[str] = {e["vds_code"] for e in existing_entries}
        print(f"📂  Existing vds_index.json  → {len(existing_entries)} entries, "
              f"{len(existing_vds_codes)} unique VDS codes\n")
    else:
        existing_vds_codes = set()
        print("⚠️  No existing vds_index.json — will create fresh.\n")

    # 4. Classify: new vs existing
    truly_new_vds: set[str] = all_vds_from_pms - existing_vds_codes
    removed_vds:   set[str] = existing_vds_codes - all_vds_from_pms

    # NEW entries = ones whose key doesn't exist yet
    added_entries = [e for e in new_entries if entry_key(e) not in existing_keys]

    # 5. Merge: keep existing + add new
    merged_entries = existing_entries + added_entries
    # Deduplicate by key (existing first)
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for e in merged_entries:
        k = entry_key(e)
        if k not in seen:
            seen.add(k)
            deduped.append(e)

    # 6. Group new VDS by class
    new_vds_by_class: dict[str, list[str]] = defaultdict(list)
    for e in added_entries:
        if e["vds_code"] in truly_new_vds:
            new_vds_by_class[e["piping_class"]].append(e["vds_code"])

    # ── REPORT ────────────────────────────────────────────────────────────

    print(f"{'─'*70}")
    print(f"SUMMARY")
    print(f"{'─'*70}")
    print(f"  Total PMS classes in pms_extracted.json : {len(pms_data)}")
    print(f"  Total unique VDS codes in PMS data      : {len(all_vds_from_pms)}")
    print(f"  Existing VDS codes in index             : {len(existing_vds_codes)}")
    print(f"  NEW VDS codes (not yet indexed)         : {len(truly_new_vds)}")
    print(f"  VDS codes removed from PMS data         : {len(removed_vds)}")
    print(f"  New index entries to add                : {len(added_entries)}")
    print(f"  Final merged index entry count          : {len(deduped)}")
    print()

    # Classes with new VDS codes
    print(f"{'─'*70}")
    print(f"NEW VDS CODES BY PIPING CLASS ({len(new_vds_by_class)} classes affected)")
    print(f"{'─'*70}")
    if new_vds_by_class:
        for cls in sorted(new_vds_by_class):
            codes = sorted(set(new_vds_by_class[cls]))
            print(f"  {cls:10s} → {', '.join(codes)}")
    else:
        print("  ✅  No new VDS codes — index is already up to date.")
    print()

    # All new VDS codes (flat list)
    if truly_new_vds:
        print(f"{'─'*70}")
        print(f"ALL NEW VDS CODES ({len(truly_new_vds)} codes)")
        print(f"{'─'*70}")
        for code in sorted(truly_new_vds):
            print(f"  {code}")
        print()

    # Full class → VDS mapping
    print(f"{'─'*70}")
    print(f"COMPLETE CLASS → VDS MAPPING ({len(pms_data)} classes)")
    print(f"{'─'*70}")
    for cls in sorted(pms_data):
        codes = class_to_vds.get(cls, [])
        if codes:
            print(f"  {cls:10s} ({len(codes):3d} VDS): {', '.join(codes[:8])}"
                  + (" ..." if len(codes) > 8 else ""))
        else:
            print(f"  {cls:10s}   (0 VDS) — tubing/special class, no valve assignments")
    print()

    # 7. Write updated vds_index.json
    updated_index = {
        "project_id": "fpso-albacora",
        "entries": deduped
    }
    INDEX_JSON.write_text(
        json.dumps(updated_index, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"{'─'*70}")
    print(f"✅  Updated vds_index.json written → {len(deduped)} total entries")
    print(f"    Path: {INDEX_JSON}")

    # 8. Also write render-sync index
    RS_INDEX.parent.mkdir(parents=True, exist_ok=True)
    rs_index = {
        "project_id": "render-sync",
        "entries": [dict(e, piping_class=e["piping_class"]) for e in deduped]
    }
    RS_INDEX.write_text(
        json.dumps(rs_index, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"✅  render-sync vds_index.json written → {len(deduped)} entries")
    print(f"    Path: {RS_INDEX}")
    print(f"{'='*70}\n")

    return updated_index, truly_new_vds, class_to_vds


if __name__ == "__main__":
    main()
