"""VDS combination validation against FPSO Albacora PMS rules + MY-K-20-PI-SP-0002.

Two-phase validation:
  Phase 1 (validate_combination): Pre-generation checks — valve type, seat, spec, end conn
  Phase 2 (validate_datasheet):   Post-generation size-dependent checks — mounting, gearbox, body form, wedge
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

# ============================================================================
# PRESSURE CLASS MAPPING
# ============================================================================

PRESSURE_CLASS_NUM = {"A": 150, "B": 300, "D": 600, "E": 900, "F": 1500, "G": 2500}

# ============================================================================
# MY-K-20-PI-SP-0002 ENGINEERING RULES
# ============================================================================

# Rule A1: Floating vs Trunnion size thresholds (inches)
BALL_MOUNTING_THRESHOLDS = {
    150: {"max_floating": 8, "min_trunnion": 10},
    300: {"max_floating": 4, "min_trunnion": 6},
    600: {"max_floating": 1.5, "min_trunnion": 2},
    900: {"max_floating": 0, "min_trunnion": 0},    # all trunnion
    1500: {"max_floating": 0, "min_trunnion": 0},
    2500: {"max_floating": 0, "min_trunnion": 0},
}

# Rule A4: Seat sealant injection threshold (minimum size in inches)
SEALANT_INJECTION_THRESHOLDS = {150: 10, 300: 6, 600: 2, 900: 0, 1500: 0, 2500: 0}

# Rule 26: Gearbox operation thresholds (minimum size in inches requiring gearbox)
GEARBOX_THRESHOLDS: dict[str, dict[int, float]] = {
    "BL": {150: 6, 300: 6, 600: 4, 900: 3, 1500: 3, 2500: 3},
    "BS": {150: 6, 300: 6, 600: 4, 900: 3, 1500: 3, 2500: 3},
    "BF": {150: 6, 300: 6},
    "GA": {150: 14, 300: 14, 600: 12, 900: 6, 1500: 3, 2500: 3},
    "GL": {150: 10, 300: 8, 600: 6, 900: 6, 1500: 3, 2500: 3},
}

# Rule 31: RTJ required for high pressure classes
RTJ_REQUIRED_CLASSES = {900, 1500, 2500}

# Rule 39: Extended stem lengths (max_size_inches, extension_mm)
EXTENDED_STEM_LENGTHS = [
    (1.5, 75),   # <=1.5" -> 75mm
    (6, 100),    # 2"-6" -> 100mm
    (999, 150),  # >=8" -> 150mm
]

# HC (hydrocarbon) spec indicators
_HC_SERVICE_KEYWORDS = {"HC", "hydrocarbon", "Glycol", "Flare", "Crude", "Corrosive HC"}
_HC_SPEC_SUFFIXES = {"N", "LN"}   # NACE specs are typically HC service


def _is_hc_service(spec: str) -> bool:
    """Determine if a piping spec code is for hydrocarbon / hazardous service."""
    sp = spec.upper().strip()
    # NACE specs (ending in N or LN) are HC service
    if sp.endswith("N") or sp.endswith("LN"):
        return True
    # A2 is crude oil
    if sp == "A2":
        return True
    # Number-2 variants are corrosive HC
    m = re.match(r"[A-G]2", sp)
    if m:
        return True
    return False


def _pressure_class_from_spec(spec: str) -> int | None:
    """Extract ASME pressure class number from spec code."""
    if not spec:
        return None
    letter = spec[0].upper()
    return PRESSURE_CLASS_NUM.get(letter)


def parse_size_inches(size_str: str | None) -> float | None:
    """Parse size string like '1/2', '1-1/2', '8\"', '10' into float inches."""
    if not size_str:
        return None
    s = str(size_str).strip().replace('"', '').replace("'", '').replace("inch", "").replace("NPS", "").strip()
    # Handle fractional: 1-1/2 -> 1.5
    m = re.match(r'^(\d+)-(\d+)/(\d+)$', s)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    m = re.match(r'^(\d+)/(\d+)$', s)
    if m:
        return int(m.group(1)) / int(m.group(2))
    try:
        return float(s)
    except ValueError:
        return None


def end_conn_for_spec(spec: str) -> list[str]:
    """Return all valid end connection codes — any end type can be used with any spec."""
    return ["R", "J", "F", "T", "H", "JT"]


# ============================================================================
# PHASE 1: PRE-GENERATION VALIDATION
# ============================================================================

def validate_combination(
    valve_type: str,
    seat: str,
    spec: str,
    end_conn: str | None = None,
    bore: str | None = None,
    design: str | None = None,
    size_inches: float | None = None,
    service: str | None = None,
    pressure_class: int | None = None,
) -> ValidationResult:
    """Validate a VDS combination against FPSO Albacora PMS rules + spec MY-K-20-PI-SP-0002.

    Returns ValidationResult with errors, warnings, and fix suggestions.
    """
    errors: list[str] = []
    warnings: list[str] = []
    suggestions: list[Suggestion] = []

    vt = valve_type.upper().strip()
    st = seat.upper().strip()
    sp = spec.upper().strip()
    ec = (end_conn or "").upper().strip() if end_conn else None

    # Resolve pressure class from spec if not provided
    if pressure_class is None:
        pressure_class = _pressure_class_from_spec(sp)

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

    # 4. End connection compatibility
    if ec and sp in VALID_SPEC_CODES:
        valid_ends = end_conn_for_spec(sp)
        if ec not in valid_ends:
            end_names = {"R": "RF", "J": "RTJ", "F": "FF", "JT": "RTJ+NPT"}
            errors.append(
                f"End connection '{ec}' ({end_names.get(ec, ec)}) is incompatible with spec '{sp}'. "
                f"Spec {sp} requires: {', '.join(end_names.get(e, e) for e in valid_ends)}"
            )

    # 5. Design compatibility
    if bore and vt in ("BL", "BS"):
        b = bore.upper().strip()
        if b not in ("R", "F", "M"):
            errors.append(f"Invalid bore '{b}' for {VALVE_TYPE_NAMES[vt]}. Valid: R (Reduced), F (Full), M (Metal)")

    if design and vt == "NE":
        d = design.upper().strip()
        if d not in ("I", "A"):
            errors.append(f"Invalid design '{d}' for Needle Valve. Valid: I (Inline), A (Angle)")

    # ============================================================================
    # MY-K-20-PI-SP-0002 SPEC RULES
    # ============================================================================

    is_hc = _is_hc_service(sp)

    # Rule 31: RTJ required for CL 900+
    if pressure_class and pressure_class >= 900 and ec and ec not in ("J", "JT"):
        errors.append(
            f"Class {pressure_class} requires RTJ end connection per MY-K-20-PI-SP-0002 Clause 11. "
            f"Current end connection '{ec}' is not permitted for classes 900-2500."
        )
        suggestions.append(Suggestion(
            type="fix",
            title="Use RTJ end connection",
            description=f"Change end connection to J (RTJ) for class {pressure_class}",
            action={"end_conn": "J"},
        ))

    # Rule 33: Threaded ends rejected in hazardous/HC service
    if ec == "T" and is_hc:
        errors.append(
            f"Threaded (NPT) end connections are not permitted in hydrocarbon/hazardous service "
            f"(spec {sp}) per MY-K-20-PI-SP-0002 Clause 15."
        )
        suggestions.append(Suggestion(
            type="fix",
            title="Use flanged RF or RTJ",
            description="Change end connection to R (RF) or J (RTJ) for HC service",
            action={"end_conn": "R"},
        ))

    # Rule 12: Butterfly restricted to clean non-HC service
    if vt == "BF" and is_hc:
        errors.append(
            f"Butterfly valves are restricted to clean non-hydrocarbon service per MY-K-20-PI-SP-0002 Clause 6. "
            f"Spec '{sp}' is for hydrocarbon service."
        )
        suggestions.append(Suggestion(
            type="fix",
            title="Use Ball Valve instead",
            description="Ball valves are suitable for HC service. Change valve type to BL.",
            action={"valve_type": "BL"},
        ))

    # Rule 13: Wafer butterfly rejected in flammable service
    if vt == "BF" and (bore or design or "").upper() == "W" and is_hc:
        warnings.append(
            "Wafer-type butterfly valves are rejected in flammable/combustible service per MY-K-20-PI-SP-0002. "
            "Must use solid lug type with threaded lugs."
        )

    # Rule 9: Gate/Globe restricted to clean non-HC (except HC >= 900# <= 1.5")
    if vt in ("GA", "GL") and is_hc:
        exception_applies = False
        if pressure_class and pressure_class >= 900 and size_inches is not None and size_inches <= 1.5:
            exception_applies = True
        if not exception_applies:
            if size_inches is not None:
                warnings.append(
                    f"{VALVE_TYPE_NAMES[vt]} is restricted to clean non-hydrocarbon service "
                    f"per MY-K-20-PI-SP-0002 Clause 6. Exception: HC service only for class >= 900 and size <= 1.5\". "
                    f"Current: class {pressure_class}, size {size_inches}\"."
                )
            else:
                warnings.append(
                    f"{VALVE_TYPE_NAMES[vt]} is restricted to clean non-hydrocarbon service "
                    f"per MY-K-20-PI-SP-0002 Clause 6. Exception: HC service for class >= 900 and size <= 1.5\". "
                    f"Verify size meets exception criteria."
                )

    # Rule 17: Body must be forged for DN <= 40 (NPS 1.5")
    if size_inches is not None and size_inches <= 1.5:
        warnings.append(
            f"Size {size_inches}\" (DN <= 40): body MUST be forged per MY-K-20-PI-SP-0002 Clause 4. "
            "Cast body is not permitted for this size."
        )

    # Needle valve size limit
    if vt == "NE" and size_inches is not None and size_inches > 2:
        errors.append(
            f"Needle valve size {size_inches}\" exceeds maximum 2\" per BS EN ISO 15761. "
            "Needle valves are for instrument connections only (typically 1/2\" to 2\")."
        )

    # Butterfly minimum size
    if vt == "BF" and size_inches is not None and size_inches < 2:
        warnings.append(
            f"Butterfly valve at {size_inches}\" is uncommon. Minimum recommended size is 2\"."
        )

    # Ball valve mounting thresholds (when size is known)
    if vt in ("BL", "BS") and size_inches is not None and pressure_class:
        thresholds = BALL_MOUNTING_THRESHOLDS.get(pressure_class)
        if thresholds:
            max_float = thresholds["max_floating"]
            if max_float == 0:
                warnings.append(
                    f"Class {pressure_class}: ALL ball valves must be trunnion mounted "
                    f"per MY-K-20-PI-SP-0002 Clause 5."
                )
            elif size_inches <= max_float:
                warnings.append(
                    f"Class {pressure_class}, size {size_inches}\": floating ball mounting applies "
                    f"(floating <= {max_float}\", trunnion >= {thresholds['min_trunnion']}\")."
                )
            else:
                warnings.append(
                    f"Class {pressure_class}, size {size_inches}\": trunnion mounting REQUIRED "
                    f"(floating <= {max_float}\", trunnion >= {thresholds['min_trunnion']}\"). "
                    "Requires: DBB capability, spring-loaded seats, body vent/drain, sealant injection."
                )

    # Gearbox threshold (when size is known)
    if size_inches is not None and pressure_class and vt in GEARBOX_THRESHOLDS:
        gear_table = GEARBOX_THRESHOLDS[vt]
        gear_min = gear_table.get(pressure_class)
        if gear_min is not None and size_inches >= gear_min:
            warnings.append(
                f"{VALVE_TYPE_NAMES[vt]} at {size_inches}\", class {pressure_class}: "
                f"gear operation REQUIRED (threshold: >= {gear_min}\") per MY-K-20-PI-SP-0002 Clause 9."
            )

    # NACE / sour service warnings
    if "N" in sp and st != "M":
        warnings.append(f"NACE spec '{sp}' — ensure all materials comply with NACE MR-01-75 / ISO 15156")
    if "L" in sp:
        warnings.append(f"Low-temperature spec '{sp}' — LTCS materials required, impact tested to -46°C min")

    # Soft seat temperature limit
    if st in ("T", "P"):
        warnings.append(
            f"{SEAT_NAMES[st]} seat: maximum service temperature 200°C. "
            "Verify design temperature does not exceed this limit."
        )

    # Antistatic device for soft-seated valves
    if st in ("T", "P") and vt in ("BL", "BS", "BF"):
        warnings.append(
            f"Antistatic device REQUIRED for soft-seated {VALVE_TYPE_NAMES[vt]} "
            "per MY-K-20-PI-SP-0002 Clause 4."
        )

    # Fire test required for non-metallic seats/seals
    if st in ("T", "P"):
        warnings.append(
            "Fire test certification required (API 607 / BS EN ISO 10497) for valves with "
            "non-metallic seats/seals per MY-K-20-PI-SP-0002 Clause 15."
        )

    is_valid = len(errors) == 0
    return ValidationResult(
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        suggestions=suggestions,
    )


# ============================================================================
# PHASE 2: POST-GENERATION SIZE-DEPENDENT VALIDATION
# ============================================================================

def validate_datasheet(
    data: dict[str, str],
    valve_type: str,
    design: str,
    seat: str,
    spec: str,
    size_inches: float | None = None,
) -> ValidationResult:
    """Validate a generated datasheet against MY-K-20-PI-SP-0002 size-dependent rules.

    Called AFTER rule_engine.generate_datasheet() to add Phase 2 warnings.
    """
    errors: list[str] = []
    warnings: list[str] = []

    vt = valve_type.upper()
    pressure_class = _pressure_class_from_spec(spec)
    is_hc = _is_hc_service(spec)

    # Rule 8: Gate valve wedge type
    if vt == "GA" and size_inches is not None:
        expected = "Solid" if size_inches <= 1.5 else "Flexible"
        actual_wedge = data.get("wedge_construction", "")
        if expected.lower() not in actual_wedge.lower():
            warnings.append(
                f"Gate valve wedge: size {size_inches}\" should use {expected} wedge "
                f"per MY-K-20-PI-SP-0002 Clause 6 (Solid <= 1.5\", Flexible > 1.5\")."
            )

    # Rule 10: Body seat — renewable vs integral
    if vt in ("GA", "GL", "CH"):
        body_seat = data.get("seat_construction", "")
        if "renewable" not in body_seat.lower() and "integral" not in body_seat.lower():
            warnings.append(
                f"Body seat type (renewable/integral) should be specified per MY-K-20-PI-SP-0002 Table 2."
            )

    # Rule 11: Backseat required for GA, GL, NE
    if vt in ("GA", "GL", "NE"):
        stem = data.get("stem_construction", "")
        if "back seat" not in stem.lower() and "backseat" not in stem.lower():
            warnings.append(
                f"Backseat REQUIRED for {VALVE_TYPE_NAMES.get(vt, vt)} "
                "per MY-K-20-PI-SP-0002 Clause 6."
            )

    # Rule 14: Blowout-proof stem required on ALL valves
    stem = data.get("stem_construction", "")
    if vt not in ("CH",) and "blowout" not in stem.lower() and "blow-out" not in stem.lower():
        warnings.append(
            "Blowout-proof stem REQUIRED on all valves per MY-K-20-PI-SP-0002 Clause 4. "
            "Stem retention by packing gland alone is not acceptable."
        )

    # Rule 15: DBB body construction
    if vt == "DB" and size_inches is not None:
        body = data.get("body_construction", "")
        if size_inches <= 2 and "one-piece" not in body.lower() and "one piece" not in body.lower():
            warnings.append(
                f"DBB body for {size_inches}\" should be one-piece forged per MY-K-20-PI-SP-0002 Clause 8."
            )
        elif size_inches > 2 and "three-piece" not in body.lower() and "three piece" not in body.lower():
            warnings.append(
                f"DBB body for {size_inches}\" should be three-piece bolted per MY-K-20-PI-SP-0002 Clause 8."
            )

    # Rule 29: Locking device required (all except check)
    if vt != "CH":
        locks = data.get("locks", "")
        if not locks:
            warnings.append(
                "Locking device (padlock facility) REQUIRED per MY-K-20-PI-SP-0002 Clause 9."
            )

    # Rule 30: Position indicator for quarter-turn and gear-operated
    if vt in ("BL", "BS", "BF", "DB"):
        operation = data.get("operation", "")
        if "position indicator" not in operation.lower():
            warnings.append(
                f"Position indicator REQUIRED for quarter-turn {VALVE_TYPE_NAMES.get(vt, vt)} "
                "per MY-K-20-PI-SP-0002 Clause 9."
            )

    # Rule 38: Lifting lug if weight >= 25 kg
    warnings.append(
        "Lifting lug required if valve weight >= 25 kg (design load 2x lift weight) "
        "per MY-K-20-PI-SP-0002 Clause 14."
    )

    # Rule 40: Auxiliary connections in HC must be flanged
    if is_hc:
        warnings.append(
            "Auxiliary body connections in HC service must be flanged welded construction "
            "(no socket weld or seal-welded threads) per MY-K-20-PI-SP-0002 Clause 12."
        )

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )
