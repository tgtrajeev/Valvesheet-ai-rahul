"""Session management routes — list, get, rename, delete conversations."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.database import get_db
from ..services.session_service import (
    list_sessions,
    get_session,
    update_session_title,
    delete_session,
)

router = APIRouter()


class RenameRequest(BaseModel):
    title: str


@router.get("/sessions")
async def get_sessions(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """List all sessions, newest first."""
    return await list_sessions(db, limit=limit)


@router.get("/sessions/{session_id}")
async def get_session_detail(session_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single session with full message history."""
    session = await get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.patch("/sessions/{session_id}")
async def rename_session(
    session_id: str, body: RenameRequest, db: AsyncSession = Depends(get_db)
):
    """Rename a session."""
    ok = await update_session_title(db, session_id, body.title)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@router.delete("/sessions/{session_id}")
async def remove_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a session."""
    ok = await delete_session(db, session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}
