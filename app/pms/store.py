"""Per-project PMS store — file-based + DB-backed.

File layout (existing, kept for backwards compat):
    data/projects/{project_id}/
        pms.json          canonical ProjectPMS
        vds_index.json    derived VDSIndex
        raw/<file>        original uploaded file(s)

DB layout (new):
    pms_sheets table — one row per piping class per project.
    Supports both xlsx_upload and api_sync sources.

The unified `load_pms()` checks DB first, falls back to file.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .schema import PipingClass, ProjectPMS, ProjectMetadata, VDSIndex

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent
PROJECTS_ROOT = APP_DIR / "data" / "projects"


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower())
    return s.strip("-") or "project"


def project_dir(project_id: str) -> Path:
    return PROJECTS_ROOT / _slug(project_id)


def ensure_project_dir(project_id: str) -> Path:
    d = project_dir(project_id)
    (d / "raw").mkdir(parents=True, exist_ok=True)
    return d


# ── File-based operations (existing, unchanged) ──────────────────────────────

def list_projects() -> List[ProjectMetadata]:
    if not PROJECTS_ROOT.exists():
        return []
    out: List[ProjectMetadata] = []
    for sub in PROJECTS_ROOT.iterdir():
        if not sub.is_dir():
            continue
        pms = load_pms_from_file(sub.name)
        if pms:
            out.append(pms.metadata)
    return out


def save_pms(pms: ProjectPMS) -> Path:
    d = ensure_project_dir(pms.metadata.project_id)
    path = d / "pms.json"
    path.write_text(pms.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_pms_from_file(project_id: str) -> Optional[ProjectPMS]:
    path = project_dir(project_id) / "pms.json"
    if not path.exists():
        return None
    return ProjectPMS.model_validate_json(path.read_text(encoding="utf-8"))


def save_vds_index(index: VDSIndex) -> Path:
    d = ensure_project_dir(index.project_id)
    path = d / "vds_index.json"
    path.write_text(index.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_vds_index(project_id: str) -> Optional[VDSIndex]:
    path = project_dir(project_id) / "vds_index.json"
    if not path.exists():
        return None
    return VDSIndex.model_validate_json(path.read_text(encoding="utf-8"))


def save_raw_upload(project_id: str, filename: str, content: bytes) -> Path:
    d = ensure_project_dir(project_id)
    target = d / "raw" / filename
    target.write_bytes(content)
    return target


# ── DB-backed operations (new) ───────────────────────────────────────────────

async def save_pms_to_db(
    project_id: str,
    project_name: str,
    piping_classes: Dict[str, PipingClass],
    source: str = "xlsx_upload",
    source_file: Optional[str] = None,
    status: str = "draft",
) -> List[str]:
    """Upsert piping classes into the pms_sheets DB table.

    Returns list of spec_codes that were saved.
    """
    from ..models.database import async_session, PMSSheet
    from sqlalchemy import select

    saved: List[str] = []
    now = datetime.now(timezone.utc)

    async with async_session() as session:
        for spec_code, pc in piping_classes.items():
            # Check if row already exists
            stmt = select(PMSSheet).where(
                PMSSheet.project_id == project_id,
                PMSSheet.spec_code == spec_code,
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            pc_data = pc.model_dump()

            if existing:
                # Update existing row
                existing.pms_data = pc_data
                existing.source = source
                existing.source_file = source_file
                existing.status = status
                existing.synced_at = now if source == "api_sync" else existing.synced_at
                existing.updated_at = now
            else:
                # Insert new row
                row = PMSSheet(
                    project_id=project_id,
                    project_name=project_name,
                    spec_code=spec_code,
                    source=source,
                    source_file=source_file,
                    pms_data=pc_data,
                    status=status,
                    synced_at=now if source == "api_sync" else None,
                )
                session.add(row)

            saved.append(spec_code)

        await session.commit()

    logger.info(f"Saved {len(saved)} PMS classes to DB for project '{project_id}'")
    return saved


async def load_pms_from_db(project_id: str) -> Optional[ProjectPMS]:
    """Load all piping classes for a project from the DB.

    Returns a ProjectPMS built from DB rows, or None if no rows exist.
    """
    from ..models.database import async_session, PMSSheet
    from sqlalchemy import select

    async with async_session() as session:
        stmt = select(PMSSheet).where(PMSSheet.project_id == project_id)
        result = await session.execute(stmt)
        rows = result.scalars().all()

    if not rows:
        return None

    piping_classes: Dict[str, PipingClass] = {}
    project_name = project_id
    source_file = None

    for row in rows:
        try:
            pc = PipingClass.model_validate(row.pms_data)
            piping_classes[row.spec_code] = pc
        except Exception as e:
            logger.warning(f"Failed to parse DB row for {row.spec_code}: {e}")
            continue
        if row.project_name:
            project_name = row.project_name
        if row.source_file:
            source_file = row.source_file

    if not piping_classes:
        return None

    meta = ProjectMetadata(
        project_id=project_id,
        name=project_name,
        source_file=source_file,
        status=rows[0].status or "draft",
    )
    return ProjectPMS(metadata=meta, piping_classes=piping_classes)


async def load_piping_class_from_db(
    project_id: str, spec_code: str
) -> Optional[PipingClass]:
    """Load a single piping class from the DB."""
    from ..models.database import async_session, PMSSheet
    from sqlalchemy import select

    async with async_session() as session:
        stmt = select(PMSSheet).where(
            PMSSheet.project_id == project_id,
            PMSSheet.spec_code == spec_code.upper().strip(),
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

    if not row:
        return None

    return PipingClass.model_validate(row.pms_data)


async def list_projects_from_db() -> List[dict]:
    """List all distinct projects in the pms_sheets table."""
    from ..models.database import async_session, PMSSheet
    from sqlalchemy import select, func

    async with async_session() as session:
        stmt = (
            select(
                PMSSheet.project_id,
                PMSSheet.project_name,
                PMSSheet.source,
                PMSSheet.status,
                func.count(PMSSheet.id).label("class_count"),
            )
            .group_by(PMSSheet.project_id, PMSSheet.project_name, PMSSheet.source, PMSSheet.status)
        )
        result = await session.execute(stmt)
        rows = result.all()

    return [
        {
            "project_id": r.project_id,
            "project_name": r.project_name,
            "source": r.source,
            "status": r.status,
            "class_count": r.class_count,
        }
        for r in rows
    ]


# ── Unified load (DB first, file fallback) ───────────────────────────────────

# In-process cache for DB-loaded PMS data (populated by warm_pms_cache).
_db_pms_cache: Dict[str, ProjectPMS] = {}


def warm_pms_cache(project_id: str, pms: ProjectPMS) -> None:
    """Cache DB-loaded PMS in memory so sync load_pms() can return it."""
    _db_pms_cache[project_id] = pms


def invalidate_pms_cache(project_id: str) -> None:
    """Remove a project from the in-memory cache (e.g. after sync/upload)."""
    _db_pms_cache.pop(project_id, None)


def load_pms(project_id: str) -> Optional[ProjectPMS]:
    """Synchronous unified loader — DB cache first, then file fallback.

    DB data is loaded into the cache by warm_pms_cache() (called from async
    contexts like the sync route or app startup). This keeps the function
    synchronous for existing callers (tools, pms_resolver) while preferring
    DB-backed data over file-only data.
    """
    # 1. Check in-memory DB cache
    cached = _db_pms_cache.get(project_id)
    if cached is not None:
        return cached

    # 2. Fall back to file-based store
    return load_pms_from_file(project_id)
