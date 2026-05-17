"""Project-scoped PMS upload, list, query, and sync."""
from __future__ import annotations

import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..config import settings
from ..pms import store
from ..pms.api_client import PMSApiClient, sync_from_local_file
from ..pms.query import query as pms_query
from ..pms.schema import (
    AttributeValue,
    PipeScheduleRow,
    PipingClass,
    ProjectMetadata,
    ProjectPMS,
    PTRating,
    ValveAssignment,
)
from ..pms.vds_builder import build_vds_index
from ..pms.xlsx_parser import parse_xlsx

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pms", tags=["pms"])

# Permissive class-code matcher. PMS Generator's §5.5 naming rules can emit
# any letter + digit(s) + optional letter suffix (e.g. A1, G2N, T2N, T80A,
# A1LN, projects' custom PROJ1). Anything PMS Generator can compute should
# be accepted here — class-code-specific gating belongs in business logic,
# not in input validation. Kept letters-only-after-the-first-letter to
# block path traversal / injection.
_SPEC_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{0,9}$", re.I)
_DEV_PROJECT_ID = "fpso-albacora"


def _attr(raw: Any) -> AttributeValue:
    numeric = None
    if isinstance(raw, bool):
        numeric = 1.0 if raw else 0.0
    elif isinstance(raw, (int, float)):
        numeric = float(raw)
    elif isinstance(raw, str):
        try:
            numeric = float(raw.replace("#", "").replace("%", "").strip())
        except ValueError:
            numeric = None
    tokens = re.findall(r"[A-Za-z0-9_.#/%+-]+", str(raw).lower()) if raw is not None else []
    return AttributeValue(raw=raw, numeric=numeric, tokens=tokens)


def _split_vds_codes(raw_codes: Any) -> list[str]:
    if raw_codes is None:
        return []
    if isinstance(raw_codes, str):
        raw_iter = [raw_codes]
    elif isinstance(raw_codes, list):
        raw_iter = raw_codes
    else:
        return []
    out: list[str] = []
    for raw in raw_iter:
        if not isinstance(raw, str):
            continue
        for part in raw.split(","):
            code = part.strip().upper()
            if code:
                out.append(code)
    return list(dict.fromkeys(out))


def _class_from_raw_payload(spec_code: str, raw: dict[str, Any]) -> PipingClass:
    pc = PipingClass(spec_code=spec_code)
    header = raw.get("header") or {}
    for key, value in header.items():
        if key == "spec_code" or value is None:
            continue
        pc.attributes[key] = _attr(value)

    for row in raw.get("pt_ratings") or []:
        if row.get("temperature_c") is not None and row.get("max_pressure_barg") is not None:
            pc.pt_ratings.append(PTRating(
                temperature_c=float(row["temperature_c"]),
                max_pressure_barg=float(row["max_pressure_barg"]),
            ))

    for row in raw.get("pipe_schedule") or []:
        pc.pipe_schedule.append(PipeScheduleRow(
            nps_inch=float(row.get("nps_inch")),
            od_mm=row.get("od_mm"),
            schedule_val=row.get("schedule_val"),
            wall_thickness_mm=row.get("wall_thickness_mm"),
            pipe_type=row.get("pipe_type"),
            pipe_moc=row.get("pipe_moc"),
            pipe_std=row.get("pipe_std"),
            ends=row.get("ends"),
        ))

    for row in raw.get("valve_assignments") or []:
        pc.valve_assignments.append(ValveAssignment(
            valve_type=row.get("valve_type", "UNKNOWN"),
            nps_min=row.get("nps_min"),
            nps_max=row.get("nps_max"),
            vds_codes=_split_vds_codes(row.get("vds_codes") or row.get("vds_code")),
            raw_cell_value=row.get("raw_cell_value"),
            notes=row.get("notes"),
            valve_standard=row.get("valve_standard"),
        ))

    pc.flanges = raw.get("flanges") or []
    pc.bolting_gaskets = raw.get("bolting_gaskets")
    pc.fittings = raw.get("fittings") or []
    pc.branch_chart = raw.get("branch_chart")
    pc.extra = raw.get("extra") or {}
    return pc


def _piping_class_to_legacy_json(pc: PipingClass) -> dict[str, Any]:
    attrs = pc.attributes
    return {
        "spec_code": pc.spec_code,
        "header": {
            "spec_code": pc.spec_code,
            "pressure_rating": attrs.get("pressure_rating").raw if attrs.get("pressure_rating") else None,
            "material_description": attrs.get("material_description").raw if attrs.get("material_description") else None,
            "corrosion_allowance": attrs.get("corrosion_allowance").raw if attrs.get("corrosion_allowance") else None,
            "service": attrs.get("service").raw if attrs.get("service") else None,
            "design_code": attrs.get("design_code").raw if attrs.get("design_code") else None,
            "mill_tolerance": attrs.get("mill_tolerance").raw if attrs.get("mill_tolerance") else None,
            "nace_flag": bool(attrs.get("nace_flag").raw) if attrs.get("nace_flag") else False,
            "lt_flag": bool(attrs.get("lt_flag").raw) if attrs.get("lt_flag") else False,
            "hydrotest_pressure_barg": attrs.get("hydrotest_pressure_barg").raw if attrs.get("hydrotest_pressure_barg") else None,
            "design_pressure_barg": attrs.get("design_pressure_barg").raw if attrs.get("design_pressure_barg") else None,
            "valve_rating_label": attrs.get("valve_rating_label").raw if attrs.get("valve_rating_label") else None,
        },
        "pt_ratings": [r.model_dump() for r in pc.pt_ratings],
        "pipe_schedule": [r.model_dump() for r in pc.pipe_schedule],
        "flanges": pc.flanges,
        "bolting_gaskets": pc.bolting_gaskets,
        "valve_assignments": [r.model_dump() for r in pc.valve_assignments],
        "fittings": pc.fittings,
        "branch_chart": pc.branch_chart,
        "extra": pc.extra,
    }


def _range_diagnostics(updates: dict[str, PipingClass]) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}
    for spec_code, pc in updates.items():
        pipe_sizes = [r.nps_inch for r in pc.pipe_schedule if r.nps_inch is not None]
        valve_ranges = [
            {
                "valve_type": va.valve_type,
                "nps_min": va.nps_min,
                "nps_max": va.nps_max,
                "vds_codes": _split_vds_codes(va.vds_codes),
            }
            for va in pc.valve_assignments
        ]
        diagnostics[spec_code] = {
            "pipe_schedule_min": min(pipe_sizes) if pipe_sizes else None,
            "pipe_schedule_max": max(pipe_sizes) if pipe_sizes else None,
            "valve_assignment_ranges": valve_ranges,
            "note": (
                "Datasheet size_range is resolved from the matching valve_assignment row first; "
                "editing pipe_schedule alone will not expand a VDS whose valve_assignment nps_max is unchanged."
            ),
        }
    return diagnostics


class FilterSpec(BaseModel):
    path: str
    op: str = "eq"
    value: Any = None


class QueryRequest(BaseModel):
    filters: List[FilterSpec] = []
    limit: Optional[int] = None


@router.get("/projects")
async def list_projects():
    return {"projects": [m.model_dump() for m in store.list_projects()]}


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    pms = store.load_pms(project_id)
    if not pms:
        raise HTTPException(404, "project not found")
    idx = store.load_vds_index(project_id)
    return {
        "metadata": pms.metadata.model_dump(),
        "class_codes": pms.class_codes(),
        "vds_codes": idx.valid_codes() if idx else [],
    }


@router.get("/projects/{project_id}/piping_class/{spec_code}")
async def get_class(project_id: str, spec_code: str):
    pms = store.load_pms(project_id)
    if not pms:
        raise HTTPException(404, "project not found")
    pc = pms.piping_classes.get(spec_code)
    if not pc:
        raise HTTPException(404, f"piping class {spec_code} not found")
    return pc.model_dump()


@router.post("/projects/{project_id}/upload")
async def upload_pms(
    project_id: str,
    file: UploadFile = File(...),
    project_name: Optional[str] = Form(None),
):
    name = file.filename or "pms.xlsx"
    if not name.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "only .xlsx/.xlsm supported in this build")

    content = await file.read()
    raw_path = store.save_raw_upload(project_id, name, content)

    try:
        pms = parse_xlsx(raw_path, project_id=project_id, project_name=project_name)
    except Exception as e:
        raise HTTPException(400, f"parse failed: {e}")

    if not pms.piping_classes:
        raise HTTPException(400, "no piping classes parsed from file")

    # Save to file (backwards compat)
    store.save_pms(pms)
    idx = build_vds_index(pms)
    store.save_vds_index(idx)

    # Also save to DB for unified access
    await store.save_pms_to_db(
        project_id=project_id,
        project_name=project_name or project_id,
        piping_classes=pms.piping_classes,
        source="xlsx_upload",
        source_file=name,
    )
    # Warm in-memory cache
    store.warm_pms_cache(project_id, pms)

    return {
        "ok": True,
        "metadata": pms.metadata.model_dump(),
        "class_codes": pms.class_codes(),
        "vds_codes": idx.valid_codes(),
    }


@router.post("/projects/{project_id}/query")
async def query_endpoint(project_id: str, body: QueryRequest):
    pms = store.load_pms(project_id)
    if not pms:
        raise HTTPException(404, "project not found")
    filters = [f.model_dump() for f in body.filters]
    results = pms_query(pms, filters, limit=body.limit)
    return {"results": [pc.model_dump() for pc in results], "count": len(results)}


@router.post("")
async def dev_sync_pms_json(
    body: Dict[str, Any],
    project_id: str = _DEV_PROJECT_ID,
):
    """Dev/Test: upsert PMS JSON keyed by piping-class code.

    This route backs the "Generate PMS" menu test panel. It intentionally
    accepts full PMS-shaped JSON so a future or edited class can be tested
    without changing backend rules.
    """
    if not body:
        raise HTTPException(400, "PMS payload must be an object keyed by piping class code")

    updates: dict[str, PipingClass] = {}
    errors: list[str] = []
    for raw_code, raw_class in body.items():
        spec_code = str(raw_code).upper().strip()
        if not _SPEC_CODE_RE.match(spec_code):
            errors.append(f"{raw_code}: invalid piping class code")
            continue
        if not isinstance(raw_class, dict):
            errors.append(f"{spec_code}: payload must be an object")
            continue
        header_code = str((raw_class.get("header") or {}).get("spec_code") or spec_code).upper().strip()
        if header_code != spec_code:
            errors.append(f"{spec_code}: header.spec_code '{header_code}' does not match key")
            continue
        try:
            updates[spec_code] = _class_from_raw_payload(spec_code, raw_class)
        except Exception as exc:
            errors.append(f"{spec_code}: {exc}")

    if errors:
        raise HTTPException(400, {"errors": errors})
    if not updates:
        raise HTTPException(400, "No valid PMS classes supplied")

    existing = store.load_pms(project_id)
    if existing:
        pms = existing
        pms.piping_classes.update(updates)
    else:
        pms = ProjectPMS(
            metadata=ProjectMetadata(
                project_id=project_id,
                name=project_id,
                source_file="dev_pms_json",
                uploaded_at=datetime.now(timezone.utc).isoformat(),
                status="draft",
            ),
            piping_classes=updates,
        )

    store.save_pms(pms)
    idx = build_vds_index(pms)
    store.save_vds_index(idx)
    store.warm_pms_cache(project_id, pms)

    db_failed: list[str] = []
    try:
        await store.save_pms_to_db(
            project_id=project_id,
            project_name=pms.metadata.name,
            piping_classes=updates,
            source="dev_json",
            source_file="POST /api/pms",
        )
    except Exception as exc:
        logger.warning("Dev PMS JSON DB write failed: %s", exc)
        db_failed = list(updates)

    try:
        from ..engine.pms_loader import refresh_pms_loader
        refresh_pms_loader()
    except Exception:
        pass

    affected_vds = sorted({
        code
        for pc in updates.values()
        for va in pc.valve_assignments
        for code in _split_vds_codes(va.vds_codes)
    })
    return {
        "ok": True,
        "project_id": project_id,
        "sheets_total": len(updates),
        "saved_codes": sorted(updates),
        "db_failed": db_failed,
        "vds_codes": affected_vds,
        "vds_count": len(affected_vds),
        "range_diagnostics": _range_diagnostics(updates),
    }


@router.get("")
async def get_dev_pms_json(spec_code: str, project_id: str = _DEV_PROJECT_ID):
    code = spec_code.upper().strip()
    pms = store.load_pms(project_id)
    if not pms or code not in pms.piping_classes:
        raise HTTPException(404, f"piping class {code} not found")
    return {"spec_code": code, "project_id": project_id, "data": _piping_class_to_legacy_json(pms.piping_classes[code])}


@router.get("/classes")
async def list_dev_pms_classes(project_id: str = _DEV_PROJECT_ID):
    pms = store.load_pms(project_id)
    if not pms:
        return {"classes": []}
    classes = []
    for spec_code, pc in sorted(pms.piping_classes.items()):
        attrs = pc.attributes
        classes.append({
            "spec_code": spec_code,
            "pressure_rating": attrs.get("pressure_rating").raw if attrs.get("pressure_rating") else None,
            "material": attrs.get("material_description").raw if attrs.get("material_description") else None,
            "corrosion_allowance": attrs.get("corrosion_allowance").raw if attrs.get("corrosion_allowance") else None,
            "service": attrs.get("service").raw if attrs.get("service") else None,
            "nace": bool(attrs.get("nace_flag").raw) if attrs.get("nace_flag") else False,
            "low_temp": bool(attrs.get("lt_flag").raw) if attrs.get("lt_flag") else False,
            "design_pressure_barg": attrs.get("design_pressure_barg").raw if attrs.get("design_pressure_barg") else None,
            "hydrotest_pressure_barg": attrs.get("hydrotest_pressure_barg").raw if attrs.get("hydrotest_pressure_barg") else None,
        })
    return {"classes": classes}


# ── Sync routes ──────────────────────────────────────────────────────────────

class SyncRequest(BaseModel):
    project_name: Optional[str] = None
    source_file: Optional[str] = None     # for local-file sync, path to xlsx


@router.post("/projects/{project_id}/sync")
async def sync_project(project_id: str, body: SyncRequest = SyncRequest()):
    """Sync PMS data for a project.

    If the external PMS API is configured (pms_sync_enabled=True), fetches
    from the API. Otherwise, falls back to re-parsing from the local raw
    upload file or a specified source_file path.
    """
    if settings.pms_sync_enabled and settings.pms_api_base_url:
        # ── API sync path ──
        client = PMSApiClient(
            base_url=settings.pms_api_base_url,
            api_key=settings.pms_api_key,
        )
        sync_result = await client.sync_project(
            project_id=project_id,
            project_name=body.project_name,
        )
        if sync_result.error:
            raise HTTPException(502, f"PMS API sync failed: {sync_result.error}")

        # Persist synced classes to DB
        if sync_result.pms and sync_result.pms.piping_classes:
            await store.save_pms_to_db(
                project_id=project_id,
                project_name=body.project_name or project_id,
                piping_classes=sync_result.pms.piping_classes,
                source="api_sync",
                source_file=settings.pms_api_base_url,
                status="approved",
            )
            # Also save to file for backwards compat
            store.save_pms(sync_result.pms)
            idx = build_vds_index(sync_result.pms)
            store.save_vds_index(idx)
            # Warm the in-memory cache so sync load_pms() sees it
            store.warm_pms_cache(project_id, sync_result.pms)

        return {
            "ok": True,
            "source": "api_sync",
            "project_id": project_id,
            "classes_synced": sync_result.classes_synced,
            "classes_failed": sync_result.classes_failed,
            "synced_at": sync_result.synced_at,
        }
    else:
        # ── Local file sync path ──
        # Try explicit source_file, then raw upload dir
        file_path = None
        if body.source_file:
            p = Path(body.source_file)
            if p.exists():
                file_path = p
        if not file_path:
            raw_dir = store.project_dir(project_id) / "raw"
            if raw_dir.exists():
                xlsx_files = list(raw_dir.glob("*.xlsx")) + list(raw_dir.glob("*.xlsm"))
                if xlsx_files:
                    file_path = xlsx_files[0]  # use most recent upload

        if not file_path:
            raise HTTPException(
                400,
                "No PMS source available. Either upload an XLSX file first, "
                "provide source_file path, or enable PMS API sync.",
            )

        pms, sync_result = await sync_from_local_file(
            file_path=file_path,
            project_id=project_id,
            project_name=body.project_name,
        )

        if sync_result.error:
            raise HTTPException(400, f"Sync failed: {sync_result.error}")

        # Save to both file and DB
        store.save_pms(pms)
        idx = build_vds_index(pms)
        store.save_vds_index(idx)

        await store.save_pms_to_db(
            project_id=project_id,
            project_name=body.project_name or project_id,
            piping_classes=pms.piping_classes,
            source="local_file",
            source_file=file_path.name,
        )
        # Warm in-memory cache
        store.warm_pms_cache(project_id, pms)

        return {
            "ok": True,
            "source": "local_file",
            "project_id": project_id,
            "class_codes": pms.class_codes(),
            "classes_synced": sync_result.classes_synced,
            "vds_codes": idx.valid_codes(),
            "synced_at": sync_result.synced_at,
        }


@router.get("/projects/{project_id}/sync")
async def sync_status(project_id: str):
    """Check sync status — returns DB-backed project info if available."""
    db_projects = await store.list_projects_from_db()
    for p in db_projects:
        if p["project_id"] == project_id:
            return {"synced": True, **p}
    # Check file-based fallback
    pms = store.load_pms_from_file(project_id)
    if pms:
        return {
            "synced": False,
            "project_id": project_id,
            "source": "file_only",
            "class_count": len(pms.piping_classes),
        }
    raise HTTPException(404, "project not found")


@router.get("/db/projects")
async def list_db_projects():
    """List all projects stored in the DB (pms_sheets table)."""
    projects = await store.list_projects_from_db()
    return {"projects": projects}


@router.post("/sync-from-generator/{spec_code}")
async def sync_from_generator(spec_code: str):
    """Engineer-approved push: pull a single PMS class from the PMS Generator
    Render DB into the Valvesheet AI agent.

    Flow:
      1. Engineer reviews and approves the class in PMS Generator UI (upstream).
      2. PMS Generator persists to `pms_cache.response_json`.
      3. Frontend hits this endpoint with the approved spec_code.
      4. Endpoint pulls + transforms + writes to Valvesheet DB and local
         pms_extracted.json (via render_sync.sync_one).
      5. In-process PmsLoader cache is invalidated so the next request sees
         the new data without a server restart.
      6. KnowledgeBase VDS index entries for this class are evicted; the next
         chat request for the class triggers a fresh build_and_register.

    Returns a sync summary the frontend can show to the engineer.
    """
    pc = (spec_code or "").upper().strip()
    if not _SPEC_CODE_RE.match(pc):
        raise HTTPException(400, f"Invalid spec_code '{spec_code}'")

    from ..pms.render_sync import sync_one
    from ..engine.pms_loader import refresh_pms_loader
    from ..engine.knowledge import get_knowledge_base

    try:
        data = sync_one(pc)
    except RuntimeError as exc:
        # Env var missing — PMS_GENERATOR_DATABASE_URL or VALVE_AGENT_DATABASE_URL.
        raise HTTPException(503, str(exc))
    except Exception as exc:  # pragma: no cover — surface DB / network failures
        logger.exception("sync-from-generator failed for %s", pc)
        raise HTTPException(502, f"Sync failed: {exc}")

    if data is None:
        raise HTTPException(404, f"No PMS row for spec_code '{pc}' in PMS Generator DB")

    # Demo / debugging aid — log the transformed PMS so reviewers can see
    # exactly what flowed from PMS Generator into Valvesheet AI.
    import json as _json
    logger.info(
        "\n========== Synced PMS from PMS Generator: %s ==========\n%s\n========== End %s ==========",
        pc,
        _json.dumps(data, indent=2, ensure_ascii=False, default=str),
        pc,
    )

    refresh_pms_loader()
    evicted = get_knowledge_base().evict_piping_class(pc)

    return {
        "ok": True,
        "spec_code": data["spec_code"],
        "valve_assignments": len(data.get("valve_assignments") or []),
        "pipe_schedule": len(data.get("pipe_schedule") or []),
        "pt_ratings": len(data.get("pt_ratings") or []),
        "flanges": len(data.get("flanges") or []),
        "vds_entries_evicted": evicted,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
