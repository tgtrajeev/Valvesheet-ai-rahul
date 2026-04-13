"""SQLAlchemy async database setup with optional pgvector support."""

import logging

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, JSON, func, text

from ..config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.async_database_url, echo=False, pool_pre_ping=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"
    id = Column(String(64), primary_key=True)
    title = Column(String(255), default="New conversation")
    messages = Column(JSON, default=list)          # user-visible chat history
    agent_messages = Column(JSON, default=list)     # full Anthropic message history for resumption
    metadata_ = Column("metadata", JSON, default=dict)  # token counts, vds codes, etc.
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class GeneratedDatasheet(Base):
    __tablename__ = "generated_datasheets"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64))
    vds_code = Column(String(20), nullable=False)
    datasheet = Column(JSON, nullable=False)
    validation_status = Column(String(20))
    completion_pct = Column(Float)
    created_at = Column(DateTime, server_default=func.now())


class AgentDownload(Base):
    __tablename__ = "agent_downloads"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64))
    vds_codes = Column(JSON, nullable=False)       # list of VDS codes
    filename = Column(String(255), nullable=False)
    download_type = Column(String(10), nullable=False)  # "xlsx" or "zip"
    sheet_count = Column(Integer, default=1)
    created_at = Column(DateTime, server_default=func.now())


class IngestedDocument(Base):
    __tablename__ = "ingested_documents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    doc_type = Column(String(50))
    chunk_count = Column(Integer, default=0)
    file_size_bytes = Column(Integer)
    ingested_at = Column(DateTime, server_default=func.now())


# DocumentChunk with pgvector is created separately only if extension is available
DocumentChunk = None


async def _try_create_pgvector_table(conn):
    """Try to enable pgvector and create the document_chunks table. Non-fatal if it fails."""
    try:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id SERIAL PRIMARY KEY,
                content TEXT NOT NULL,
                embedding vector(384),
                source_type VARCHAR(50),
                document_name VARCHAR(255),
                section VARCHAR(255),
                piping_class VARCHAR(20),
                valve_type VARCHAR(10),
                metadata JSON,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
            )
        """))
        logger.info("pgvector document_chunks table ready.")
    except Exception as e:
        logger.warning(f"pgvector not available — RAG features disabled. ({type(e).__name__})")


async def _migrate_sessions_table(conn):
    """Add new columns to sessions table if they don't exist (for existing DBs)."""
    migrations = [
        ("title", "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS title VARCHAR(255) DEFAULT 'New conversation'"),
        ("agent_messages", "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS agent_messages JSON DEFAULT '[]'"),
        ("metadata", "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS metadata JSON DEFAULT '{}'"),
    ]
    for col_name, sql in migrations:
        try:
            await conn.execute(text(sql))
        except Exception as e:
            logger.debug(f"Migration for sessions.{col_name} skipped: {e}")


async def init_db():
    """Create tables if they don't exist."""
    # Create core tables (no pgvector dependency)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Migrate existing sessions table with new columns
    async with engine.begin() as conn:
        await _migrate_sessions_table(conn)

    # Try pgvector table separately — non-fatal
    async with engine.begin() as conn:
        await _try_create_pgvector_table(conn)

    logger.info("Database initialized.")


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session
