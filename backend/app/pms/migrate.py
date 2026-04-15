"""Convert legacy pms_extracted.json into the canonical ProjectPMS schema.

Run: python -m app.pms.migrate
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .schema import (
    AttributeValue, PipingClass, ProjectMetadata, ProjectPMS,
    PTRating, PipeScheduleRow, ValveAssignment,
)
from .store import save_pms, save_vds_index
from .vds_builder import build_vds_index
from .xlsx_parser import _attr  # reuse helper


LEGACY_PATH = Path(__file__).resolve().parent.parent / "data" / "pms_extracted.json"
LEGACY_PROJECT_ID = "fpso-albacora"
LEGACY_PROJECT_NAME = "FPSO Albacora (legacy)"


def _convert_class(spec_code: str, raw: dict) -> PipingClass:
    pc = PipingClass(spec_code=spec_code)
    header = raw.get("header") or {}
    for k, v in header.items():
        if v is None or k == "spec_code":
            continue
        pc.attributes[k] = _attr(v)

    for r in raw.get("pt_ratings") or []:
        if r.get("temperature_c") is not None and r.get("max_pressure_barg") is not None:
            pc.pt_ratings.append(PTRating(
                temperature_c=r["temperature_c"],
                max_pressure_barg=r["max_pressure_barg"],
            ))

    for r in raw.get("pipe_schedule") or []:
        pc.pipe_schedule.append(PipeScheduleRow(
            nps_inch=r.get("nps_inch", 0.0),
            od_mm=r.get("od_mm"),
            schedule_val=r.get("schedule_val"),
            wall_thickness_mm=r.get("wall_thickness_mm"),
            pipe_type=r.get("pipe_type"),
            pipe_moc=r.get("pipe_moc"),
            pipe_std=r.get("pipe_std"),
            ends=r.get("ends"),
        ))

    for v in raw.get("valve_assignments") or []:
        pc.valve_assignments.append(ValveAssignment(
            valve_type=v.get("valve_type", "UNKNOWN"),
            nps_min=v.get("nps_min"),
            nps_max=v.get("nps_max"),
            vds_codes=v.get("vds_codes") or [],
            raw_cell_value=v.get("raw_cell_value"),
            notes=v.get("notes"),
            valve_standard=v.get("valve_standard"),
        ))

    pc.flanges = raw.get("flanges") or []
    pc.bolting_gaskets = raw.get("bolting_gaskets")
    return pc


def migrate() -> ProjectPMS:
    legacy = json.loads(LEGACY_PATH.read_text(encoding="utf-8"))
    classes = {code: _convert_class(code, body) for code, body in legacy.items()}
    pms = ProjectPMS(
        metadata=ProjectMetadata(
            project_id=LEGACY_PROJECT_ID,
            name=LEGACY_PROJECT_NAME,
            source_file=LEGACY_PATH.name,
            uploaded_at=datetime.now(timezone.utc).isoformat(),
            status="approved",
            notes="Migrated from legacy pms_extracted.json",
        ),
        piping_classes=classes,
    )
    save_pms(pms)
    save_vds_index(build_vds_index(pms))
    return pms


if __name__ == "__main__":
    pms = migrate()
    print(f"Migrated {len(pms.piping_classes)} classes -> project '{pms.metadata.project_id}'")
