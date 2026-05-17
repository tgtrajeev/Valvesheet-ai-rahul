"""Auto-build VDS index entries for newly synced PMS classes.

Derives valve_assignments from PMS header data following the same engineering
rules used in the client's Excel PMS sheets (Pipe Class Sheets-With Tubing).

RULES (validated against all 88 spec codes in pms_extracted.json):

  SEAT SELECTION (ball valves):
    150# / 300#        → T  (PTFE)
    600# / 900# / 1500# → P  (PEEK)
    2500#              → P  (PEEK)  AND  M  (Metal) — both generated

  END CONNECTION:
    150# / 300# / 600# → R  (RF, Raised Face)
    900# / 1500# / 2500# → J  (RTJ, Ring Type Joint)

  CHECK VALVE SIZE SPLIT (universal across all classes):
    Piston type  → 0.5" – 1.5" NPS
    Swing type   → 2.0" – NPS_max
    Dual Plate   → 2.0" – NPS_max

  DBB (Double Block & Bleed):
    ONLY for 900# / 1500# / 2500# (E / F / G series)
    Process DBB  → end_conn = J   (standard RTJ)
    Instrument   → end_conn = JT  (RTJ + NPT bleed)
    2500# also gets Metal-seated DBB (DBRM)

  BUTTERFLY VALVE:
    NOT for plain CS / CS_NACE / LTCS_NACE classes
    YES for: GALV, GALV_SS_BODY, SS316L, SS316L_NACE, DSS, SDSS, SDSS_NACE,
             CUNI, COPPER, GRE, GRE_BONSTRAND, CPVC
    Only up to 600# (butterfly not used at RTJ pressure classes)
    Wafer design (W), PTFE seat (T), starts at 3.0" NPS

After running:
  1. valve_assignments are written back to pms_extracted.json for the spec
  2. VDS index entries are generated via the Rule Engine for each VDS code
  3. Entries are appended to all_valve_vds_index.json
  4. KnowledgeBase singleton is updated in-memory (no restart needed)
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Seat selection ────────────────────────────────────────────────────────────
# Returns list because 2500# generates BOTH PEEK and Metal ball valves.
_SEATS_BY_PRESSURE: dict[int, list[str]] = {
    150:  ["T"],       # PTFE only
    300:  ["T"],       # PTFE only
    600:  ["P"],       # PEEK only
    900:  ["P"],       # PEEK only
    1500: ["P"],       # PEEK only
    2500: ["P", "M"],  # PEEK + Metal (both in G-series per Excel PMS)
}

# Material categories that get a butterfly valve assignment
_BUTTERFLY_ELIGIBLE_CATEGORIES = {
    "GALV", "GALV_SS_BODY",
    "SS316L", "SS316L_NACE",
    "DSS",
    "SDSS", "SDSS_NACE",
    "CUNI", "COPPER",
    "GRE", "GRE_BONSTRAND",
    "CPVC",
}

# Valve standards (matching parse_pms_excel.py VALVE_STANDARD dict)
_VALVE_STANDARDS = {
    "BALL":              "API SPEC 6D / ISO 14313",
    "GATE":              "API STD 600 / API STD 602",
    "GLOBE":             "BS 1873",
    "CHECK_PISTON":      "API STD 594 / BS 1868",
    "CHECK_SWING":       "API STD 594 / BS 1868",
    "CHECK_DUAL_PLATE":  "API STD 594 / BS 1868",
    "BUTTERFLY":         "API STD 609",
    "DBB_PROCESS":       "API SPEC 6D",
    "DBB_INST":          "API SPEC 6D",
}


def _parse_pressure_num(pressure_rating: str | None) -> int:
    """Extract numeric pressure class from '300#', '300 lb', '300', etc."""
    m = re.search(r"\d+", str(pressure_rating or "150"))
    return int(m.group()) if m else 150


def _flange_face_to_end_conn(flange_face: str | None) -> str:
    """Convert PMS flange face string to VDS end-connection character."""
    ff = (flange_face or "RF").upper()
    if "RTJ" in ff or "RJ" in ff:
        return "J"
    if "FLAT" in ff or " FF" in ff or ff == "FF":
        return "F"
    return "R"  # default RF


def _end_conn_for_pressure(pressure_num: int, flange_face: str | None) -> str:
    """RTJ (J) for 900+, otherwise derive from flange face (usually RF)."""
    if pressure_num >= 900:
        return "J"
    return _flange_face_to_end_conn(flange_face)


def _material_category(
    material_description: str | None,
    nace_flag: bool,
    lt_flag: bool,
) -> str:
    """Derive rule-engine material category from PMS header fields.

    For custom PMS classes (e.g. PROJ1), standard letter-based derivation
    (A1→CS, A10→SS316L) is unavailable so we parse the material_description.
    """
    md = (material_description or "").lower()

    # Super Duplex
    if any(k in md for k in ("super duplex", "sdss", "s32750", "s32760", "f53", "f55")):
        return "SDSS_NACE" if nace_flag else "SDSS"

    # Duplex (not super)
    if any(k in md for k in ("duplex", "dss", "s31803", "s32205", "f51", "f60")):
        return "DSS"  # duplex is inherently NACE-compatible

    # Stainless steel 316 / 316L
    if any(k in md for k in ("316l", "316/316l", "cf3m", "f316l", "f316")):
        return "SS316L_NACE" if nace_flag else "SS316L"
    if "316" in md or "stainless" in md:
        return "SS316L_NACE" if nace_flag else "SS316L"

    # Titanium — no dedicated reference-table category yet, fall back to
    # SS316L (closest corrosion-resistant alloy in tables). Marked so future
    # extension can add a TITANIUM category without touching this branch.
    if "titanium" in md or "ti gr" in md or "asme b 367" in md or "asme b367" in md:
        return "SS316L"

    # Galvanized with SS valve body
    if ("galvaniz" in md or "galv" in md) and ("stainless" in md or "316" in md or "ss" in md):
        return "GALV_SS_BODY"
    # Galvanized plain
    if "galvaniz" in md or "galv" in md:
        return "GALV"

    # Copper-Nickel
    if any(k in md for k in ("cu-ni", "cuni", "copper-nickel", "cupronickel", "c70600")):
        return "CUNI"

    # Bronze / Copper
    if any(k in md for k in ("bronze", "copper", "c92200", "b61")):
        return "COPPER"

    # GRE (Glass Reinforced Epoxy)
    if any(k in md for k in ("gre", "glass reinforced", "fiberglass", "bonstrand")):
        return "GRE_BONSTRAND" if "bonstrand" in md else "GRE"

    # CPVC
    if "cpvc" in md or "chlorinated pvc" in md:
        return "CPVC"

    # LTCS — Low-Temperature Carbon Steel. Reference tables only have
    # LTCS_NACE; treat plain LTCS as LTCS_NACE so cold-service grades
    # (A350 LF2 etc.) are emitted instead of degrading to CS room-temp
    # grades. This is safe: LTCS_NACE specs are a superset of LTCS.
    if "ltcs" in md or "lt cs" in md or "low temp" in md or "a350" in md or "lf2" in md:
        return "LTCS_NACE"

    # Carbon Steel (default)
    if lt_flag and nace_flag:
        return "LTCS_NACE"
    if lt_flag:
        return "LTCS_NACE"  # safer than plain CS for cold service
    if nace_flag:
        return "CS_NACE"
    return "CS"


def _derive_valve_assignments(
    spec_code: str,
    pressure_num: int,
    end_conn: str,
    nps_max: float,
    mat_cat: str,
) -> list[dict]:
    """Build valve_assignments list following Excel PMS sheet rules exactly.

    Each dict mirrors the structure stored in pms_extracted.json:
      valve_type, valve_standard, nps_min, nps_max, vds_codes[], notes
    """
    sp  = spec_code.upper()
    ec  = end_conn
    seats = _SEATS_BY_PRESSURE.get(pressure_num, ["T"])
    primary_seat = seats[0]   # T or P (used for non-ball valves: gate/globe/check don't vary)
    has_dbb      = pressure_num >= 900
    has_butterfly = (mat_cat in _BUTTERFLY_ELIGIBLE_CATEGORIES) and (pressure_num <= 600)
    nps_max_f    = float(nps_max)

    assignments: list[dict] = []

    # ── 1. Ball valve — Full Bore + Reduced Bore, all seats for this pressure ──
    ball_codes = []
    for seat in seats:
        ball_codes.append(f"BLF{seat}{sp}{ec}")   # Full bore
        ball_codes.append(f"BLR{seat}{sp}{ec}")   # Reduced bore
    assignments.append({
        "valve_type":     "BALL",
        "valve_standard": _VALVE_STANDARDS["BALL"],
        "nps_min":        0.5,
        "nps_max":        nps_max_f,
        "vds_codes":      ball_codes,
        "notes":          None,
    })

    # ── 2. Gate valve — OS&Y, Metal seat ─────────────────────────────────────
    assignments.append({
        "valve_type":     "GATE",
        "valve_standard": _VALVE_STANDARDS["GATE"],
        "nps_min":        0.5,
        "nps_max":        nps_max_f,
        "vds_codes":      [f"GAYM{sp}{ec}"],
        "notes":          None,
    })

    # ── 3. Globe valve — OS&Y, Metal seat ────────────────────────────────────
    assignments.append({
        "valve_type":     "GLOBE",
        "valve_standard": _VALVE_STANDARDS["GLOBE"],
        "nps_min":        0.5,
        "nps_max":        nps_max_f,
        "vds_codes":      [f"GLYM{sp}{ec}"],
        "notes":          None,
    })

    # ── 4. Check valve — Piston (small bore ≤ 1.5") ──────────────────────────
    assignments.append({
        "valve_type":     "CHECK_PISTON",
        "valve_standard": _VALVE_STANDARDS["CHECK_PISTON"],
        "nps_min":        0.5,
        "nps_max":        1.5,
        "vds_codes":      [f"CHPM{sp}{ec}"],
        "notes":          None,
    })

    # ── 5. Check valve — Swing + Dual Plate (large bore ≥ 2") ────────────────
    assignments.append({
        "valve_type":     "CHECK_SWING",
        "valve_standard": _VALVE_STANDARDS["CHECK_SWING"],
        "nps_min":        2.0,
        "nps_max":        nps_max_f,
        "vds_codes":      [f"CHSM{sp}{ec}", f"CHDM{sp}{ec}"],
        "notes":          None,
    })

    # ── 6. DBB — only for 900# / 1500# / 2500# ───────────────────────────────
    if has_dbb:
        dbb_codes_process = []
        dbb_codes_inst    = []
        for seat in seats:
            dbb_codes_process.append(f"DBR{seat}{sp}{ec}")
            dbb_codes_inst.append(f"DBR{seat}{sp}{ec}T")   # +T = NPT bleed port = JT

        assignments.append({
            "valve_type":     "DBB_PROCESS",
            "valve_standard": _VALVE_STANDARDS["DBB_PROCESS"],
            "nps_min":        0.5,
            "nps_max":        nps_max_f,
            "vds_codes":      dbb_codes_process,
            "notes":          None,
        })
        assignments.append({
            "valve_type":     "DBB_INST",
            "valve_standard": _VALVE_STANDARDS["DBB_INST"],
            "nps_min":        0.5,
            "nps_max":        2.0,
            "vds_codes":      dbb_codes_inst,
            "notes":          "Instrumentation isolation — NPT bleed connection",
        })

    # ── 7. Butterfly — only for eligible material categories up to 600# ───────
    if has_butterfly:
        bf_nps_min = min(3.0, nps_max_f)
        assignments.append({
            "valve_type":     "BUTTERFLY",
            "valve_standard": _VALVE_STANDARDS["BUTTERFLY"],
            "nps_min":        bf_nps_min,
            "nps_max":        nps_max_f,
            "vds_codes":      [f"BFWT{sp}{ec}"],
            "notes":          None,
        })

    return assignments


def _synced_valve_assignments_nonempty(valve_assignments: object) -> bool:
    """True when POST /api/pms (or Excel extract) supplied real VDS rows to use."""
    if not isinstance(valve_assignments, list) or len(valve_assignments) == 0:
        return False
    for row in valve_assignments:
        if not isinstance(row, dict):
            continue
        codes = row.get("vds_codes")
        if isinstance(codes, list) and len(codes) > 0:
            return True
        one = row.get("vds_code")
        if isinstance(one, str) and one.strip():
            return True
    return False


def build_and_register(spec_code: str) -> int:
    """Generate VDS index entries for a newly synced piping class.

    Steps:
      1. Skip if entries already exist in KnowledgeBase.
      2. Load spec from PmsLoader (must have been synced via POST /api/pms).
      3. Derive material category and valve_assignments from PMS header data,
         following the same rules as the client's Excel PMS sheets.
      4. Write valve_assignments back to pms_extracted.json so the spec
         structure matches existing classes.
      5. Call Rule Engine on each VDS code to populate all datasheet fields.
      6. Append new entries to all_valve_vds_index.json.
      7. Inject into live KnowledgeBase singleton (no server restart needed).

    Returns number of new VDS index entries added (0 if already indexed).
    """
    from ..config import settings
    from .knowledge import get_knowledge_base
    from .pms_loader import get_pms_loader, refresh_pms_loader
    from .vds_decoder import decode_vds
    from .rule_engine import generate_datasheet

    spec_code = spec_code.upper().strip()
    kb = get_knowledge_base()

    if kb.has_piping_class(spec_code):
        logger.debug("pms_index_builder: %s already indexed, skipping", spec_code)
        return 0

    loader = get_pms_loader()
    # Always refresh from GET /api/pms before indexing.  `_preload_from_backend`
    # may have cached a lightweight class row with empty valve_assignments; the
    # full document (including valve rows from the in-app PMS Generator sync)
    # only appears after this fetch.
    pms_spec = loader.refresh_spec_from_backend(spec_code) or loader.get_spec(spec_code)
    if not pms_spec:
        logger.warning("pms_index_builder: %s not in PmsLoader — cannot build index", spec_code)
        return 0

    # ── Valve rows: prefer synced payload from PMS Generator / Excel ingest ───
    if _synced_valve_assignments_nonempty(pms_spec.valve_assignments):
        assignments = list(pms_spec.valve_assignments)
        logger.info(
            "pms_index_builder: using %d synced valve_assignments for %s (from PMS API)",
            len(assignments),
            spec_code,
        )
    else:
        # ── Derive parameters from PMS header (legacy / empty sync) ───────────
        pressure_num = _parse_pressure_num(pms_spec.header.pressure_rating)
        nace_flag    = bool(pms_spec.header.nace_flag)
        lt_flag      = bool(pms_spec.header.lt_flag)
        mat_cat      = _material_category(pms_spec.header.material_description, nace_flag, lt_flag)

        flange_face  = None
        nps_max      = 24.0
        if pms_spec.flanges:
            fl = pms_spec.flanges[0]
            flange_face = fl.flange_face
            if fl.nps_max is not None:
                nps_max = float(fl.nps_max)

        end_conn = _end_conn_for_pressure(pressure_num, flange_face)

        logger.info(
            "pms_index_builder: %s  pressure=%d#  mat_cat=%s  end_conn=%s  "
            "seats=%s  nps_max=%.1f  dbb=%s  butterfly=%s — deriving valve_assignments (sync empty)",
            spec_code, pressure_num, mat_cat, end_conn,
            _SEATS_BY_PRESSURE.get(pressure_num, ["T"]),
            nps_max,
            pressure_num >= 900,
            mat_cat in _BUTTERFLY_ELIGIBLE_CATEGORIES and pressure_num <= 600,
        )

        assignments = _derive_valve_assignments(spec_code, pressure_num, end_conn, nps_max, mat_cat)

    # ── Write valve_assignments back into pms_extracted.json ──────────────────
    json_path: Path = settings.data_dir / "pms_extracted.json"
    try:
        pms_data: dict = {}
        if json_path.exists():
            pms_data = json.loads(json_path.read_text(encoding="utf-8"))

        # If the spec wasn't in the local file (e.g. custom class synced to backend
        # but not yet written here), fetch the full spec from the backend API and
        # persist it so the Rule Engine can read PT ratings, bolting, gaskets, etc.
        if spec_code not in pms_data:
            try:
                import httpx
                resp = httpx.get(
                    f"{settings.backend_api_base_url}/pms",
                    params={"spec_code": spec_code},
                    timeout=5.0,
                )
                if resp.status_code == 200:
                    sheet = resp.json().get("data") or {}
                    if sheet:
                        pms_data[spec_code] = sheet
                        logger.info(
                            "pms_index_builder: fetched full spec for %s from backend API",
                            spec_code,
                        )
            except Exception as fetch_exc:
                logger.warning(
                    "pms_index_builder: could not fetch %s from backend: %s",
                    spec_code, fetch_exc,
                )

        if spec_code in pms_data:
            pms_data[spec_code]["valve_assignments"] = assignments
            json_path.write_text(
                json.dumps(pms_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            refresh_pms_loader()
            logger.info(
                "pms_index_builder: wrote %d valve_assignments for %s into pms_extracted.json",
                len(assignments), spec_code,
            )
        else:
            logger.warning(
                "pms_index_builder: %s not in local pms_extracted.json and backend fetch failed; "
                "rule engine will use fallback values",
                spec_code,
            )
    except Exception as exc:
        logger.warning(
            "pms_index_builder: could not update pms_extracted.json for %s: %s",
            spec_code, exc,
        )

    # ── Generate datasheet data for every VDS code ────────────────────────────
    all_vds_codes: list[str] = []
    for a in assignments:
        if not isinstance(a, dict):
            continue
        raw_list = a.get("vds_codes")
        if isinstance(raw_list, list):
            for c in raw_list:
                if isinstance(c, str) and c.strip():
                    all_vds_codes.append(c.strip().upper())
        one = a.get("vds_code")
        if isinstance(one, str) and one.strip():
            all_vds_codes.append(one.strip().upper())

    all_vds_codes = list(dict.fromkeys(all_vds_codes))

    new_entries: dict[str, dict] = {}
    for vds_code in all_vds_codes:
        try:
            decoded = decode_vds(vds_code)
            data = generate_datasheet(decoded)
            if data:
                new_entries[vds_code] = data
        except Exception as exc:
            logger.debug("pms_index_builder: skipping %s — %s", vds_code, exc)

    if not new_entries:
        logger.warning("pms_index_builder: rule engine produced no entries for %s", spec_code)
        return 0

    # ── Append to all_valve_vds_index.json ────────────────────────────────────
    index_path: Path = settings.data_dir / "all_valve_vds_index.json"
    try:
        existing: dict = {}
        if index_path.exists():
            existing = json.loads(index_path.read_text(encoding="utf-8"))
        merged = {**existing, **{k: v for k, v in new_entries.items() if k not in existing}}
        index_path.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(
            "pms_index_builder: wrote %d new VDS entries for %s to all_valve_vds_index.json",
            len(new_entries), spec_code,
        )
    except Exception as exc:
        logger.error("pms_index_builder: index write failed for %s: %s", spec_code, exc)
        # Still inject in-memory so this single request works even if disk write failed
        kb.add_entries(new_entries)
        return len(new_entries)

    # ── Inject into live KnowledgeBase ─────────────────────────────────────────
    added = kb.add_entries(new_entries)
    logger.info(
        "pms_index_builder: injected %d entries into KnowledgeBase for %s",
        added, spec_code,
    )

    # ── Register spec code in the validator cache ──────────────────────────────
    # The validator's _dynamic_spec_codes is loaded once at startup. New classes
    # added to the backend after server start won't be recognised by validate_combination()
    # until we explicitly register them here.
    try:
        from ..engine.validator import refresh_valid_spec_codes
        refresh_valid_spec_codes()
    except Exception:
        pass

    return added
