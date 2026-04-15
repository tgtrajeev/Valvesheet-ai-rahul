"""Per-project file store.

Layout:
    data/projects/{project_id}/
        pms.json          canonical ProjectPMS
        vds_index.json    derived VDSIndex
        rules.yaml        project-specific validation rules (optional)
        raw/<file>        original uploaded file(s)
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import List, Optional

from .schema import ProjectPMS, VDSIndex, ProjectMetadata

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


def list_projects() -> List[ProjectMetadata]:
    if not PROJECTS_ROOT.exists():
        return []
    out: List[ProjectMetadata] = []
    for sub in PROJECTS_ROOT.iterdir():
        if not sub.is_dir():
            continue
        pms = load_pms(sub.name)
        if pms:
            out.append(pms.metadata)
    return out


def save_pms(pms: ProjectPMS) -> Path:
    d = ensure_project_dir(pms.metadata.project_id)
    path = d / "pms.json"
    path.write_text(pms.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_pms(project_id: str) -> Optional[ProjectPMS]:
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
