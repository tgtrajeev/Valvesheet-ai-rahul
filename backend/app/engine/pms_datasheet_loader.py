"""PMS Datasheet Loader — loads PDF-extracted datasheet records.

Two file formats are supported:

1. **Per-project file** (`data/projects/<id>/pms_datasheet_extracted.json`) —
   verification map. Labels carry value + pdf_source + verification status.
   Schema:
       {"BLFTA1R": {"Valve Standard": {"value": "...", "pdf_source": "...",
                                       "verification": "EXACT"}}}

2. **Global VDS datasheets** (`data/pms_vds_datasheets.json`) — the
   authoritative per-VDS PMS source extracted from PMS_PDF.pdf. Flat schema
   keyed by VDS code, snake_case field names mapping directly to engine fields.
   Schema:
       {"BLFTA1R": {"body_material": "ASTM A105N...", "gland_packing": "...",
                    "lever_handwheel": "...", "spring": "Inconel 750", ...}}

The global file is the primary source for `generate_datasheet`; per-project
files act as audit/verification overlays.
"""

import json
from pathlib import Path
from typing import Any, Optional

# Provenance `source` strings in pms_reference_tables.json must stay PMS-first;
# optional API 615 is the only external document ID allowed there (see file _meta).
_BANNED_PMS_REF_SOURCE_MARKERS: tuple[str, ...] = (
    "ASME B16",
    "NACE",
    "ISO ",
    "BS EN",
    "EEMUA",
    "API 6D",
    "API 609",
    "API 600",
    "API 602",
    "API 603",
    "API 594",
    "API 607",
    "API 6FA",
    "API STD",
)


def _validate_pms_reference_table_sources(tables: dict[str, Any]) -> None:
    for table_name, rows in tables.items():
        if not isinstance(rows, dict):
            continue
        for key, row in rows.items():
            if not isinstance(row, dict):
                continue
            src = row.get("source")
            if not isinstance(src, str) or not src.strip():
                raise ValueError(
                    f"pms_reference_tables.json: missing source for "
                    f"table {table_name!r} key {key!r}"
                )
            if "PMS_PDF.pdf" not in src:
                raise ValueError(
                    f"pms_reference_tables.json: source must cite PMS_PDF.pdf "
                    f"(table {table_name!r} key {key!r})"
                )
            for bad in _BANNED_PMS_REF_SOURCE_MARKERS:
                if bad in src:
                    raise ValueError(
                        f"pms_reference_tables.json: disallowed citation fragment "
                        f"{bad!r} in source (table {table_name!r} key {key!r})"
                    )
            if "API " in src and "API 615" not in src:
                raise ValueError(
                    f"pms_reference_tables.json: only API 615 may appear as an "
                    f"API document citation in source (table {table_name!r} key {key!r})"
                )


# Map from datasheet label (as seen in the extracted JSON) to the engine's
# internal field name in the dict returned by generate_datasheet().
LABEL_TO_FIELD = {
    "Valve type":                     "valve_type",
    "Valve Standard":                 "valve_standard",
    "Pressure Class":                 "pressure_class",
    "Design Pressure":                "design_pressure",
    "Corrosion Allowance":            "corrosion_allowance",
    "Sour Service Requirements":      "sour_service",
    "End Connections":                "end_connections",
    "Face to Face Dimension":         "face_to_face",
    "Body":                           "body_construction",
    "Ball":                           "ball_construction",
    "Stem":                           "stem_construction",
    "Seat":                           "seat_construction",
    "Disc":                           "disc_construction",
    "Wedge":                          "wedge_construction",
    "Back Seat":                      "back_seat_construction",
    "Cover":                          "cover_construction",
    "Bonnet":                         "bonnet_construction",
    "Shaft":                          "shaft_construction",
    "Packing":                        "packing_construction",
    "Locks":                          "locks",
    "Operation":                      "operation",
    "Body Material":                  "body_material",
    "Ball Material":                  "ball_material",
    "Disc Material":                  "disc_material",
    "Wedge Material":                 "wedge_material",
    "Trim Material":                  "trim_material",
    "Seat Material":                  "seat_material",
    "Seal Material":                  "seal_material",
    "Stem Material":                  "stem_material",
    "Shaft material":                 "shaft_material",
    "Gland material":                 "gland_material",
    "Gland Material":                 "gland_material",
    "Gland Packing":                  "gland_packing",
    "Gland packing":                  "gland_packing",
    "Cover Material":                 "cover_material",
    "Hinge/ Hinge Pin":               "hinge_pin_material",
    "Spring":                         "spring_material",
    "Lever / Handwheel":              "lever_handwheel",
    "Needle Material":                "needle_material",
    "Back Seat Mat.":                 "back_seat_material",
    "Gaskets":                        "gaskets",
    "Bolts":                          "bolts",
    "Nuts":                           "nuts",
    "Marking - Purchaser’s Specification": "marking_purchaser",
    "Marking – Manufacturer":    "marking_manufacturer",
    "Inspection – Testing":      "inspection_testing",
    "Leakage Rate":                   "leakage_rate",
    "Hydrotest Shell Test Pressure":  "hydrotest_shell",
    "Hydrotest Closure Test Pressure": "hydrotest_closure",
    "Pneumatic LP Test Pressure":     "pneumatic_test",
    "Material Certification":         "material_certification",
    "Fire Rating":                    "fire_rating",
    "Finish":                         "finish",
    "Size Range":                     "size_range",
    "Service":                        "service",
    "Piping Class":                   "piping_class",
    "VDS No":                         "vds_no",
}


class PmsDatasheetLoader:
    """Loads per-VDS datasheet records extracted from a project's PMS PDF."""

    def __init__(self, json_path: Path):
        with open(json_path, encoding="utf-8") as f:
            self._records: dict = json.load(f)

    @property
    def vds_codes(self) -> list[str]:
        return sorted(self._records.keys())

    @property
    def total(self) -> int:
        return len(self._records)

    def has(self, vds_code: str) -> bool:
        return vds_code.upper().strip().replace("VDS-", "") in self._records

    def get_datasheet(self, vds_code: str) -> tuple[dict[str, str], dict[str, str]] | None:
        """Return (data, provenance) or None if VDS not in extracted file.

        data:        flat {field_name: value}
        provenance:  flat {field_name: "PMS_PDF.pdf page N"}
        """
        key = vds_code.upper().strip().replace("VDS-", "")
        rec = self._records.get(key)
        if not rec:
            return None
        data: dict[str, str] = {}
        provenance: dict[str, str] = {}
        for label, payload in rec.items():
            field = LABEL_TO_FIELD.get(label)
            if not field:
                continue
            value = payload.get("value", "")
            src = payload.get("pdf_source", "")
            if not value or value == "#VALUE!":
                continue
            data[field] = value
            provenance[field] = src
        return data, provenance


# ── Per-project singleton cache ────────────────────────────────────────────

_loaders: dict[str, PmsDatasheetLoader] = {}


def _project_path(project_id: str) -> Path:
    from ..config import settings
    return settings.data_dir / "projects" / project_id / "pms_datasheet_extracted.json"


def get_datasheet_loader(project_id: str = "pttep-sabah") -> PmsDatasheetLoader | None:
    """Get or lazily load the datasheet extractor for a project.

    Returns None if the project has no extracted datasheet file (engine then
    falls back to rule-based generation).
    """
    if project_id in _loaders:
        return _loaders[project_id]
    p = _project_path(project_id)
    if not p.exists():
        return None
    loader = PmsDatasheetLoader(p)
    _loaders[project_id] = loader
    return loader


def refresh_datasheet_loader(project_id: str | None = None) -> None:
    """Force reload (call after a new project's PDF is extracted)."""
    if project_id is None:
        _loaders.clear()
    else:
        _loaders.pop(project_id, None)


# ── Global per-VDS datasheets (PMS_PDF.pdf authoritative extraction) ─────────

class GlobalVdsDatasheetLoader:
    """Loads the global PMS_PDF-extracted per-VDS datasheets file.

    The file is keyed by VDS code (e.g. "BLFTA1R") with flat snake_case field
    names that map directly to the engine's output dict. Field values are
    strings sourced from `PMS_PDF.pdf` — they are the authoritative project
    PMS values per VDS code.

    A field returning ``None`` means the extraction did not capture that field
    for that VDS code. Per the no-fallback rule, callers should raise/log
    rather than silently substitute a constant.
    """

    def __init__(self, json_path: Path):
        with open(json_path, encoding="utf-8") as f:
            self._records: dict = json.load(f)
        self._path = json_path

    @property
    def vds_codes(self) -> list[str]:
        return sorted(self._records.keys())

    @property
    def total(self) -> int:
        return len(self._records)

    def has(self, vds_code: str) -> bool:
        return self._normalize(vds_code) in self._records

    def get(self, vds_code: str) -> Optional[dict]:
        return self._records.get(self._normalize(vds_code))

    def get_field(self, vds_code: str, field: str) -> Optional[str]:
        """Return a single field for a VDS, or None if absent/unfilled.

        ``construction`` is a nested dict in source; callers wanting a
        construction subfield should pass ``construction.body`` etc.
        """
        rec = self.get(vds_code)
        if not rec:
            return None
        if "." in field:
            head, _, tail = field.partition(".")
            nested = rec.get(head)
            if isinstance(nested, dict):
                v = nested.get(tail)
                return v if v else None
            return None
        v = rec.get(field)
        return v if v else None

    @staticmethod
    def _normalize(vds_code: str) -> str:
        return (vds_code or "").upper().strip().replace("VDS-", "")


_global_loader: Optional[GlobalVdsDatasheetLoader] = None


def _global_path() -> Path:
    from ..config import settings
    return settings.data_dir / "pms_vds_datasheets.json"


def get_global_vds_loader() -> Optional[GlobalVdsDatasheetLoader]:
    """Return the singleton global per-VDS datasheet loader, or None if the
    JSON file is absent. Loaded lazily on first call.
    """
    global _global_loader
    if _global_loader is not None:
        return _global_loader
    p = _global_path()
    if not p.exists():
        return None
    _global_loader = GlobalVdsDatasheetLoader(p)
    return _global_loader


def refresh_global_vds_loader() -> None:
    """Clear the cached global loader so the next call rereads the JSON.
    Call after the extraction script writes a new pms_vds_datasheets.json.
    """
    global _global_loader
    _global_loader = None


# ── Externalized PMS reference tables (no-fallback material lookups) ─────────

class PmsReferenceTables:
    """Strict per-category material/bolting lookups with provenance.

    Backs `pms_reference_tables.json`. Every row is keyed by material category
    and carries `{value, source}` where source cites PMS_PDF.pdf §X.Y. Use
    `get(table, key)` for a strict lookup that raises ``KeyError`` when the
    category is not registered for that table — there is no implicit CS
    fallback. A missing entry is a bug to fix in the JSON, not a runtime
    branch (per project no-fallback rule).
    """

    def __init__(self, json_path: Path):
        with open(json_path, encoding="utf-8") as f:
            payload = json.load(f)
        self._tables = payload.get("tables", {})
        _validate_pms_reference_table_sources(self._tables)

    def get(self, table: str, key: str) -> str:
        rows = self._tables.get(table)
        if rows is None:
            raise KeyError(
                f"PmsReferenceTables: unknown table '{table}'. "
                f"Add it to pms_reference_tables.json."
            )
        row = rows.get(key)
        if row is None:
            raise KeyError(
                f"PmsReferenceTables: no entry for table '{table}', key '{key}'. "
                f"Add a row to pms_reference_tables.json with citation, or fix "
                f"the category derivation upstream."
            )
        return row["value"]

    def source(self, table: str, key: str) -> Optional[str]:
        rows = self._tables.get(table) or {}
        row = rows.get(key)
        return row.get("source") if row else None

    def has(self, table: str, key: str) -> bool:
        return key in (self._tables.get(table) or {})

    def lookup(self, table: str, *keys: str) -> str:
        """Strict tuple-style lookup: try keys joined by ':' first, fall back
        to head key only. Raises if neither is present.

        Example: lookup('valve_standard', 'CH', 'D') tries 'CH:D' then 'CH'.
        """
        if not keys:
            raise KeyError(f"PmsReferenceTables.lookup: no keys for table '{table}'")
        compound = ":".join(k for k in keys if k)
        if self.has(table, compound):
            return self.get(table, compound)
        head = keys[0]
        if self.has(table, head):
            return self.get(table, head)
        raise KeyError(
            f"PmsReferenceTables: no entry for table '{table}' under "
            f"'{compound}' or '{head}'. Add a row in pms_reference_tables.json."
        )


_ref_tables: Optional[PmsReferenceTables] = None


def get_reference_tables() -> PmsReferenceTables:
    """Singleton accessor for PMS reference tables.

    Raises FileNotFoundError if the JSON is missing — a build-time error,
    not a runtime fallback.
    """
    global _ref_tables
    if _ref_tables is not None:
        return _ref_tables
    from ..config import settings
    p = settings.data_dir / "pms_reference_tables.json"
    if not p.exists():
        raise FileNotFoundError(
            f"PMS reference tables JSON not found at {p}. "
            f"This file is required for no-fallback rule_engine operation."
        )
    _ref_tables = PmsReferenceTables(p)
    return _ref_tables


def refresh_reference_tables() -> None:
    """Clear the cached reference tables so the next call rereads the JSON."""
    global _ref_tables
    _ref_tables = None
