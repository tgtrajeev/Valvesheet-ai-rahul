"""Chat endpoint — SSE streaming from agent orchestrator."""

import json
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from ..models.schemas import ChatRequest
from ..agent.orchestrator import run_agent

router = APIRouter()


@router.post("/chat")
async def chat(request: ChatRequest):
    """Stream agent responses via SSE.

    Accepts a ChatRequest with messages and optional session_id.
    Returns an EventSourceResponse that streams AgentEvent objects.
    """
    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    async def event_generator():
        async for event in run_agent(messages, session_id=request.session_id):
            yield {
                "event": event.type,
                "data": json.dumps(event.data),
            }

    return EventSourceResponse(event_generator())
