"""Verify bug-sheet VDS expectations against generate_datasheet (rule engine + prune)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engine.rule_engine import generate_datasheet  # noqa: E402
from app.engine.vds_decoder import decode_vds  # noqa: E402


BF_CODES = [
    "VDS-BFWTB4R", "VDS-BFWTD4R", "VDS-BFWTA5R", "VDS-BFWTA6R", "VDS-BFWTA25R", "VDS-BFWTB25R",
    "VDS-BFWTD25R", "VDS-BFWTA30F", "VDS-BFWTA40F", "VDS-BFWTA50F", "VDS-BFWTA51F",
    "BFWTA3R", "BFWTA10R", "BFWTA52F", "BFWTA60F", "BFWTA4R",
]

GL_CODES = [
    "VDS-GLYMA2NR", "VDS-GLYMB2NR", "VDS-GLYMD2NR", "VDS-GLYME2NJ", "VDS-GLYMF2NJ", "VDS-GLYMG2NJ",
    "VDS-GLYMA1LR", "VDS-GLYMB1LR", "VDS-GLYMD1LR", "VDS-GLYME1LJ", "VDS-GLYMF1LJ", "VDS-GLYMG1LJ",
    "VDS-GLYMA1LNR", "VDS-GLYMB1LNR", "VDS-GLYMD1LNR", "VDS-GLYME1LNJ", "VDS-GLYMF1LNJ", "VDS-GLYMG1LNJ",
    "VDS-GLYMA1NR", "VDS-GLYMB1NR", "VDS-GLYMD1NR", "VDS-GLYME1NJ", "VDS-GLYMF1NJ", "VDS-GLYMG1NJ",
    "VDS-GLYMA2LNR", "VDS-GLYMB2LNR", "VDS-GLYMD2LNR", "VDS-GLYME2LNJ", "VDS-GLYMF2LNJ", "VDS-GLYMG2LNJ",
    "VDS-GLYMA10NR", "VDS-GLYMB10NR", "VDS-GLYMD10NR", "VDS-GLYME10NJ", "VDS-GLYMF10NJ", "VDS-GLYMG10NJ",
    "VDS-GLYMA3R", "VDS-GLYMA4R", "VDS-GLYMB4R", "VDS-GLYMD4R", "VDS-GLYMA5R", "VDS-GLYMA6R",
    "VDS-GLYMA10R", "VDS-GLYMB10R", "VDS-GLYMD10R", "VDS-GLYME10J", "VDS-GLYMF10J", "VDS-GLYMG10J",
    "VDS-GLYMA20R", "VDS-GLYMB20R", "VDS-GLYMD20R", "VDS-GLYME20J", "VDS-GLYMF20J", "VDS-GLYMG20J",
    "VDS-GLYMA20NR", "VDS-GLYMB20NR", "VDS-GLYMD20NR", "VDS-GLYME20NJ", "VDS-GLYMF20NJ", "VDS-GLYMG20NJ",
    "VDS-GLYMA25R", "VDS-GLYMB25R", "VDS-GLYMD25R", "VDS-GLYME25R", "VDS-GLYMF25R", "VDS-GLYMG25R",
    "VDS-GLYMA25NR", "VDS-GLYMB25NR", "VDS-GLYMD25NR", "VDS-GLYME25NR", "VDS-GLYMF25NR", "VDS-GLYMG25NR",
    "VDS-GLYMA30F", "VDS-GLYMA40F", "VDS-GLYMA50F", "VDS-GLYMA51F", "VDS-GLYMA52F", "VDS-GLYMA60F", "VDS-GLYMA70R",
]

DB_CODES = [
    "DBRPF1JT", "DBFPT80BJT", "DBRPG25NJ", "DBRPE1J", "DBRPF1JT", "DBRPG1JT", "DBRPF25NJ",
    "VDS-DBRPE1JT", "VDS-DBRPF1J", "VDS-DBRPG1JT", "VDS-DBRPG1J", "VDS-DBRMG1J",
    "VDS-DBRPE1NJT", "VDS-DBRPE1NJ", "VDS-DBRPF1NJT", "VDS-DBRPF1NJ", "VDS-DBRPG1NJT", "VDS-DBRPG1NJ", "VDS-DBRMG1NJ",
    "VDS-DBRPE2NJT", "VDS-DBRPE2NJ", "VDS-DBRPF2NJT", "VDS-DBRPF2NJ", "VDS-DBRPG2NJT", "VDS-DBRPG2NJ", "VDS-DBRMG2NJ",
    "VDS-DBRPE1LJT", "VDS-DBRPE1LJ", "VDS-DBRPF1LJT", "VDS-DBRPF1LJ", "VDS-DBRPG1LJT", "VDS-DBRPG1LJ", "VDS-DBRMG1LJ",
    "VDS-DBRPE1LNJT", "VDS-DBRPE1LNJ", "VDS-DBRPF1LNJT", "VDS-DBRPF1LNJ", "VDS-DBRPG1LNJT", "VDS-DBRPG1LNJ", "VDS-DBRMG1LNJ",
    "VDS-DBRPE2LNJT", "VDS-DBRPE2LNJ", "VDS-DBRPF2LNJT", "VDS-DBRPF2LNJ", "VDS-DBRPG2LNJT", "VDS-DBRPG2LNJ", "VDS-DBRMG2LNJ",
    "VDS-DBRPE10JT", "VDS-DBRPE10J", "VDS-DBRPF10JT", "VDS-DBRPF10J", "VDS-DBRPG10JT", "VDS-DBRPG10J", "VDS-DBRMG10J",
    "VDS-DBRPE10NJT", "VDS-DBRPE10NJ", "VDS-DBRPF10NJT", "VDS-DBRPF10NJ", "VDS-DBRPG10NJT", "VDS-DBRPG10NJ", "VDS-DBRMG10NJ",
    "VDS-DBRPE20JT", "VDS-DBRPF20JT", "VDS-DBRPF20J", "VDS-DBRPG20JT", "VDS-DBRPG20J", "VDS-DBRMG20J",
    "VDS-DBRPE20NJT", "VDS-DBRPE20NJ", "VDS-DBRPF20NJT", "VDS-DBRPF20NJ", "VDS-DBRPG20NJT", "VDS-DBRPG20NJ", "VDS-DBRMG20NJ",
    "VDS-DBRPE25JT", "VDS-DBRPE25J", "VDS-DBRPF25JT", "VDS-DBRPF25J", "VDS-DBRPG25JT", "VDS-DBRPG25J", "VDS-DBRMG25J",
    "VDS-DBRPE25NJT", "VDS-DBRPE25NJ", "VDS-DBRPF25NJT", "VDS-DBRPG25NJT", "VDS-DBRPG25NJ",
    "VDS-DBFPT80AJT", "VDS-DBFPT80CJT", "VDS-DBFPT90AJT", "VDS-DBFPT90BJT", "VDS-DBFPT90CJT",
]

NE_CODES = [
    "VDS-NEIPT80AF", "VDS-NEIPT80BF", "VDS-NEIPT80CF", "VDS-NEIPT90AF", "VDS-NEIPT90BF", "VDS-NEIPT90CF",
]


def _ok_bf(data: dict) -> list[str]:
    errs: list[str] = []
    if data.get("spring_material"):
        errs.append("spring_material should be absent")
    if data.get("stem_material"):
        errs.append("stem_material should be absent (use shaft_material)")
    if not (data.get("shaft_material") or "").strip():
        errs.append("shaft_material missing")
    return errs


def _ok_gl(data: dict) -> list[str]:
    errs: list[str] = []
    if not (data.get("back_seat_material") or "").strip():
        errs.append("back_seat_material missing")
    if not (data.get("seal_material") or "").strip():
        errs.append("seal_material missing")
    if not (data.get("spring_material") or "").strip():
        errs.append("spring_material missing")
    bsm = (data.get("back_seat_material") or "").upper()
    stem = (data.get("stem_material") or "").upper()
    if "316L" in stem and "316L" not in bsm and "F316L" not in bsm:
        errs.append("back_seat_material missing L-grade alignment with stem")
    return errs


def _ok_db(data: dict) -> list[str]:
    errs: list[str] = []
    for k in ("spring_material", "seal_material", "back_seat_material"):
        if data.get(k):
            errs.append(f"{k} should be absent")
    return errs


def _ok_ne(data: dict) -> list[str]:
    errs: list[str] = []
    if data.get("spring_material"):
        errs.append("spring_material should be absent")
    return errs


def main() -> int:
    failures: list[tuple[str, str, list[str]]] = []

    for raw in BF_CODES:
        d = decode_vds(raw)
        data = generate_datasheet(d, return_provenance=False)
        e = _ok_bf(data)
        if e:
            failures.append((raw, d.valve_type.value, e))

    for raw in GL_CODES:
        d = decode_vds(raw)
        data = generate_datasheet(d, return_provenance=False)
        e = _ok_gl(data)
        if e:
            failures.append((raw, d.valve_type.value, e))

    for raw in DB_CODES:
        d = decode_vds(raw)
        data = generate_datasheet(d, return_provenance=False)
        e = _ok_db(data)
        if e:
            failures.append((raw, d.valve_type.value, e))

    for raw in NE_CODES:
        d = decode_vds(raw)
        data = generate_datasheet(d, return_provenance=False)
        e = _ok_ne(data)
        if e:
            failures.append((raw, d.valve_type.value, e))

    print(f"Checked {len(BF_CODES)} BF + {len(GL_CODES)} GL + {len(DB_CODES)} DB + {len(NE_CODES)} NE samples")
    if failures:
        print(f"FAIL: {len(failures)}")
        for raw, vt, errs in failures:
            print(f"  {raw} [{vt}]: " + "; ".join(errs))
        return 1
    print("OK: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
