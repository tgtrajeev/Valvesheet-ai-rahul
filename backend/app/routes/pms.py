"""Project-scoped PMS upload, list, query."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..pms import store
from ..pms.query import query as pms_query
from ..pms.vds_builder import build_vds_index
from ..pms.xlsx_parser import parse_xlsx

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

    store.save_pms(pms)
    idx = build_vds_index(pms)
    store.save_vds_index(idx)

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
