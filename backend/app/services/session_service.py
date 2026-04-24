"""Session CRUD — persistence layer for conversation history."""

import logging
from datetime import datetime, timezone
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.database import Session

logger = logging.getLogger(__name__)


async def list_sessions(db: AsyncSession, limit: int = 50) -> list[dict]:
    """Return recent sessions, newest first."""
    result = await db.execute(
        select(Session)
        .order_by(Session.updated_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [
        {
            "id": s.id,
            "title": s.title or "New conversation",
            "message_count": len(s.messages or []),
            "metadata": s.metadata_ or {},
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in rows
    ]


async def get_session(db: AsyncSession, session_id: str) -> dict | None:
    """Return full session with messages and agent_messages."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    s = result.scalar_one_or_none()
    if not s:
        return None
    return {
        "id": s.id,
        "title": s.title or "New conversation",
        "messages": s.messages or [],
        "agent_messages": s.agent_messages or [],
        "metadata": s.metadata_ or {},
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


async def get_or_create_session(db: AsyncSession, session_id: str) -> Session:
    """Get existing session or create a new one."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if session:
        return session
    session = Session(
        id=session_id,
        title="New conversation",
        messages=[],
        agent_messages=[],
        metadata_={},
    )
    db.add(session)
    await db.flush()
    return session


async def save_session(
    db: AsyncSession,
    session_id: str,
    *,
    messages: list[dict] | None = None,
    agent_messages: list[dict] | None = None,
    title: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Update session fields. Only updates non-None fields."""
    values = {"updated_at": datetime.now(timezone.utc).replace(tzinfo=None)}
    if messages is not None:
        values["messages"] = messages
    if agent_messages is not None:
        values["agent_messages"] = agent_messages
    if title is not None:
        values["title"] = title
    if metadata is not None:
        values["metadata_"] = metadata

    await db.execute(
        update(Session).where(Session.id == session_id).values(**values)
    )
    await db.commit()


async def update_session_title(db: AsyncSession, session_id: str, title: str) -> bool:
    """Rename a session. Returns True if found."""
    result = await db.execute(
        update(Session).where(Session.id == session_id).values(
            title=title, updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
        )
    )
    await db.commit()
    return result.rowcount > 0


async def delete_session(db: AsyncSession, session_id: str) -> bool:
    """Delete a session. Returns True if found."""
    result = await db.execute(delete(Session).where(Session.id == session_id))
    await db.commit()
    return result.rowcount > 0
