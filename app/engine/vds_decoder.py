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


def _display_vds_for_sheet(original_input: str, canonical_vds: str) -> str:
    """Datasheet label: keep ``VDS-`` prefix when the user included it."""
    head = (original_input or "").strip().upper()
    c = canonical_vds.upper().strip()
    if head.startswith("VDS-"):
        return f"VDS-{c}"
    return c


def decode_vds(vds: str, project_id: str | None = None) -> DecodedVDS:
    """Parse a VDS string into a DecodedVDS model.

    Supports:
    - New format: BLRTA1R  → BL + R(bore) + T(seat) + A1 + R(end)
    - Legacy 3-char: BSFA1R → BSF + A1 + R(end)
    - Legacy 2-char: BSA1R  → BS  + A1 + R(end)

    The set of recognized valve-type prefixes (and per-prefix design lists)
    comes from `vds_config.py`. A project can supply its own prefix mapping
    (e.g. "BV" → ball valve) by adding `app/data/projects/<id>/vds_config.json`.
    """
    original_input = vds
    from .vds_config import get_vds_config
    cfg = get_vds_config(project_id)
    prefix_map     = cfg["valve_type_prefixes"]
    seat_chars     = set(cfg["seat_chars"])
    legacy_3char   = cfg["legacy_3char_prefixes"]
    legacy_2char   = cfg["legacy_2char_prefixes"]

    raw = vds.upper().strip()
    if raw.startswith("VDS-"):
        raw = raw[4:].strip()
    if len(raw) < 5:
        raise ValueError(f"VDS code too short: '{raw}'")

    valve_type_str = ""
    design = ""
    seat_char = ""
    rest = ""

    prefix2 = raw[:2]
    prefix3 = raw[:3]

    if prefix2 in prefix_map:
        # ── New format ──
        spec = prefix_map[prefix2]
        valve_type_str = spec["engine_type"]   # canonical type used by the engine
        valid_designs = set(spec.get("designs", []))
        default_design = spec.get("default_design", "")
        pos = 2

        # Position 2: design / bore character
        if pos < len(raw) and raw[pos] in valid_designs:
            design = raw[pos]; pos += 1
        else:
            design = default_design

        # Position 3: seat character (T/P/M)
        if pos < len(raw) and raw[pos] in seat_chars:
            # Disambiguate: T followed by digit is a piping class (T50A), not a seat
            if raw[pos] == "T" and pos + 1 < len(raw) and raw[pos + 1].isdigit():
                seat_char = ""
            else:
                seat_char = raw[pos]; pos += 1

        rest = raw[pos:]

    elif prefix3 in legacy_3char:
        valve_type_str, design = legacy_3char[prefix3]
        rest = raw[3:]

    elif prefix2 in legacy_2char:
        valve_type_str, design = legacy_2char[prefix2]
        rest = raw[2:]

    else:
        raise ValueError(f"Unrecognized VDS prefix: '{raw[:3]}'")

    # ── Parse piping_class + end_connection from `rest` ──
    # End connections come from the project config — 2-char (e.g. JT) tried first.
    end_chars        = set(cfg["end_chars"])
    double_char_ends = list(cfg.get("double_char_ends", []))
    piping_class = ""
    end_conn_str = ""

    matched_double = False
    for de in double_char_ends:
        if rest.endswith(de):
            end_conn_str = de
            piping_class = rest[: -len(de)]
            matched_double = True
            break
    if not matched_double:
        if len(rest) >= 1:
            last = rest[-1]
            if last in end_chars:
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
        display_vds=_display_vds_for_sheet(original_input, raw),
        valve_type=valve_type,
        design=design,
        seat_type=seat_type,
        piping_class=piping_class,
        end_connection=end_connection,
        is_nace=is_nace,
        is_low_temp=is_low_temp,
    )
