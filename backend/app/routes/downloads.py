"""Agent download tracking — save and list generated datasheet downloads."""

from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.database import AgentDownload, get_db

router = APIRouter()


class SaveDownloadRequest(BaseModel):
    session_id: Optional[str] = None
    vds_codes: list[str]
    filename: str
    download_type: str  # "xlsx" or "zip"
    sheet_count: int = 1


@router.post("/downloads")
async def save_download(body: SaveDownloadRequest, db: AsyncSession = Depends(get_db)):
    """Track a completed download."""
    dl = AgentDownload(
        session_id=body.session_id,
        vds_codes=body.vds_codes,
        filename=body.filename,
        download_type=body.download_type,
        sheet_count=body.sheet_count,
    )
    db.add(dl)
    await db.commit()
    await db.refresh(dl)
    return {
        "id": dl.id,
        "filename": dl.filename,
        "vds_codes": dl.vds_codes,
        "download_type": dl.download_type,
        "sheet_count": dl.sheet_count,
        "created_at": dl.created_at.isoformat() if dl.created_at else None,
    }


@router.get("/downloads")
async def list_downloads(
    limit: int = 50,
    session_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List recent downloads, newest first."""
    query = select(AgentDownload).order_by(AgentDownload.created_at.desc()).limit(limit)
    if session_id:
        query = query.where(AgentDownload.session_id == session_id)
    result = await db.execute(query)
    rows = result.scalars().all()
    return [
        {
            "id": d.id,
            "session_id": d.session_id,
            "vds_codes": d.vds_codes,
            "filename": d.filename,
            "download_type": d.download_type,
            "sheet_count": d.sheet_count,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in rows
    ]
