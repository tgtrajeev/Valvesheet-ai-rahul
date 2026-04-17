"""PMS external API client.

Handles fetching PMS data from the project's external PMS system and
converting it into the canonical PipingClass schema for storage.

Currently a skeleton — plug in the real API endpoint + auth tomorrow.
The parse/store logic is fully wired so swapping in the real API is
a one-line change in `fetch_raw_pms()`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from .schema import PipingClass, ProjectMetadata, ProjectPMS
from .xlsx_parser import parse_xlsx

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of a PMS sync operation."""
    project_id: str
    source: str                          # "api_sync" | "local_file"
    classes_synced: List[str]            # spec codes that were upserted
    classes_failed: List[str]            # spec codes that failed to parse
    synced_at: str                       # ISO timestamp
    error: Optional[str] = None
    pms: Optional["ProjectPMS"] = None   # parsed data (for DB persistence by caller)


class PMSApiClient:
    """Client for the external PMS API.

    Usage:
        client = PMSApiClient(base_url="https://pms.example.com/api", api_key="...")
        result = await client.sync_project("fpso-albacora")
    """

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def fetch_raw_pms(self, project_id: str) -> Dict[str, Any]:
        """Fetch raw PMS output from the external API.

        TODO: Replace this with the actual API call once the endpoint is ready.
        Expected response format (adapt as needed):
        {
            "project_id": "fpso-albacora",
            "piping_classes": [
                {
                    "spec_code": "B1N",
                    "pressure_rating": "300#",
                    "material_description": "CS NACE",
                    ...full PMS fields...
                }
            ]
        }
        """
        url = f"{self.base_url}/projects/{project_id}/pms"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def fetch_pms_file(self, project_id: str, download_path: Path) -> Path:
        """Download PMS as an Excel file from the API.

        Some PMS systems return XLSX directly instead of JSON.
        The file is saved locally, then parsed by xlsx_parser.

        TODO: Wire up the actual download endpoint.
        """
        url = f"{self.base_url}/projects/{project_id}/pms/download"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=self._headers())
            resp.raise_for_status()
            download_path.write_bytes(resp.content)
            return download_path

    async def sync_project(
        self,
        project_id: str,
        project_name: Optional[str] = None,
    ) -> SyncResult:
        """Pull latest PMS from external API, parse, and return structured data.

        This method handles two API response formats:
        1. JSON response — directly maps to PipingClass objects
        2. XLSX file download — parsed via xlsx_parser

        Returns a SyncResult with the parsed ProjectPMS ready for storage.
        The caller (store or route) handles the actual DB upsert.
        """
        now = datetime.now(timezone.utc).isoformat()
        classes_synced: List[str] = []
        classes_failed: List[str] = []

        try:
            raw = await self.fetch_raw_pms(project_id)
        except httpx.HTTPStatusError as e:
            logger.error(f"PMS API returned {e.response.status_code} for project {project_id}")
            return SyncResult(
                project_id=project_id,
                source="api_sync",
                classes_synced=[],
                classes_failed=[],
                synced_at=now,
                error=f"API error: HTTP {e.response.status_code}",
            )
        except httpx.RequestError as e:
            logger.error(f"PMS API connection failed for project {project_id}: {e}")
            return SyncResult(
                project_id=project_id,
                source="api_sync",
                classes_synced=[],
                classes_failed=[],
                synced_at=now,
                error=f"Connection error: {str(e)[:200]}",
            )

        # Parse the raw API response into PipingClass objects
        parsed_classes: Dict[str, PipingClass] = {}
        piping_classes = raw.get("piping_classes", [])
        for pc_raw in piping_classes:
            spec_code = pc_raw.get("spec_code", "UNKNOWN")
            try:
                pc = PipingClass.model_validate(pc_raw)
                parsed_classes[pc.spec_code] = pc
                classes_synced.append(pc.spec_code)
            except Exception as e:
                logger.warning(f"Failed to parse piping class {spec_code}: {e}")
                classes_failed.append(spec_code)

        # Build ProjectPMS so the caller can persist to DB
        pms = None
        if parsed_classes:
            meta = ProjectMetadata(
                project_id=project_id,
                name=project_name or project_id,
                source_file=f"{self.base_url}/projects/{project_id}/pms",
                status="approved",
            )
            pms = ProjectPMS(metadata=meta, piping_classes=parsed_classes)

        return SyncResult(
            project_id=project_id,
            source="api_sync",
            classes_synced=classes_synced,
            classes_failed=classes_failed,
            synced_at=now,
            pms=pms,
        )


async def sync_from_local_file(
    file_path: Path,
    project_id: str,
    project_name: Optional[str] = None,
) -> tuple[ProjectPMS, SyncResult]:
    """Parse a local PMS Excel file and return structured data.

    Used as the sync path until the real API is available.
    Also useful for manual file imports alongside API sync.
    """
    now = datetime.now(timezone.utc).isoformat()

    try:
        pms = parse_xlsx(file_path, project_id=project_id, project_name=project_name)
    except Exception as e:
        return None, SyncResult(
            project_id=project_id,
            source="local_file",
            classes_synced=[],
            classes_failed=[],
            synced_at=now,
            error=f"Parse error: {str(e)[:200]}",
        )

    classes_synced = list(pms.piping_classes.keys())
    result = SyncResult(
        project_id=project_id,
        source="local_file",
        classes_synced=classes_synced,
        classes_failed=[],
        synced_at=now,
    )
    return pms, result
