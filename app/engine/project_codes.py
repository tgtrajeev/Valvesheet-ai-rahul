"""Project document-code configuration.

Maps each project to its document-number prefixes (PMS, VMS, coating, etc.)
so datasheet outputs reference the correct project documents dynamically
instead of using hardcoded strings.

Only the first segment of the doc number changes per project (the project
code).  The rest of the template is shared:
  PMS  → {project_code}-SPE-80000-PP-SP-0001
  VMS  → {project_code}-SPE-80000-PP-SP-0002

Adding a new project:
  1. Add an entry to ``PROJECT_CODES`` below with its ``project_code``.
  2. Restart the backend.  No code changes needed elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ── Document-number templates ────────────────────────────────────────────────
# {code} is replaced by the project's project_code at runtime.
_PMS_TEMPLATE = "{code}-SPE-80000-PP-SP-0001"
_VMS_TEMPLATE = "{code}-SPE-80000-PP-SP-0002"


@dataclass(frozen=True)
class ProjectDocCodes:
    """Document-code identifiers for a single project."""

    # Short project code — the first segment of every doc number.
    # e.g. "40801", "FPSO-006", "KLK-001"
    project_code: str = ""

    # Coating / paint spec — has its own numbering scheme, stored in full.
    coating_doc: str = ""

    # Human-readable project label
    project_label: str = ""

    # Computed doc numbers (auto-built from project_code + template)
    @property
    def pms_doc(self) -> str:
        return _PMS_TEMPLATE.format(code=self.project_code) if self.project_code else ""

    @property
    def vms_doc(self) -> str:
        return _VMS_TEMPLATE.format(code=self.project_code) if self.project_code else ""


# ── Registry ─────────────────────────────────────────────────────────────────
# Key = canonical project name (case-insensitive lookup via helper).
# The *first* entry is the default used when no project name is provided.

PROJECT_CODES: dict[str, ProjectDocCodes] = {
    "FPSO P-82 Albacora Leste": ProjectDocCodes(
        project_code="40801",
        coating_doc="50501-SPE-80000-ME-ET-0006",
        project_label="FPSO P-82 Albacora Leste",
    ),
    # ── Add new projects below ──────────────────────────────────────────────
    # "Kalkinda Project": ProjectDocCodes(
    #     project_code="FPSO-006",
    #     coating_doc="FPSO-006-...-...",
    #     project_label="Kalkinda Project (FPSO-006)",
    # ),
}

# Default entry (first key)
_DEFAULT_PROJECT = next(iter(PROJECT_CODES))
_DEFAULT_CODES = PROJECT_CODES[_DEFAULT_PROJECT]

# Build a case-insensitive lookup index
_CI_INDEX: dict[str, ProjectDocCodes] = {
    k.lower(): v for k, v in PROJECT_CODES.items()
}


# ── Public helpers ────────────────────────────────────────────────────────────

def get_project_codes(project_name: str | None = None) -> ProjectDocCodes:
    """Resolve document codes for a project name.

    Falls back to the default project if *project_name* is None, empty,
    or not found in the registry.
    """
    if not project_name:
        return _DEFAULT_CODES
    codes = _CI_INDEX.get(project_name.strip().lower())
    return codes if codes else _DEFAULT_CODES


def get_pms_doc(project_name: str | None = None) -> str:
    """Return the PMS document number for the given project."""
    return get_project_codes(project_name).pms_doc


def get_vms_doc(project_name: str | None = None) -> str:
    """Return the VMS document number for the given project."""
    return get_project_codes(project_name).vms_doc


def get_coating_doc(project_name: str | None = None) -> str:
    """Return the coating/paint specification document number."""
    return get_project_codes(project_name).coating_doc


def get_project_label(project_name: str | None = None) -> str:
    """Return the canonical project label."""
    return get_project_codes(project_name).project_label
