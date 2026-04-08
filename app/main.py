"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .models.database import init_db
from .routes.chat import router as chat_router
from .routes.sessions import router as sessions_router
from .routes.validate import router as validate_router
from .routes.datasheets import router as datasheets_router
from .routes.ingest import router as ingest_router
from .routes.metadata import router as metadata_router
from .routes.suggest import router as suggest_router
from .routes.downloads import router as downloads_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup, cleanup on shutdown."""
    logger.info("Starting Valve Agent API...")
    await init_db()
    logger.info("Valve Agent API ready.")
    yield


app = FastAPI(
    title="Valve Agent API",
    description="RAG Agentic Valve Datasheet Generator",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(validate_router, prefix="/api")
app.include_router(datasheets_router, prefix="/api")
app.include_router(ingest_router, prefix="/api")
app.include_router(metadata_router, prefix="/api")
app.include_router(suggest_router, prefix="/api")
app.include_router(downloads_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
