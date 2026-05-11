"""Derive a project-scoped VDS index from valve_assignments."""
from __future__ import annotations

from .schema import ProjectPMS, VDSIndex, VDSIndexEntry


def iter_vds_codes(raw_codes: list[str]) -> list[str]:
    """Normalize PMS VDS cells that may contain comma-separated values."""
    out: list[str] = []
    for raw in raw_codes or []:
        if not isinstance(raw, str):
            continue
        for part in raw.split(","):
            code = part.strip().upper()
            if code:
                out.append(code)
    return list(dict.fromkeys(out))


def build_vds_index(pms: ProjectPMS) -> VDSIndex:
    entries = []
    for spec_code, pc in pms.piping_classes.items():
        for va in pc.valve_assignments:
            for code in iter_vds_codes(va.vds_codes):
                entries.append(VDSIndexEntry(
                    vds_code=code,
                    piping_class=spec_code,
                    valve_type=va.valve_type,
                    nps_min=va.nps_min,
                    nps_max=va.nps_max,
                ))
    return VDSIndex(project_id=pms.metadata.project_id, entries=entries)
