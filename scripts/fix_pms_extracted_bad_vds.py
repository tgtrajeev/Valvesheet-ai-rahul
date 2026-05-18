"""One-off fix for bad vds_codes in pms_extracted.json (USE GATE VALVE, NAB)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "app" / "data" / "pms_extracted.json"


def _patch_nab_placeholder(blob: dict, spec: str) -> int:
    """Replace mistaken ``NAB`` material shorthand in ``vds_codes`` with real VDS strings."""
    n = 0
    sc = spec.upper().strip()
    fix_map = {
        "ball": [f"BLFT{sc}F", f"BLRT{sc}F"],
        "gate": [f"GAYM{sc}F"],
        "globe": [f"GLYM{sc}F"],
        "check": [f"CHPM{sc}F", f"CHSM{sc}F", f"CHDM{sc}F"],
        "butterfly": [f"BFWT{sc}F"],
    }
    for a in blob.get("valve_assignments") or []:
        if a.get("vds_codes") != ["NAB"]:
            continue
        vt = (a.get("valve_type") or "").lower()
        if vt in fix_map:
            a["vds_codes"] = fix_map[vt]
            a["spec_code"] = a.get("spec_code") or sc
            n += 1
    return n


def main() -> None:
    d = json.loads(P.read_text(encoding="utf-8"))
    rm_use = 0
    for spec, blob in d.items():
        if not isinstance(blob, dict):
            continue
        va = blob.get("valve_assignments") or []
        new_va = []
        for a in va:
            vc = a.get("vds_codes") or []
            if vc == ["USE GATE VALVE"]:
                rm_use += 1
                continue
            new_va.append(a)
        if len(new_va) != len(va):
            blob["valve_assignments"] = new_va
    print("removed USE GATE VALVE rows:", rm_use)

    nab = 0
    for spec, blob in d.items():
        if not isinstance(blob, dict):
            continue
        nab += _patch_nab_placeholder(blob, spec)
    print("patched NAB placeholder rows:", nab)

    P.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", P)


if __name__ == "__main__":
    main()
