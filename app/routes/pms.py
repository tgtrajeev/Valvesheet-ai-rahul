"""Project-scoped PMS upload, list, query, and sync."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..config import settings
from ..pms import store
from ..pms.api_client import PMSApiClient, sync_from_local_file
from ..pms.query import query as pms_query
from ..pms.vds_builder import build_vds_index
from ..pms.xlsx_parser import parse_xlsx

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pms", tags=["pms"])


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
