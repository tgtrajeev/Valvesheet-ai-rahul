"""Chat endpoint — SSE streaming from agent orchestrator with session persistence."""

import json
import logging
from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.schemas import ChatRequest
from ..models.database import get_db
from ..agent.orchestrator import run_agent
from ..services.session_service import get_or_create_session, save_session

logger = logging.getLogger(__name__)

router = APIRouter()

_DEFAULT_TITLE = "New conversation"


def _auto_title(text: str) -> str:
    """Generate a short title from the first user message."""
    text = text.strip()
    if len(text) <= 60:
        return text
    return text[:57] + "..."


@router.post("/chat")
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Stream agent responses via SSE with conversation persistence.

    - Loads prior agent_messages from DB for conversation resumption
    - Saves updated history after stream completes
    """
    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    # Load or create session
    session_id = request.session_id or ""
    session = await get_or_create_session(db, session_id) if session_id else None
    await db.commit()

    # Use stored agent_messages for Claude conversation continuity
    prior_agent_messages = (session.agent_messages or []) if session else []

    # Auto-title from first user message (default title is "New conversation")
    session_title = (session.title if session else None) or _DEFAULT_TITLE
    if session and session_title == _DEFAULT_TITLE and messages:
        first_user = next((m["content"] for m in messages if m["role"] == "user"), "")
        if first_user:
            session_title = _auto_title(first_user)

    async def event_generator():
        collected_agent_messages = []
        assistant_text = ""
        total_input_tokens = 0
        total_output_tokens = 0
        cache_read_tokens = 0
        cache_creation_tokens = 0
        # Capture rich UI events (suggestion/validation/datasheet) for session restore
        ui_events: list[dict] = []
        turn_index = len(session.messages or []) if session else 0

        async for event in run_agent(
            messages,
            session_id=session_id,
            prior_agent_messages=prior_agent_messages,
            project_id=request.project_id,
        ):
            # Capture agent_messages and token usage from orchestrator
            if event.type == "_agent_state":
                collected_agent_messages = event.data.get("agent_messages", [])
                continue
            if event.type == "text":
                assistant_text += event.data.get("text", "")
            if event.type == "done":
                total_input_tokens = event.data.get("input_tokens", 0)
                total_output_tokens = event.data.get("output_tokens", 0)
                cache_read_tokens = event.data.get("cache_read_tokens", 0)
                cache_creation_tokens = event.data.get("cache_creation_tokens", 0)
                if cache_read_tokens:
                    logger.info(
                        f"Session {session_id}: tokens in={total_input_tokens} out={total_output_tokens} "
                        f"cache_read={cache_read_tokens} cache_create={cache_creation_tokens} "
                        f"(saved ~{cache_read_tokens * 9 // 10} tokens via caching)"
                    )
            # Save rich events for session restore
            if event.type in ("suggestion", "validation", "datasheet"):
                ui_events.append({
                    "type": event.type,
                    "data": event.data,
                    "turn": turn_index,
                })

            yield {
                "event": event.type,
                "data": json.dumps(event.data),
            }

        # Persist session after stream completes
        if session_id and session:
            try:
                # Build user-visible messages: start from what's stored, add new ones
                chat_messages = list(session.messages or [])
                for m in messages:
                    if m not in chat_messages:
                        chat_messages.append(m)
                # Also save the assistant's response from this turn
                if assistant_text.strip():
                    chat_messages.append({"role": "assistant", "content": assistant_text})

                metadata = session.metadata_ or {}
                metadata["total_input_tokens"] = metadata.get("total_input_tokens", 0) + total_input_tokens
                metadata["total_output_tokens"] = metadata.get("total_output_tokens", 0) + total_output_tokens
                metadata["total_cache_read_tokens"] = metadata.get("total_cache_read_tokens", 0) + cache_read_tokens
                metadata["total_cache_creation_tokens"] = metadata.get("total_cache_creation_tokens", 0) + cache_creation_tokens
                # Append new UI events to existing ones
                existing_ui_events = metadata.get("ui_events", [])
                metadata["ui_events"] = existing_ui_events + ui_events

                await save_session(
                    db,
                    session_id,
                    messages=chat_messages,
                    agent_messages=collected_agent_messages or prior_agent_messages,
                    title=session_title,
                    metadata=metadata,
                )
            except Exception as e:
                logger.warning(f"Failed to persist session {session_id}: {e}")

    return EventSourceResponse(event_generator())
