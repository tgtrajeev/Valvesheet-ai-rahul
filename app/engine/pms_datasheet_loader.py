"""PMS Datasheet Loader — loads PDF-extracted datasheet records per project.

Each project ships a `pms_datasheet_extracted.json` keyed by VDS code, where every
field carries the value, the source PDF page, and the verification status. This
file is used as a page-level verification map back to the project PMS PDF.
It is not the value source for generated sheets; live output is generated from
current PMS piping-class data plus engineering rules.

Schema:
    {
      "BLFTA1R": {
        "Valve Standard":  {"value": "API 6D / ISO 17292",
                            "pdf_source": "PMS_PDF.pdf page 39",
                            "verification": "EXACT"},
        "Pressure Class": {"value": "ASME B16.34 Class 150",
                            "pdf_source": "PMS_PDF.pdf page 39",
                            "verification": "EXACT"},
        ...
      },
      ...
    }
"""

import json
from pathlib import Path
from typing import Optional


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
