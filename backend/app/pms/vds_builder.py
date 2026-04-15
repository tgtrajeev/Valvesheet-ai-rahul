"""Derive a project-scoped VDS index from valve_assignments."""
from __future__ import annotations

from .schema import ProjectPMS, VDSIndex, VDSIndexEntry


def build_vds_index(pms: ProjectPMS) -> VDSIndex:
    entries = []
    for spec_code, pc in pms.piping_classes.items():
        for va in pc.valve_assignments:
            for code in va.vds_codes:
                entries.append(VDSIndexEntry(
                    vds_code=code,
                    piping_class=spec_code,
                    valve_type=va.valve_type,
                    nps_min=va.nps_min,
                    nps_max=va.nps_max,
                ))
    return VDSIndex(project_id=pms.metadata.project_id, entries=entries)
