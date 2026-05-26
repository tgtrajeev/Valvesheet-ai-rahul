"""Project document-code configuration.

Maps each project to its document-number prefixes (PMS, VMS, coating, etc.)
so datasheet outputs reference the correct project documents dynamically
instead of using hardcoded strings.

Adding a new project:
  1. Add an entry to ``PROJECT_CODES`` below.
  2. Restart the backend.  No code changes needed elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectDocCodes:
    """Document-code identifiers for a single project."""

    # Piping Material Specification doc number
    pms_doc: str = ""
    # Valve Material Specification doc number
    vms_doc: str = ""
    # Coating / paint general specification doc number
    coating_doc: str = ""
    # Human-readable project label
    project_label: str = ""


# ── Registry ─────────────────────────────────────────────────────────────────
# Key = canonical project name (case-insensitive lookup via helper).
# The *first* entry is the default used when no project name is provided.

PROJECT_CODES: dict[str, ProjectDocCodes] = {
    "FPSO P-82 Albacora Leste": ProjectDocCodes(
        pms_doc="40801-SPE-80000-PP-SP-0001",
        vms_doc="40801-SPE-80000-PP-SP-0002",
        coating_doc="50501-SPE-80000-ME-ET-0006",
        project_label="FPSO P-82 Albacora Leste",
    ),
    # ── Add new projects below ──────────────────────────────────────────────
    # "Project XYZ": ProjectDocCodes(
    #     pms_doc="12345-XYZ-...",
    #     vms_doc="12345-XYZ-...",
    #     coating_doc="12345-XYZ-...",
    #     project_label="Project XYZ",
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
