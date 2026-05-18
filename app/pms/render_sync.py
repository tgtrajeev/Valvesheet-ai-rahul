"""Render-deployed PMS Generator → Valvesheet AI sync.

Reads PMS class JSONs from the PMS Generator DB on Render (`pms_cache.response_json`),
translates each entry into the chatbot's `pms_extracted.json` shape, and writes the
result to:

  - `valve_agent.public.pms_sheets` (persistent store on Render), and
  - `app/data/pms_extracted.json` (the in-process PmsLoader cache).

After sync, the existing PmsLoader + rule engine + reference tables produce
correct valvesheets for the newly added piping classes — no rule changes.

Env vars (loaded from .env via dotenv):
  PMS_GENERATOR_DATABASE_URL — PMS Generator Render Postgres (read ``pms_cache``).
  VALVE_AGENT_DATABASE_URL — optional; if unset, ``DATABASE_URL`` or
    ``Settings.database_url`` is used so ``pms_sheets`` upserts hit the same DB
    as the running agent (typical single-Postgres deployments).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ── DB URLs ────────────────────────────────────────────────────────────────

def _psycopg2_conn_uri(raw: str) -> str:
    """Normalize SQLAlchemy/async DSNs to a libpq form psycopg2 accepts."""
    url = (raw or "").strip()
    if not url:
        return ""
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def _generator_url() -> str:
    load_dotenv()
    candidates: list[str] = []
    env_g = os.environ.get("PMS_GENERATOR_DATABASE_URL")
    if env_g:
        candidates.append(env_g)
    try:
        from ..config import settings

        if getattr(settings, "pms_generator_database_url", ""):
            candidates.append(settings.pms_generator_database_url)
    except Exception:
        pass
    for raw in candidates:
        u = _psycopg2_conn_uri(raw)
        if u:
            return u
    raise RuntimeError("PMS_GENERATOR_DATABASE_URL is not set in .env")


def _valve_agent_url() -> str:
    """DSN for ``pms_sheets`` upserts (psycopg2). Uses agent DB by default."""
    load_dotenv()
    candidates: list[str] = []
    for key in ("VALVE_AGENT_DATABASE_URL", "DATABASE_URL"):
        v = os.environ.get(key)
        if v:
            candidates.append(v)
    try:
        from ..config import settings

        if getattr(settings, "valve_agent_database_url", ""):
            candidates.append(settings.valve_agent_database_url)
        if getattr(settings, "database_url", ""):
            candidates.append(settings.database_url)
    except Exception:
        pass
    for raw in candidates:
        u = _psycopg2_conn_uri(raw)
        if u:
            return u
    raise RuntimeError(
        "No PostgreSQL URL for pms_sheets sync. Set VALVE_AGENT_DATABASE_URL or "
        "DATABASE_URL in .env (both may point at the same database as the agent)."
    )


# ── Translator: pms_cache.response_json → pms_extracted.json shape ────────

_VDS_CODE_GROUPS: tuple[tuple[str, str], ...] = (
    ("ball",      "ball_by_size"),
    ("gate",      "gate_by_size"),
    ("globe",     "globe_by_size"),
    ("check",     "check_by_size"),
    ("butterfly", "butterfly_by_size"),
    ("needle",    "needle_by_size"),
    ("dbb",       "dbb_by_size"),
    ("dbb_inst",  "dbb_inst_by_size"),
)


def _nace_flag(piping_class: str) -> bool:
    # Standard suffix: "N" indicates NACE service (e.g. A1N, B25N, A1LN).
    return "N" in piping_class.upper()[2:] if len(piping_class) > 2 else False


def _lt_flag(piping_class: str) -> bool:
    # "L" indicates low-temperature service (LTCS classes — e.g. A1LN, A2LN).
    return "L" in piping_class.upper()[2:] if len(piping_class) > 2 else False


def _parse_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str):
            cleaned = value.split()[0].replace(",", "")
            return float(cleaned)
        return float(value)
    except (ValueError, TypeError):
        return None


def _size_inch_to_float(size_inch: str) -> Optional[float]:
    if not size_inch:
        return None
    try:
        return float(size_inch)
    except ValueError:
        # Handle "1-1/2" etc.
        if "-" in size_inch:
            whole, frac = size_inch.split("-", 1)
            try:
                num, den = frac.split("/")
                return float(whole) + float(num) / float(den)
            except (ValueError, ZeroDivisionError):
                return None
        return None


def _split_vds_codes(code_cell: str) -> list[str]:
    """The PMS Generator packs multiple codes into one cell as 'BLRTA1R, BLFTA1R'."""
    if not code_cell:
        return []
    return [c.strip().upper() for c in code_cell.split(",") if c.strip()]


def _build_valve_assignments(valves: dict, spec_code: str) -> list[dict]:
    """Group ``<valve>_by_size`` rows into one assignment per (valve_type, code-set)."""
    if not isinstance(valves, dict):
        return []
    assignments: list[dict] = []
    for valve_type, by_size_key in _VDS_CODE_GROUPS:
        rows = valves.get(by_size_key) or []
        if not isinstance(rows, list) or not rows:
            continue

        # Group consecutive sizes with the same code-set into one assignment.
        current_codes: tuple[str, ...] | None = None
        nps_min: float | None = None
        nps_max: float | None = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            codes = tuple(_split_vds_codes(row.get("code") or ""))
            nps = _size_inch_to_float(str(row.get("size_inch") or ""))
            if not codes or nps is None:
                # Close any open group when a sizeless row interrupts the run.
                if current_codes is not None:
                    assignments.append({
                        "spec_code": spec_code,
                        "valve_type": valve_type,
                        "vds_codes": list(current_codes),
                        "nps_min": nps_min,
                        "nps_max": nps_max,
                    })
                    current_codes = None
                continue
            if current_codes is None:
                current_codes = codes
                nps_min = nps_max = nps
            elif codes == current_codes:
                nps_max = nps
            else:
                assignments.append({
                    "spec_code": spec_code,
                    "valve_type": valve_type,
                    "vds_codes": list(current_codes),
                    "nps_min": nps_min,
                    "nps_max": nps_max,
                })
                current_codes = codes
                nps_min = nps_max = nps

        if current_codes is not None:
            assignments.append({
                "spec_code": spec_code,
                "valve_type": valve_type,
                "vds_codes": list(current_codes),
                "nps_min": nps_min,
                "nps_max": nps_max,
            })
    return assignments


def _build_pipe_schedule(pipe_data: list[dict], spec_code: str, material: str) -> list[dict]:
    """Translate pipe_data rows into chatbot pipe_schedule entries."""
    if not isinstance(pipe_data, list):
        return []
    # Pipe standard heuristic: SS uses B 36.19M, everything else B 36.10M.
    pipe_std = "ASME B 36.19M" if "stainless" in (material or "").lower() or "316" in (material or "") else "ASME B 36.10M"
    out: list[dict] = []
    for r in pipe_data:
        if not isinstance(r, dict):
            continue
        nps = _size_inch_to_float(str(r.get("size_inch") or ""))
        if nps is None:
            continue
        schedule_val = (r.get("schedule") or "").replace("SCH ", "").replace("Sch ", "").strip() or None
        out.append({
            "spec_code":         spec_code,
            "nps_inch":          nps,
            "od_mm":             _parse_float(r.get("od_mm")),
            "schedule_val":      schedule_val,
            "wall_thickness_mm": _parse_float(r.get("wall_thickness_mm")),
            "pipe_type":         r.get("pipe_type") or "",
            "pipe_moc":          r.get("material_spec") or "",
            "pipe_std":          pipe_std,
            "ends":              r.get("ends") or "BE",
        })
    return out


def _build_flanges(flange: dict, pipe_data: list[dict], spec_code: str) -> list[dict]:
    if not isinstance(flange, dict) or not flange:
        return []
    nps_vals = sorted(
        {n for r in (pipe_data or []) if (n := _size_inch_to_float(str(r.get("size_inch") or ""))) is not None}
    )
    nps_min = nps_vals[0] if nps_vals else None
    nps_max = nps_vals[-1] if nps_vals else None
    size_range = f'{nps_min}"-{nps_max}"' if (nps_min is not None and nps_max is not None) else ""
    return [{
        "spec_code":   spec_code,
        "size_range":  size_range,
        "nps_min":     nps_min,
        "nps_max":     nps_max,
        "flange_moc":  flange.get("material_spec") or "",
        "flange_face": flange.get("face_type") or "",
        "flange_type": flange.get("flange_type") or "",
        "flange_std":  flange.get("standard") or "",
    }]


def _build_pt_ratings(pressure_temperature: dict, spec_code: str) -> list[dict]:
    if not isinstance(pressure_temperature, dict):
        return []
    temps = pressure_temperature.get("temperatures") or []
    press = pressure_temperature.get("pressures") or []
    return [
        {"spec_code": spec_code, "temperature_c": float(t), "max_pressure_barg": float(p)}
        for t, p in zip(temps, press)
        if t is not None and p is not None
    ]


def _build_index_row(pressure_temperature: dict, hydrotest_pressure: str | float | None, spec_code: str) -> Optional[dict]:
    pt_ratings = _build_pt_ratings(pressure_temperature, spec_code)
    if not pt_ratings:
        return None
    pt_sorted = sorted(pt_ratings, key=lambda r: r["temperature_c"])
    first = pt_sorted[0]
    return {
        "spec_code":            spec_code,
        "hydrotest_barg":       _parse_float(hydrotest_pressure),
        "design_pressure_barg": first["max_pressure_barg"],
        "min_temp_c":           first["temperature_c"],
        "pt_breakpoints":       [
            {"temp_c": r["temperature_c"], "press_barg": r["max_pressure_barg"]}
            for r in pt_sorted[1:]
        ],
    }


def _build_materials_section(pc: str, material_description: str, bng: dict) -> Optional[dict]:
    """Build the 'materials' section from PMS header + bolting_gaskets at sync time.

    This ensures that when a PMS class is synced from the PMS Generator, the
    resolved material specs are stored directly in the pms_extracted.json /
    pms_sheets DB row. The rule engine then reads from spec.materials (which
    IS populated) and never falls back to generic reference-table rows.

    Body material is resolved using the same keyword mapping as the rule engine.
    Bolt / nut specs come verbatim from the PMS bolting_gaskets section —
    these are project-authoritative values.
    """
    bng = bng or {}
    stud_bolt = bng.get("stud_bolts") or bng.get("stud_bolt_spec") or None
    hex_nut   = bng.get("hex_nuts")   or bng.get("hex_nut_spec")   or None
    gasket    = bng.get("gasket")     or bng.get("gasket_spec")    or None

    # Resolve body material from material_description text
    body_mat = _resolve_body_material_text(material_description)

    if not any([body_mat, stud_bolt, hex_nut, gasket]):
        return None

    return {
        "spec_code":      pc,
        "body_material":  body_mat,
        # bolt/nut stored directly — the rule engine maps these to bolt_material / nut_material
        "stud_bolt_spec": stud_bolt,
        "hex_nut_spec":   hex_nut,
        "gasket_spec":    gasket,
    }


# Material-description → body-material text mapping (mirrors rule_engine logic)
_MATERIAL_BODY_MAP = {
    "titanium": "ASTM A105N RF with 3mm Titanium weld deposit (≤ 1.5\"), ASTM A105N with 3mm Titanium weld deposit / ASTM B265 Gr. 2 (2\" and above) per ASME B16.34 Group 4.2",
    "super duplex": "SDSS - UNS S32750, Forged - ASTM A182 F53 (1.5\" and below), Cast - ASTM A995 5A UNS J93404 (2\" and above)",
    "sdss": "SDSS - UNS S32750, Forged - ASTM A182 F53 (1.5\" and below), Cast - ASTM A995 5A UNS J93404 (2\" and above)",
    "duplex": "DSS - UNS S32205, Forged - ASTM A182 F60 (1.5\" and below), Cast - A995 4A UNS J92205 (2\" & Above)",
    "dss": "DSS - UNS S32205, Forged - ASTM A182 F60 (1.5\" and below), Cast - A995 4A UNS J92205 (2\" & Above)",
    "316": "ASTM A182 F316L (1.5\" and below), A351 CF3M (2\" and above)",
    "stainless": "ASTM A182 F316L (1.5\" and below), A351 CF3M (2\" and above)",
    "cu-ni": "ASTM B148 C95800",
    "copper nickel": "ASTM B148 C95800",
    "90/10": "ASTM B148 C95800",
    "carbon": "ASTM A105N (1.5\" and below), ASTM A105N/ASTM A216 WCB (2\" & Above)",
    "ltcs": "ASTM A350 LF2 (1.5\" & below), ASTM A352 LCC (2\" & Above)",
    "low temperature carbon": "ASTM A350 LF2 (1.5\" & below), ASTM A352 LCC (2\" & Above)",
}


def _resolve_body_material_text(description: str) -> Optional[str]:
    """Return the authoritative body material ASTM grade string for a given
    material_description from the PMS header.
    """
    if not description:
        return None
    text = description.lower()
    for keyword, body in _MATERIAL_BODY_MAP.items():
        if keyword in text:
            return body
    # Plain CS shorthand
    if text.strip() in {"cs", "c.s.", "carbon steel"}:
        return "ASTM A105N (1.5\" and below), ASTM A105N/ASTM A216 WCB (2\" & Above)"
    return None


def transform(piping_class: str, response_json: dict) -> dict:
    """Convert one ``pms_cache`` row to the chatbot's `pms_extracted.json` shape."""
    pc = (piping_class or "").upper().strip()
    rj = response_json or {}

    pt = rj.get("pressure_temperature") or {}
    pressures = pt.get("pressures") or []
    design_pressure_barg = float(pressures[0]) if pressures else None

    header = {
        "spec_code":               pc,
        "pressure_rating":         rj.get("rating") or "",
        "material_description":    rj.get("material") or "",
        "corrosion_allowance":     rj.get("corrosion_allowance") or "",
        "mill_tolerance":          rj.get("mill_tolerance") or "",
        "design_code":             rj.get("design_code") or "ASME B 31.3",
        "service":                 rj.get("service") or "",
        "branch_chart":            rj.get("branch_chart") or "",
        "nace_flag":               _nace_flag(pc),
        "lt_flag":                 _lt_flag(pc),
        "valve_rating_label":      (rj.get("valves") or {}).get("rating") or rj.get("rating") or "",
        "design_pressure_barg":    design_pressure_barg,
        "hydrotest_pressure_barg": _parse_float(rj.get("hydrotest_pressure")),
    }

    bng = rj.get("bolts_nuts_gaskets") or {}
    bolting_gaskets = {
        "spec_code":      pc,
        "stud_bolt_spec": bng.get("stud_bolts") or "",
        "hex_nut_spec":   bng.get("hex_nuts") or "",
        "gasket_spec":    bng.get("gasket") or "",
    } if bng else None

    # ── Bake in the resolved materials section at sync time ──────────────────
    # Store the actual material specs directly in the JSON so the rule engine
    # reads them as first-class data and never falls back to generic tables.
    # Body material is derived from material_description; bolt/nut from the
    # PMS bolting_gaskets section which IS authoritative (project-specific).
    materials = _build_materials_section(pc, header["material_description"], bng)

    pipe_schedule = _build_pipe_schedule(rj.get("pipe_data") or [], pc, header["material_description"])
    flanges       = _build_flanges(rj.get("flange") or {}, rj.get("pipe_data") or [], pc)
    pt_ratings    = _build_pt_ratings(pt, pc)
    index_row     = _build_index_row(pt, rj.get("hydrotest_pressure"), pc)
    valve_assigns = _build_valve_assignments(rj.get("valves") or {}, pc)

    nps_sizes = []
    for i, r in enumerate(rj.get("pipe_data") or [], start=2):
        nps = _size_inch_to_float(str(r.get("size_inch") or ""))
        if nps is not None:
            nps_sizes.append({"col": i, "nps_inch": nps})

    return {
        "spec_code":         pc,
        "header":            header,
        "pt_ratings":        pt_ratings,
        "pipe_schedule":     pipe_schedule,
        "flanges":           flanges,
        "bolting_gaskets":   bolting_gaskets,
        "materials":         materials,
        "valve_assignments": valve_assigns,
        "nps_sizes":         nps_sizes,
        "index_row":         index_row,
    }


# ── Fetch / store ────────────────────────────────────────────────────────────

def fetch_all_from_generator() -> list[tuple[str, dict]]:
    """Return [(piping_class, response_json), ...] for every row in pms_cache.

    De-duplicates by ``piping_class``, keeping the most recently updated row.
    """
    conn = psycopg2.connect(_generator_url(), connect_timeout=15)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (piping_class) piping_class, response_json
                FROM pms_cache
                ORDER BY piping_class, updated_at DESC NULLS LAST
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [(pc, rj) for pc, rj in rows if pc and rj]


def fetch_one_from_generator(piping_class: str) -> Optional[dict]:
    """Return the latest ``response_json`` for a single piping class, or None."""
    pc = (piping_class or "").upper().strip()
    conn = psycopg2.connect(_generator_url(), connect_timeout=15)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT response_json FROM pms_cache
                WHERE UPPER(piping_class) = %s
                ORDER BY updated_at DESC NULLS LAST
                LIMIT 1
                """,
                (pc,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def write_to_valve_agent_db(rows: list[tuple[str, dict]], *, project_id: str = "render-sync",
                            project_name: str = "Render PMS Generator sync") -> int:
    """Upsert transformed rows into ``valve_agent.public.pms_sheets``.

    Implemented as DELETE-then-INSERT because the table has no unique constraint
    on ``(project_id, spec_code)`` so we can't use ``ON CONFLICT`` directly.
    """
    if not rows:
        return 0
    conn = psycopg2.connect(_valve_agent_url(), connect_timeout=15)
    try:
        with conn.cursor() as cur:
            n = 0
            for spec_code, pms_data in rows:
                cur.execute(
                    "DELETE FROM pms_sheets WHERE project_id = %s AND spec_code = %s",
                    (project_id, spec_code),
                )
                cur.execute(
                    """
                    INSERT INTO pms_sheets (project_id, project_name, spec_code, source,
                                            source_file, pms_data, status, synced_at,
                                            created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, NOW(), NOW(), NOW())
                    """,
                    (project_id, project_name, spec_code, "render",
                     None, json.dumps(pms_data, ensure_ascii=False), "synced"),
                )
                n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def _default_pms_extracted_path() -> Path:
    """Absolute path to the agent's ``pms_extracted.json`` (not cwd-relative)."""
    try:
        from ..config import settings

        return settings.data_dir / "pms_extracted.json"
    except Exception:
        return Path(__file__).resolve().parents[1] / "data" / "pms_extracted.json"


def write_to_local_json(
    rows: list[tuple[str, dict]], path: str | None = None
) -> int:
    """Merge transformed rows into the chatbot's local ``pms_extracted.json``."""
    p = Path(path) if path else _default_pms_extracted_path()
    existing: dict = {}
    if p.exists():
        existing = json.loads(p.read_text(encoding="utf-8"))
    for spec_code, data in rows:
        existing[spec_code] = data
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return len(rows)


# ── Public entry points ────────────────────────────────────────────────────

def sync_all(write_local: bool = True, write_remote: bool = True) -> dict:
    """Pull every row from pms_generator.pms_cache, transform, store in both targets."""
    raw = fetch_all_from_generator()
    transformed: list[tuple[str, dict]] = [(pc, transform(pc, rj)) for pc, rj in raw]
    result = {"fetched": len(raw), "transformed": len(transformed)}
    if write_remote:
        result["written_remote"] = write_to_valve_agent_db(transformed)
    if write_local:
        result["written_local"] = write_to_local_json(transformed)
    return result


def sync_one(piping_class: str, write_local: bool = True, write_remote: bool = True) -> Optional[dict]:
    """Pull one spec from pms_generator, transform, store. Returns the transformed dict."""
    rj = fetch_one_from_generator(piping_class)
    if not rj:
        return None
    data = transform(piping_class, rj)
    if write_remote:
        write_to_valve_agent_db([(data["spec_code"], data)])
    if write_local:
        write_to_local_json([(data["spec_code"], data)])
    return data
