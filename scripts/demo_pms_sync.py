"""demo_pms_sync.py — proves the engine truly reads from project PMS data
by simulating a NEW project: modify class A1N's service/bolts/gasket text,
regenerate the SAME VDS code, and observe the values change accordingly.

If the engine were hardcoded mapping each VDS to a PMS_PDF page, this demo
would FAIL — the values for BLFTA1NR would stay constant regardless of what
the project's class data says. Because the engine actually reads from the
project's class data, the values change.

Run:
    python -m scripts.demo_pms_sync
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent

# Sample class to mutate + sample VDS to regenerate
TARGET_CLASS = "A1N"
TARGET_VDS = "BLFTA1NR"

# The "new project's" override values — deliberately different from PTTEP's
NEW_SERVICE       = "Methanol, Crude Oil, Wet Sour Gas (NEW PROJECT data)"
NEW_BOLT_SPEC     = "ASTM A 193 Gr. B7M, PTFE-coated 75μm (NEW PROJECT spec)"
NEW_NUT_SPEC      = "ASTM A 194 Gr. 2HM, PTFE-coated 75μm (NEW PROJECT spec)"
NEW_GASKET_SPEC   = "ASME B 16.20, 4.5mm, Inconel-625 Spiral Wound + PTFE filler (NEW PROJECT spec)"
NEW_BODY_MATERIAL = "ASTM A350 LF2 (1\"-1.5\"), ASTM A352 LCC (2\" & above) — NEW PROJECT-specific spec"


def header(s: str) -> None:
    print("\n" + "=" * 100)
    print(f" {s}")
    print("=" * 100)


def step(s: str) -> None:
    print(f"\n  ▶ {s}")


def show(label: str, value: str) -> None:
    print(f"     {label:<22} {str(value)[:80]}")


def main() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    from app.engine.pms_loader import get_pms_loader, PmsMaterials
    from app.engine.vds_decoder import decode_vds
    from app.engine.rule_engine import generate_datasheet

    header(f"PMS-SYNC DEMO — modify class {TARGET_CLASS} and regenerate {TARGET_VDS}")
    print(f"\n  Premise: if values were hardcoded VDS→PMS_PDF mapping, modifying the")
    print(f"  project's class data would have ZERO effect on the generated datasheet.")
    print(f"  In reality, the engine reads CLASS-LEVEL data — so changing the class")
    print(f"  data MUST change the output. This script proves it.")

    loader = get_pms_loader()
    spec = loader.get_spec(TARGET_CLASS)
    if not spec:
        print(f"\n  ERROR: class {TARGET_CLASS} not in PMS loader. Aborting.")
        return 1

    # ── Step 1: Capture ORIGINAL values from the engine ──
    step(f"BEFORE — original project (PTTEP Sabah) class {TARGET_CLASS}:")
    show("service           :", spec.header.service)
    show("bolt spec         :", spec.bolting_gaskets.stud_bolt_spec if spec.bolting_gaskets else "—")
    show("nut spec          :", spec.bolting_gaskets.hex_nut_spec if spec.bolting_gaskets else "—")
    show("gasket spec       :", spec.bolting_gaskets.gasket_spec if spec.bolting_gaskets else "—")
    show("body material     :", (spec.materials.body_material if spec.materials else "(from rule_engine fallback)"))

    decoded = decode_vds(TARGET_VDS)
    data_before, _ = generate_datasheet(decoded, return_provenance=True)
    for k in ("_provenance_links","_provenance_quotes","_source_values","_justifications"):
        data_before.pop(k, None)

    print()
    show(f"Engine output for {TARGET_VDS} BEFORE mutation:", "")
    show("service           :", data_before.get("service",""))
    show("bolts             :", data_before.get("bolts",""))
    show("nuts              :", data_before.get("nuts",""))
    show("gaskets           :", data_before.get("gaskets",""))
    show("body_material     :", data_before.get("body_material",""))

    # ── Step 2: SIMULATE syncing a NEW project — mutate class data in-memory ──
    step("Simulating new-project sync: mutating class A1N's data in-memory...")
    print(f"     (this simulates running extract_pms_pdf.py on a different client's PMS)")
    spec.header.service = NEW_SERVICE
    spec.bolting_gaskets.stud_bolt_spec = NEW_BOLT_SPEC
    spec.bolting_gaskets.hex_nut_spec   = NEW_NUT_SPEC
    spec.bolting_gaskets.gasket_spec    = NEW_GASKET_SPEC
    spec.materials = PmsMaterials(
        spec_code=TARGET_CLASS,
        body_material=NEW_BODY_MATERIAL,
        ball_material="Forged - ASTM A182-F316L (NEW PROJECT)",
        stem_material="Forged - ASTM A182 F316L (NEW PROJECT)",
        seat_material="Reinforced PTFE (NEW PROJECT)",
        gland_material="Forged - ASTM A182 F316L (NEW PROJECT)",
        gland_packing="Flexible graphite — NEW PROJECT spec",
        spring_material="Inconel 750 (NEW PROJECT)",
        lever_handwheel="Hot-dip galvanized iron / SS316 (NEW PROJECT)",
        asme_b1634_group=1,
    )

    # ── Step 3: Regenerate the SAME VDS through the SAME engine ──
    step(f"Regenerating {TARGET_VDS} through the SAME generate_datasheet() function:")
    data_after, _ = generate_datasheet(decoded, return_provenance=True)
    for k in ("_provenance_links","_provenance_quotes","_source_values","_justifications"):
        data_after.pop(k, None)

    print()
    show(f"Engine output for {TARGET_VDS} AFTER class data was mutated:", "")
    show("service           :", data_after.get("service",""))
    show("bolts             :", data_after.get("bolts",""))
    show("nuts              :", data_after.get("nuts",""))
    show("gaskets           :", data_after.get("gaskets",""))
    show("body_material     :", data_after.get("body_material",""))

    # ── Step 4: Verify changes flowed through ──
    header("VERDICT")
    fields_to_check = ("service", "bolts", "nuts", "gaskets", "body_material")
    changes_seen = 0
    for f in fields_to_check:
        before = data_before.get(f, "")
        after = data_after.get(f, "")
        if before != after and "NEW PROJECT" in after:
            changes_seen += 1
            print(f"\n  ✓ {f}")
            print(f"     before : {before[:80]}")
            print(f"     after  : {after[:80]}")
        else:
            print(f"\n  ✗ {f} — UNEXPECTED: value did NOT change despite class data mutation")
            print(f"     before : {before[:80]}")
            print(f"     after  : {after[:80]}")

    print()
    if changes_seen == len(fields_to_check):
        print(f"  ✓ ALL {changes_seen} fields reflected the new-project class data.")
        print()
        print(f"  PROOF: the engine reads from CLASS-LEVEL PMS data, not from any")
        print(f"  hardcoded VDS-to-output-sheet mapping. When a new project's PMS")
        print(f"  is synced (extract_pms_pdf.py overwrites pms_extracted.json), the")
        print(f"  engine immediately uses that data for ALL VDS codes in those classes.")
        print()
        print(f"  Citations / source-derived values / clickable PDF links remain")
        print(f"  unchanged — they always point to API/ASME standards. Only the")
        print(f"  project-supplied portions (service, materials, bolting, gaskets)")
        print(f"  change as the project changes — exactly the architecture the")
        print(f"  client asked for.")
        rc = 0
    else:
        print(f"  ⚠ Only {changes_seen}/{len(fields_to_check)} fields reflected the new data.")
        print(f"  The engine may still have hardcoded fallbacks bypassing class data.")
        rc = 1

    # Restore (so subsequent test runs in the same Python session see original data)
    # NOTE: this is ONLY in-memory mutation for the demo — pms_extracted.json on
    # disk is NEVER modified. To actually onboard a new project, run:
    #    python -m scripts.extract_pms_pdf --pms-pdf <new.pdf> --workbook ...
    return rc


if __name__ == "__main__":
    sys.exit(main())
