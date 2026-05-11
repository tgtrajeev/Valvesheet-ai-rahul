"""Standards PDF route — serves API/ASME/BS/ISO/PMS PDFs locally so citation
links in datasheets are clickable.

Routes:
  GET /api/standards            → list available standards (JSON)
  GET /api/standards/{slug}     → stream the PDF (browser opens at #page=N)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from ..engine.standards_registry import find_pdf, list_docs

router = APIRouter()


@router.get("/standards")
def list_standards() -> dict:
    return {"standards": list_docs()}


@router.get("/standards/{slug}")
def get_standard_pdf(slug: str):
    path = find_pdf(slug)
    if not path:
        raise HTTPException(status_code=404, detail=f"Standard '{slug}' not found on disk")
    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        # inline so the browser renders the PDF and honors #page=N anchors
        headers={"Content-Disposition": f'inline; filename="{path.name}"'},
    )
