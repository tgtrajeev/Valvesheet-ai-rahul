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
DESIGN_NAMES = {
    "I": "Inline", "A": "Angle",
    "Y": "Screw & Yoke", "W": "Wafer", "S": "Swing",
    "P": "Piston", "D": "Dual Plate", "T": "Triple Offset",
}

ALL_VALVE_TYPES = ["BL", "BF", "GA", "GL", "CH", "DB", "NE"]
ALL_SEATS = ["T", "P", "M"]
ALL_BORES = ["R", "F"]

# Valid designs per valve type (from VDS code structure)
DESIGNS_BY_TYPE: dict[str, list[str]] = {
    "BL": ["R", "F"],       # Bore: Reduced / Full
    "BS": ["R", "F"],       # Bore: Reduced / Full
    "BF": ["W", "T"],       # Wafer / Triple Offset
    "GA": ["Y", "S"],       # Screw & Yoke / Swing
    "GL": ["Y"],            # Screw & Yoke
    "CH": ["P", "S", "D", "W"],  # Piston / Swing / Dual Plate / Wafer
    "DB": ["P"],            # Piston
    "NE": ["I", "A"],       # Inline / Angle
}

# Default design when not specified
DEFAULT_DESIGN: dict[str, str] = {
    "BL": "R", "BS": "R",   # Reduced Bore
    "BF": "W",              # Wafer
    "GA": "Y",              # Screw & Yoke
    "GL": "Y",              # Screw & Yoke
    "CH": "P",              # Piston
    "DB": "P",              # Piston
    "NE": "I",              # Inline
}


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

    @property
    def design_or_bore(self) -> str:
        """Return the design/bore character used in the VDS code."""
        return self.bore or self.design or ""


def build_vds_code(
    valve_type: str, seat: str, spec: str, end_connection: str,
    bore: str = "", design: str = "",
) -> str:
    """Assemble a VDS code string from components.

    Format: ValveType + Bore/Design + Seat + Spec + EndConnection
    Every valve type gets a design/bore character per VDS code structure.
    """
    vt = valve_type.upper()
    code = vt

    # Bore/Design character — every valve type includes one
    if vt in ("BL", "BS"):
        code += (bore or DEFAULT_DESIGN.get(vt, "R")).upper()
    else:
        code += (design or DEFAULT_DESIGN.get(vt, "")).upper()

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

    VDS code structure: ValveType + Bore/Design + Seat + Spec + EndConnection
    Every valve type includes a design/bore character per VDS code rules.
    End connection is always rule-derived from spec.
    """
    vt_list = [v.upper() for v in (valve_types or ALL_VALVE_TYPES)]
    seat_list = [s.upper() for s in (seats or ALL_SEATS)]
    spec_list = [s.upper().strip() for s in (specs or [])]
    bore_list = [b.upper() for b in (bores or ALL_BORES)]
    design_list = [d.upper() for d in (designs or [])] if designs else []

    if not spec_list:
        return []

    result: list[VdsCombo] = []

    for spec in spec_list:
        if spec not in VALID_SPEC_CODES:
            continue

        for vt in vt_list:
            # End connection is fully determined by (valve_type, spec) per PMS rule.
            rule_ends = end_conn_for_spec(spec, vt)
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

            # Get valid designs for this valve type
            vt_designs = DESIGNS_BY_TYPE.get(vt, [])

            if vt in ("BL", "BS"):
                # Ball valves use bore (R/F) as the design character
                active_bores = [b for b in bore_list if b in vt_designs] or vt_designs
                for b in active_bores:
                    for s in rule_seats:
                        for e in rule_ends:
                            result.append(VdsCombo(
                                valve_type=vt, bore=b, seat=s,
                                spec=spec, end_connection=e,
                            ))
            else:
                # All other types use design character
                # Filter to user-selected designs if provided, else use all valid
                active_designs = (
                    [d for d in design_list if d in vt_designs]
                    if design_list else vt_designs
                ) or [DEFAULT_DESIGN.get(vt, "")]
                for d in active_designs:
                    for s in rule_seats:
                        for e in rule_ends:
                            result.append(VdsCombo(
                                valve_type=vt, design=d, seat=s,
                                spec=spec, end_connection=e,
                            ))

    return result
