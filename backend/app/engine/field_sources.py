"""Field source mapping — maps each datasheet field to its data provenance.

Based on the VDS code structure and FPSO Albacora PMS rules, every field
in the output datasheet has a source that documents where the value came from.

Source types (matching the output datasheet format):
- "Selected based on VDS No"              — Derived from VDS number parsing
- "Automated based on PMS class"          — From PMS piping class data
- "As per valve standard"                 — From valve design standards (API 6D, etc.)
- "As per PMS Base material and Valve Standard" — Combined PMS + standards
- "As per Project Requirement"            — Project-specific requirement
- "need to input under data base"         — Requires manual input / DB entry
- "Calculated"                            — Computed from other values
"""

# ── Source description strings ──────────────────────────────────────────────

SRC_VDS = "Selected based on VDS No"
SRC_PMS = "Automated based on PMS class"
SRC_VALVE_STD = "As per valve standard"
SRC_PMS_AND_STD = "As per PMS Base material and Valve Standard"
SRC_PROJECT = "As per Project Requirement"
SRC_CALCULATED = "Calculated"
SRC_VDS_INDEX = "automated based on PMS class and valve standard"
SRC_INPUT = "need to input under data base"

# ── Per-field source mapping ────────────────────────────────────────────────
# Key = field name as it appears in the flat VDS index / datasheet data
# Value = source description string for the output "Source" column

FIELD_SOURCE_MAP: dict[str, str] = {
    # Header / Basic
    "vds_no":               SRC_VDS,
    "piping_class":         SRC_VDS,
    "valve_type":           SRC_VDS,
    "size_range":           SRC_PMS,
    "service":              SRC_PMS,

    # Design
    "valve_standard":       SRC_VALVE_STD,
    "pressure_class":       SRC_PMS,
    "design_pressure":      SRC_PMS,
    "corrosion_allowance":  SRC_VALVE_STD,
    "sour_service":         SRC_PMS,
    "design_code":          SRC_VALVE_STD,
    "nace_compliant":       SRC_VDS,
    "low_temperature":      SRC_VDS,
    "min_design_temp":      SRC_PMS,
    "max_design_temp":      SRC_PMS,
    "soft_seat_temp_limit": SRC_VALVE_STD,

    # Configuration
    "end_connections":      SRC_VALVE_STD,
    "face_to_face":         SRC_VALVE_STD,
    "operation":            SRC_VALVE_STD,

    # Construction
    "body_construction":    SRC_VALVE_STD,
    "ball_construction":    SRC_VALVE_STD,
    "stem_construction":    SRC_VALVE_STD,
    "seat_construction":    SRC_VALVE_STD,
    "disc_construction":    SRC_VALVE_STD,
    "wedge_construction":   SRC_VALVE_STD,
    "shaft_construction":   SRC_VALVE_STD,
    "back_seat_construction": SRC_VALVE_STD,
    "packing_construction": SRC_VALVE_STD,
    "bonnet_construction":  SRC_VALVE_STD,
    "construction_bonnet":  SRC_VALVE_STD,
    "locks":                SRC_VALVE_STD,

    # Material
    "body_material":        SRC_PMS_AND_STD,
    "ball_material":        SRC_PMS_AND_STD,
    "stem_material":        SRC_PMS_AND_STD,
    "seat_material":        SRC_PMS_AND_STD,
    "seal_material":        SRC_PMS_AND_STD,
    "gland_material":       SRC_PMS_AND_STD,
    "gland_packing":        SRC_PMS_AND_STD,
    "lever_handwheel":      SRC_PMS_AND_STD,
    "spring_material":      SRC_PMS_AND_STD,
    "disc_material":        SRC_PMS_AND_STD,
    "wedge_material":       SRC_PMS_AND_STD,
    "trim_material":        SRC_PMS_AND_STD,
    "shaft_material":       SRC_PMS_AND_STD,
    "needle_material":      SRC_PMS_AND_STD,
    "material_needle_material": SRC_PMS_AND_STD,
    "back_seat_material":   SRC_PMS_AND_STD,
    "hinge_pin_material":   SRC_PMS_AND_STD,
    "material_cover_material": SRC_PMS_AND_STD,
    "material_hinge/_hinge_pin": SRC_PMS_AND_STD,
    "bonnet_material":      SRC_PMS_AND_STD,
    "gaskets":              SRC_PMS_AND_STD,
    "bolts":                SRC_PMS_AND_STD,
    "nuts":                 SRC_PMS_AND_STD,

    # Testing / Compliance
    "marking_purchaser":    SRC_VALVE_STD,
    "marking_manufacturer": SRC_VALVE_STD,
    "inspection_testing":   SRC_VALVE_STD,
    "leakage_rate":         SRC_VALVE_STD,
    "hydrotest_shell":      SRC_PMS_AND_STD,
    "hydrotest_closure":    SRC_PMS_AND_STD,
    "pneumatic_test":       SRC_VALVE_STD,
    "material_certification": SRC_PROJECT,
    "fire_rating":          SRC_PROJECT,
    "finish":               SRC_PROJECT,
    "applicable_notes":     SRC_CALCULATED,
}


def get_field_sources(data: dict[str, str]) -> dict[str, str]:
    """Return a source mapping for all fields present in the data dict.

    Args:
        data: Flat datasheet dict {field_name: value}

    Returns:
        Dict mapping field_name → source description string
    """
    sources: dict[str, str] = {}
    for key in data:
        sources[key] = FIELD_SOURCE_MAP.get(key, SRC_VALVE_STD)
    return sources
