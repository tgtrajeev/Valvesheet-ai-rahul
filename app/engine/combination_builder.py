"""Generate valid VDS code combinations from partial selections.

Ported from SPE-Valvesheet-Frontend-Staging/src/lib/vdsParser.ts generateCombinations().
"""

import re
from dataclasses import dataclass
from .validator import (
    VALID_SEATS_BY_TYPE,
    VALID_SPEC_CODES,
    VALVE_TYPE_NAMES,
    SEAT_NAMES,
    end_conn_for_spec,
)

END_CONN_NAMES = {"R": "RF", "J": "RTJ", "F": "FF", "JT": "RTJ+NPT", "H": "HUB", "T": "NPT"}
BORE_NAMES = {"R": "Reduced Bore", "F": "Full Bore"}
DESIGN_NAMES = {"I": "Inline", "A": "Angle"}

ALL_VALVE_TYPES = ["BL", "BF", "GA", "GL", "CH", "DB", "NE"]
ALL_SEATS = ["T", "P", "M"]
ALL_BORES = ["R", "F"]
ALL_DESIGNS = ["I", "A"]


@dataclass
class VdsCombo:
    valve_type: str
    seat: str
    spec: str
    end_connection: str
    bore: str = ""
    design: str = ""

    @property
    def vds_code(self) -> str:
        return build_vds_code(self.valve_type, self.seat, self.spec,
                              self.end_connection, self.bore, self.design)

    @property
    def description(self) -> str:
        parts = [VALVE_TYPE_NAMES.get(self.valve_type, self.valve_type)]
        if self.bore:
            parts.append(BORE_NAMES.get(self.bore, self.bore))
        if self.design:
            parts.append(DESIGN_NAMES.get(self.design, self.design))
        parts.append(f"{SEAT_NAMES.get(self.seat, self.seat)} seat")
        parts.append(f"Spec {self.spec}")
        parts.append(END_CONN_NAMES.get(self.end_connection, self.end_connection))
        return " / ".join(parts)


def build_vds_code(
    valve_type: str, seat: str, spec: str, end_connection: str,
    bore: str = "", design: str = "",
) -> str:
    """Assemble a VDS code string from components."""
    code = valve_type.upper()

    if valve_type.upper() in ("BL", "BS"):
        code += (bore or "R").upper()
    elif valve_type.upper() == "NE":
        code += (design or "I").upper()
    # For other types we skip explicit design in code for now
    # (GA→Y, GL→Y, CH→P/S/D, BF→W are typically implicit)

    code += seat.upper()
    code += spec.upper()
    code += end_connection.upper()
    return code


def generate_combinations(
    valve_types: list[str] | None = None,
    seats: list[str] | None = None,
    specs: list[str] | None = None,
    end_connections: list[str] | None = None,
    bores: list[str] | None = None,
    designs: list[str] | None = None,
) -> list[VdsCombo]:
    """Generate all valid VDS combinations from multi-selected options.

    End connection is always rule-derived from spec — the end_connections param
    is only used as fallback when spec is absent.
    """
    vt_list = [v.upper() for v in (valve_types or ALL_VALVE_TYPES)]
    seat_list = [s.upper() for s in (seats or ALL_SEATS)]
    spec_list = [s.upper().strip() for s in (specs or [])]
    bore_list = [b.upper() for b in (bores or ALL_BORES)]
    design_list = [d.upper() for d in (designs or ALL_DESIGNS)]

    if not spec_list:
        return []

    result: list[VdsCombo] = []

    for spec in spec_list:
        if spec not in VALID_SPEC_CODES:
            continue

        # End connection fully determined by spec prefix
        rule_ends = end_conn_for_spec(spec)

        for vt in vt_list:
            # Filter seats to those valid for this valve type
            rule_seats = [s for s in (VALID_SEATS_BY_TYPE.get(vt, ALL_SEATS)) if s in seat_list]
            if not rule_seats:
                continue

            # NE only valid with E/F/G or tubing specs
            if vt == "NE":
                prefix = spec[0] if spec else ""
                is_high = prefix in ("E", "F", "G")
                is_tubing = bool(re.match(r"^T\d", spec))
                if not is_high and not is_tubing:
                    continue

            if vt in ("BL", "BS"):
                for b in bore_list:
                    for s in rule_seats:
                        for e in rule_ends:
                            result.append(VdsCombo(
                                valve_type=vt, bore=b, seat=s,
                                spec=spec, end_connection=e,
                            ))
            elif vt == "NE":
                for d in design_list:
                    for s in rule_seats:
                        for e in rule_ends:
                            result.append(VdsCombo(
                                valve_type=vt, design=d, seat=s,
                                spec=spec, end_connection=e,
                            ))
            else:
                for s in rule_seats:
                    for e in rule_ends:
                        result.append(VdsCombo(
                            valve_type=vt, seat=s,
                            spec=spec, end_connection=e,
                        ))

    return result
