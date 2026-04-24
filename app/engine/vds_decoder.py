"""Decode a VDS code string into a structured DecodedVDS object.

Handles both the new 5-part format and legacy 3-char/2-char prefixes.
Ported from SPE-Valvesheet-AI-Staging/ml/data_preparation.py parse_vds_features().
"""

import re
from ..models.vds import DecodedVDS, ValveType, SeatType, EndConnection

# New-format 2-char valve type prefixes
_NEW_PREFIXES = {"BL", "BF", "GA", "GL", "CH", "DB", "NE", "BS"}

# Legacy 3-char → (valve_type, default_design)
_LEGACY_3CHAR = {
    "BSF": ("BL", "F"), "BSR": ("BL", "R"),
    "GAW": ("GA", "W"), "GLS": ("GL", "Y"),
    "CHP": ("CH", "P"), "CSW": ("CH", "S"), "CDP": ("CH", "D"),
    "BFD": ("BF", "W"), "DSR": ("DB", "R"), "DSF": ("DB", "F"),
    "NEE": ("NE", "I"),
}

# Legacy 2-char → (valve_type, default_design)
_LEGACY_2CHAR = {
    "BS": ("BL", "F"), "GS": ("GA", "Y"), "CS": ("CH", "S"), "PS": ("GA", "Y"),
}

# Designs that function as bore indicators for ball/DBB valves
_BALL_DESIGNS = {"R", "F", "M"}
_NE_DESIGNS = {"I", "A"}


def decode_vds(vds: str) -> DecodedVDS:
    """Parse a VDS string into a DecodedVDS model.

    Supports:
    - New format: BLRTA1R  → BL + R(bore) + T(seat) + A1 + R(end)
    - Legacy 3-char: BSFA1R → BSF + A1 + R(end)
    - Legacy 2-char: BSA1R  → BS  + A1 + R(end)
    """
    raw = vds.upper().strip()
    if len(raw) < 5:
        raise ValueError(f"VDS code too short: '{raw}'")

    valve_type_str = ""
    design = ""
    seat_char = ""
    rest = ""  # everything after valve_type + design + seat

    prefix2 = raw[:2]
    prefix3 = raw[:3]

    if prefix2 in _NEW_PREFIXES:
        # ── New format ──
        valve_type_str = prefix2
        pos = 2

        # Position 2: design / bore character
        if prefix2 in ("BL", "BS"):
            if raw[pos] in _BALL_DESIGNS:
                design = raw[pos]; pos += 1
            else:
                design = "R"  # default reduced bore
        elif prefix2 == "NE":
            if raw[pos] in _NE_DESIGNS:
                design = raw[pos]; pos += 1
            else:
                design = "I"  # default inline
        else:
            # GA, GL, CH, DB, BF — design char is always present in new format
            design = raw[pos]; pos += 1

        # Position 3: seat character (T/P/M)
        if pos < len(raw) and raw[pos] in ("T", "P", "M"):
            # Disambiguate: T followed by digit is a piping class (T50A), not a seat
            if raw[pos] == "T" and pos + 1 < len(raw) and raw[pos + 1].isdigit():
                seat_char = ""  # no explicit seat
            else:
                seat_char = raw[pos]; pos += 1

        rest = raw[pos:]

    elif prefix3 in _LEGACY_3CHAR:
        # ── Legacy 3-char ──
        valve_type_str, design = _LEGACY_3CHAR[prefix3]
        rest = raw[3:]

    elif prefix2 in _LEGACY_2CHAR:
        # ── Legacy 2-char ──
        valve_type_str, design = _LEGACY_2CHAR[prefix2]
        rest = raw[2:]

    else:
        raise ValueError(f"Unrecognized VDS prefix: '{raw[:3]}'")

    # ── Parse piping_class + end_connection from `rest` ──
    # End connections: JT (2-char), then single-char R/J/F/W/S/H/T
    piping_class = ""
    end_conn_str = ""

    if rest.endswith("JT"):
        end_conn_str = "JT"
        piping_class = rest[:-2]
    elif len(rest) >= 1:
        last = rest[-1]
        if last in ("R", "J", "F", "W", "S", "H", "T"):
            end_conn_str = last
            piping_class = rest[:-1]
        else:
            # No end connection found — treat entire rest as piping class, default RF
            piping_class = rest
            end_conn_str = "R"
    else:
        raise ValueError(f"Cannot parse piping class from VDS: '{raw}'")

    if not piping_class:
        raise ValueError(f"Empty piping class in VDS: '{raw}'")

    # ── Build DecodedVDS ──
    valve_type = ValveType(valve_type_str)
    seat_type = SeatType(seat_char) if seat_char else None
    end_connection = EndConnection.from_string(end_conn_str)

    is_nace = "N" in piping_class.upper()
    is_low_temp = "L" in piping_class.upper()

    return DecodedVDS(
        raw_vds=raw,
        valve_type=valve_type,
        design=design,
        seat_type=seat_type,
        piping_class=piping_class,
        end_connection=end_connection,
        is_nace=is_nace,
        is_low_temp=is_low_temp,
    )
