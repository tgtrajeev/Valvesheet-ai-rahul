"""Rule-derived fields from PMS data.

Per PMS specialist (verified 2026-04-20 on pms_extracted.json):
given (valve_type, piping_class), pressure and material are already
encoded in the spec_code, and end connection is deterministic — every
(valve_type, spec_code) key in PMS maps to exactly one end-connection code
across 504 unique keys / 707 VDS codes (100% coverage).

This module builds that (valve_type, spec) -> end_connection lookup by
parsing the VDS codes that PMS lists per valve_assignment. The lookup is
cached; first use triggers a lazy build from the PmsLoader singleton.
"""

from __future__ import annotations

from .pms_loader import get_pms_loader
from .vds_decoder import decode_vds

# (valve_type_code, spec_code) -> end_connection_code
_end_conn_map: dict[tuple[str, str], str] | None = None


def _build_end_conn_map() -> dict[tuple[str, str], str]:
    loader = get_pms_loader()
    m: dict[tuple[str, str], set[str]] = {}
    for code in loader.spec_codes:
        spec = loader.get_spec(code)
        if spec is None:
            continue
        for va in spec.valve_assignments or []:
            for vds in va.get("vds_codes") or []:
                try:
                    decoded = decode_vds(vds)
                except ValueError:
                    continue
                vt = decoded.valve_type.value
                ec = decoded.end_connection.value
                sp = decoded.piping_class.upper()
                m.setdefault((vt, sp), set()).add(ec)

    # Collapse to single value; if PMS ever shows ambiguity, keep the first
    # deterministically so behavior stays predictable.
    return {k: sorted(v)[0] for k, v in m.items() if v}


def get_end_conn(valve_type: str, spec: str) -> str | None:
    """Return the PMS-derived end-connection code for a (valve_type, spec).

    Returns None if the pair is not present in PMS — caller should fall back
    to the legacy "any end connection allowed" behavior.
    """
    global _end_conn_map
    if _end_conn_map is None:
        _end_conn_map = _build_end_conn_map()
    return _end_conn_map.get((valve_type.upper().strip(), spec.upper().strip()))


def reset_cache() -> None:
    """Test hook — force the next call to rebuild from PmsLoader."""
    global _end_conn_map
    _end_conn_map = None
