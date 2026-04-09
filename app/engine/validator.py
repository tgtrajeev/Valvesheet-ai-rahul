"""VDS combination validation against FPSO Albacora PMS rules.

Rules sourced from vds_rules.yaml and vdsParser.ts.
"""

import re
from ..models.schemas import ValidationResult, Suggestion

# Valid seat codes per valve type (Section 4, CLAUDE.md / vdsParser.ts)
VALID_SEATS_BY_TYPE: dict[str, list[str]] = {
    "GA": ["M"],
    "GL": ["M"],
    "CH": ["M"],
    "DB": ["M"],
    "NE": ["T", "P", "M"],
    "BF": ["T", "P", "M"],
    "BL": ["T", "P", "M"],
    "BS": ["T", "P", "M"],
}

# Valid designs per valve type
VALID_DESIGNS_BY_TYPE: dict[str, list[str]] = {
    "BL": ["R", "F", "M"], "BS": ["R", "F", "M"],
    "BF": ["W", "T", "P"], "GA": ["Y", "W", "S"],
    "GL": ["Y"], "CH": ["P", "S", "D", "W"],
    "DB": ["P", "M"], "NE": ["I", "A"],
}

# Complete FPSO Albacora PMS spec whitelist
VALID_SPEC_CODES = {
    # CS non-NACE
    "A1", "B1", "D1", "E1", "F1", "G1", "A2",
    # CS NACE
    "A1N", "B1N", "D1N", "E1N", "F1N", "G1N",
    "A2N", "B2N", "D2N", "E2N", "F2N", "G2N",
    # LTCS NACE
    "A1LN", "B1LN", "D1LN", "E1LN", "F1LN", "G1LN",
    "A2LN", "B2LN", "D2LN", "E2LN", "F2LN", "G2LN",
    # CS Galvanized
    "A3", "A4", "B4", "D4", "A5", "A6",
    # SS316L
    "A10", "B10", "D10", "E10", "F10", "G10",
    "A10N", "B10N", "D10N", "E10N", "F10N", "G10N",
    # DSS NACE
    "A20N", "B20N", "D20N", "E20N", "F20N", "G20N",
    # SDSS
    "A25", "G25",
    "A25N", "B25N", "D25N", "E25N", "F25N", "G25N",
    # Non-metallic / special
    "A30", "A31", "A40", "A41", "A42",
    # Tubing
    "T50A", "T50B", "T50C", "T60A", "T60B", "T60C",
}

NON_METALLIC_SPECS = {"A30", "A31", "A40", "A41", "A42"}

VALVE_TYPE_NAMES = {
    "BL": "Ball Valve", "BF": "Butterfly Valve", "GA": "Gate Valve",
    "GL": "Globe Valve", "CH": "Check Valve", "DB": "Double Block & Bleed",
    "NE": "Needle Valve", "BS": "Ball Valve (SDSS)",
}

SEAT_NAMES = {"T": "PTFE", "P": "PEEK", "M": "Metal"}


def end_conn_for_spec(spec: str) -> list[str]:
    """Return all valid end connection codes — any end type can be used with any spec."""
    return ["R", "J", "F", "T", "H", "JT"]


def validate_combination(
    valve_type: str,
    seat: str,
    spec: str,
    end_conn: str | None = None,
    bore: str | None = None,
    design: str | None = None,
) -> ValidationResult:
    """Validate a VDS combination against FPSO Albacora PMS rules.

    Returns ValidationResult with errors, warnings, and fix suggestions.
    """
    errors: list[str] = []
    warnings: list[str] = []
    suggestions: list[Suggestion] = []

    vt = valve_type.upper().strip()
    st = seat.upper().strip()
    sp = spec.upper().strip()

    # 1. Valve type exists
    if vt not in VALID_SEATS_BY_TYPE:
        errors.append(f"Unknown valve type '{vt}'. Valid: {', '.join(VALID_SEATS_BY_TYPE.keys())}")
        return ValidationResult(is_valid=False, errors=errors)

    # 2. Seat valid for valve type
    valid_seats = VALID_SEATS_BY_TYPE[vt]
    if st not in valid_seats:
        seat_labels = [f"{s} ({SEAT_NAMES[s]})" for s in valid_seats]
        errors.append(
            f"Seat '{st}' ({SEAT_NAMES.get(st, '?')}) is not valid for {VALVE_TYPE_NAMES[vt]}. "
            f"Valid seats: {', '.join(seat_labels)}"
        )
        for s in valid_seats:
            suggestions.append(Suggestion(
                type="fix",
                title=f"Use {SEAT_NAMES[s]} seat",
                description=f"Change seat to {s} ({SEAT_NAMES[s]}) which is valid for {VALVE_TYPE_NAMES[vt]}",
                action={"seat": s},
            ))

    # 3. Piping spec is valid
    if sp not in VALID_SPEC_CODES:
        errors.append(
            f"Piping spec '{sp}' is not a valid FPSO Albacora PMS code. "
            f"Examples: A1, B1N, D1LN, A10, A20N, T50A"
        )

    # 4. NE spec — needle valves can work with any valid piping class

    # 5. End connection compatibility
    if end_conn and sp in VALID_SPEC_CODES:
        ec = end_conn.upper().strip()
        valid_ends = end_conn_for_spec(sp)
        if ec not in valid_ends:
            end_names = {"R": "RF", "J": "RTJ", "F": "FF", "JT": "RTJ+NPT"}
            errors.append(
                f"End connection '{ec}' ({end_names.get(ec, ec)}) is incompatible with spec '{sp}'. "
                f"Spec {sp} requires: {', '.join(end_names.get(e, e) for e in valid_ends)}"
            )

    # 6. Design compatibility
    if bore and vt in ("BL", "BS"):
        b = bore.upper().strip()
        if b not in ("R", "F", "M"):
            errors.append(f"Invalid bore '{b}' for {VALVE_TYPE_NAMES[vt]}. Valid: R (Reduced), F (Full), M (Metal)")

    if design and vt == "NE":
        d = design.upper().strip()
        if d not in ("I", "A"):
            errors.append(f"Invalid design '{d}' for Needle Valve. Valid: I (Inline), A (Angle)")

    # Warnings
    if "N" in sp and st != "M":
        warnings.append(f"NACE spec '{sp}' — ensure all materials comply with NACE MR-01-75 / ISO 15156")
    if "L" in sp:
        warnings.append(f"Low-temperature spec '{sp}' — LTCS materials required, impact tested to -46C min")

    is_valid = len(errors) == 0
    return ValidationResult(
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        suggestions=suggestions,
    )
