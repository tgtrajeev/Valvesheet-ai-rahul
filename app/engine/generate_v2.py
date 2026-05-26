"""v2 Datasheet Generator — derives datasheets from PMS Generator JSON.

This is the SEPARATE pipeline for new/custom piping classes coming from the
PMS Generator tool. It produces exactly the same ~40-field datasheet structure
as the existing rule_engine.generate_datasheet(), but reads all PMS data from
a PmsContext adapter instead of global singletons.

Design rules:
  1. **Frozen pipeline stays frozen.** This file NEVER modifies rule_engine.py,
     pms_loader.py, pms_datasheet_loader.py, or any global data files.
  2. **Reuse, don't duplicate.** Pure engineering rules (CONSTRUCTION, thresholds,
     helpers) are imported from rule_engine.py — they don't depend on singletons.
  3. **PmsContext is the sole PMS data source.** No calls to get_pms_loader(),
     get_global_vds_loader(), or any singleton accessor.
  4. **Complete datasheet always.** Every field is derived — nothing is omitted
     just because the PMS input changed. Cascade: whatever changed in PMS flows
     through to every affected field automatically.
"""
from __future__ import annotations

import re
from typing import Optional

from ..models.vds import DecodedVDS, EndConnection, SeatType
from .pms_context import PmsContext

# ── Reuse pure engineering constants & helpers from existing rule_engine ──
from .rule_engine import (
    # Constants
    CONSTRUCTION,
    VALVE_TYPE_DESCRIPTION,
    PROJECT_CONSTANTS,
    GASKET_MATERIAL,
    _PRESSURE_CLASS_NUM,
    _BALL_MOUNTING,
    _GEARBOX,
    _SEALANT_INJECTION,
    _NDT_EXTENT,
    _BF_GASKET_SS316L_RF,
    _BF_BODY_SS316L,
    _BF_BOLT_SS316L,
    _BF_NUT_SS316L,
    # Size-dependent helpers (pure functions, no singleton dependency)
    _resolve_ball_mounting,
    _resolve_operation,
    _resolve_ndt_extent,
    _resolve_extended_stem,
    _resolve_wedge_type,
    _resolve_end_connection,
    _resolve_corrosion_allowance,
    _calc_hydrotest,
    _stem_trim_row,
    # Footer notes
    build_footer_notes,
    footer_notes_as_text,
    # BF construction fix
    apply_bf_vms_construction_overrides,
)

from .pms_datasheet_loader import get_reference_tables
from .datasheet_prune import prune_datasheet_by_valve_type
from . import rule_citations

from .project_codes import get_pms_doc, get_coating_doc


# ── v2 footer-notes (dynamic PMS doc number, not from frozen rule_engine) ────

# Matches rule_engine._FORGED_PART_BY_VALVE_TYPE without importing the private
# constant (keep coupling to the frozen file minimal).
_FORGED_PART = {
    "BL": "Ball", "BS": "Ball", "DB": "Ball",
    "GA": "Wedge", "BF": "Disc", "CH": "Disc",
    "GL": "Disc", "NE": "Needle",
}


def _build_footer_notes_v2(
    valve_type: str,
    is_nace: bool,
    pms_doc: str,
    pms_project_notes: list[str] | None = None,
    class_note: str | None = None,
) -> str:
    """Return numbered footer notes with dynamic PMS doc + PMS project notes.

    Standard engineering notes come first (quotation, hydro-test, forging,
    bolt coating, NACE). Then PMS Generator project_notes are appended —
    these are the actual notes stored in the PMS for this piping class
    (e.g. soft-seat temp limits, wafer-check restrictions, etc.).
    """
    forged_part = _FORGED_PART.get(valve_type, "Disc")
    notes: list[str] = [
        "This data sheet shall be completed and returned with the quotation. "
        "Failure to return the completed data sheet will deem the offer technically not acceptable.",
        "Data sheet shall be read in conjunction with Piping Material Specification, "
        f"Doc No. {pms_doc}.",
        "Hydrostatic shell test pressure shall be 1.5 times of Max. design pressure, "
        "and hydraulic seat test shall be 1.1 times of Max. design pressure for seats.",
        f"{forged_part}, Stem and Gland material shall be forged, Castings are not acceptable.",
        "All stud bolts and nuts shall be XYLAR 2 + XYLAN 1070 coated with minimum "
        "combined thickness of 50μm.",
    ]
    if is_nace:
        notes.append("Valve shall be in accordance with NACE MR0175 /ISO 15156-1/2/3.")

    # ── Append PMS project notes (from PMS Generator) ──
    if pms_project_notes:
        for pn in pms_project_notes:
            text = pn.strip()
            if text:
                notes.append(text)

    # ── Append class-level note if present ──
    if class_note:
        notes.append(class_note.strip())

    return "\n".join(f"{i}. {note}" for i, note in enumerate(notes, start=1))


def generate_datasheet_v2(
    decoded: DecodedVDS,
    ctx: PmsContext,
    size_inches: float | None = None,
    return_provenance: bool = False,
    project_name: str | None = None,
) -> dict[str, str] | tuple[dict[str, str], dict[str, str]]:
    """Generate a complete valve datasheet from a decoded VDS + PmsContext.

    This is the v2 equivalent of rule_engine.generate_datasheet(). The
    entire PMS data layer is supplied by ``ctx`` (PmsContext) — no global
    singletons are consulted.

    Args:
        decoded: A DecodedVDS object from vds_decoder.decode_vds()
        ctx: PmsContext wrapping the PMS Generator JSON for this piping class
        size_inches: Optional valve size for size-dependent rules
        return_provenance: If True, returns (data, provenance) tuple

    Returns:
        Flat dict {field_name: value}. If return_provenance=True, returns
        (data, provenance) tuple where provenance maps each field to its source.
    """
    vt = decoded.valve_type.value        # "BL", "GA", etc.
    design = decoded.design               # "R", "F", "M", etc.
    seat = decoded.seat_type.value if decoded.seat_type else "M"
    pc = decoded.piping_class             # "Y1"
    ec = decoded.end_connection           # EndConnection enum
    is_nace = decoded.is_nace or ctx.is_nace()
    is_lt = decoded.is_low_temp or ctx.is_low_temp()
    is_rtj = ec in (EndConnection.RTJ, EndConnection.RTJ_NPT)

    # ── Material category from PmsContext (NOT from regex/singleton) ──
    cat = ctx.get_material_category()

    # ── Pressure class from PmsContext ──
    pc_letter = ctx.get_pressure_class_letter()
    pc_num = ctx.get_pressure_class_num()

    # ── Reference tables (shared, read-only JSON — not a singleton mutation) ──
    _rt = get_reference_tables()

    # ── Build the datasheet ──
    data: dict[str, str] = {}

    # ────────────────────────────────────────────────────────────────────────
    # HEADER / IDENTIFICATION
    # ────────────────────────────────────────────────────────────────────────
    data["vds_no"] = decoded.display_vds
    data["valve_type"] = VALVE_TYPE_DESCRIPTION.get(
        (vt, design), f"{vt} Valve, design {design}"
    )
    data["piping_class"] = pc

    # ────────────────────────────────────────────────────────────────────────
    # SERVICE & SIZE
    # ────────────────────────────────────────────────────────────────────────
    data["service"] = ctx.get_service() or ""
    data["size_range"] = ctx.get_size_range_for_vds(decoded.raw_vds) or '1/2" - 24"'

    # ────────────────────────────────────────────────────────────────────────
    # VALVE STANDARD (same rules as v1, using reference tables)
    # ────────────────────────────────────────────────────────────────────────
    if vt == "GA" and cat in ("SS316L", "SS316L_NACE", "DSS", "SDSS", "SDSS_NACE"):
        data["valve_standard"] = _rt.get("valve_standard", "GA_CRA")
    elif vt in ("BL", "BS") and seat == "M":
        data["valve_standard"] = _rt.get("valve_standard", "BL_METAL")
    elif vt in ("BL", "BS"):
        if size_inches is not None and (size_inches > 24 or pc_num > 600):
            data["valve_standard"] = "API SPEC 6D / ISO 14313"
        else:
            data["valve_standard"] = _rt.lookup("valve_standard", vt, design)
    else:
        data["valve_standard"] = _rt.lookup("valve_standard", vt, design)

    # ────────────────────────────────────────────────────────────────────────
    # PRESSURE CLASS
    # ────────────────────────────────────────────────────────────────────────
    data["pressure_class"] = ctx.get_pressure_class_display()

    # ────────────────────────────────────────────────────────────────────────
    # DESIGN PRESSURE (from PmsContext P-T table)
    # ────────────────────────────────────────────────────────────────────────
    data["design_pressure"] = ctx.get_design_pressure_display()

    # ────────────────────────────────────────────────────────────────────────
    # CORROSION ALLOWANCE
    # ────────────────────────────────────────────────────────────────────────
    data["corrosion_allowance"] = _resolve_corrosion_allowance(
        cat, ctx.get_corrosion_allowance()
    )

    # ────────────────────────────────────────────────────────────────────────
    # NACE / SOUR SERVICE / LOW TEMP
    # ────────────────────────────────────────────────────────────────────────
    if is_nace:
        data["sour_service"] = "NACE MR0175 / ISO 15156 compliant"
        data["nace_compliant"] = "Yes"
    else:
        data["sour_service"] = "-"
        data["nace_compliant"] = "No"

    if vt == "GA" and is_nace:
        data["sour_service"] = (
            "NACE MR0175 /ISO 15156-1/2/3, SSC Region 3, Non-exposed, internal only"
        )

    if is_lt:
        data["low_temperature"] = "Yes - Impact tested"
        _default_lt_temp = "-46°C" if cat in ("DSS", "SDSS", "SDSS_NACE") else "-45°C"
        data["min_design_temp"] = ctx.get_min_design_temp_display() or _default_lt_temp
    else:
        data["low_temperature"] = "No"
        _default = (
            "-29°C" if cat.startswith("CS")
            else "-100°C" if cat.startswith("SS")
            else "-46°C"
        )
        data["min_design_temp"] = ctx.get_min_design_temp_display() or _default

    # Max design temperature — from PmsContext P-T table or design_conditions
    data["max_design_temp"] = f"{int(ctx.get_design_temp_c())}°C"

    # Design code
    data["design_code"] = "ASME B31.3"

    # Material class label
    data["material_class"] = ctx.raw.code_factors.fitting_specs.family

    # ────────────────────────────────────────────────────────────────────────
    # END CONNECTIONS
    # ────────────────────────────────────────────────────────────────────────
    data["end_connections"] = _resolve_end_connection(
        ec, pc, cat, size_inches,
        pms_flange_face=ctx.get_flange_face_code(),
        pms_flange_type=ctx.get_flange_type(),
        pms_flange_std=ctx.get_flange_std(),
    )

    # Flange material
    forged_mat = ctx.get_forged_material()
    if forged_mat:
        data["flange_material"] = forged_mat

    # Face to face
    data["face_to_face"] = _rt.lookup("face_to_face", vt, design)

    # ────────────────────────────────────────────────────────────────────────
    # CONSTRUCTION (from valve-type template)
    # ────────────────────────────────────────────────────────────────────────
    tmpl_key = f"{vt}_{design}" if vt == "CH" else vt
    tmpl = CONSTRUCTION.get(tmpl_key, CONSTRUCTION.get(vt, {}))
    for field, value in tmpl.items():
        data[field] = value

    # ── Size-dependent construction ──
    if vt in ("BL", "BS"):
        mounting = _resolve_ball_mounting(size_inches, pc_num)
        data["ball_construction"] = f'{mounting["description"]}, no vent hole, Solid Type'
        data["ball_mounting_type"] = mounting["type"]
        if mounting["type"] == "Trunnion":
            data["dbb_feature"] = "Double Block and Bleed capability"
            data["seat_loading"] = "Spring-loaded seat rings"
            data["body_vent_drain"] = (
                "Body vent and drain fitted with NPT threaded plugs"
            )
            sealant_min = _SEALANT_INJECTION.get(pc_num, 0)
            if size_inches is None or size_inches >= sealant_min:
                data["sealant_injection"] = "Seat sealant injection system fitted"
        elif mounting["type"] == "Floating":
            data["body_cavity_relief"] = "Body cavity pressure relief required"

    if vt == "GA":
        data["wedge_construction"] = _resolve_wedge_type(size_inches)

    if vt == "DB" and size_inches is not None:
        if size_inches <= 2:
            data["body_construction"] = (
                "One-piece forged body, integral construction"
            )
            data["dbb_end_connection"] = 'Flange x 1/2" NPT'
        else:
            data["body_construction"] = "Three-piece bolted body"
            data["dbb_end_connection"] = "Flanged both ends"

    # Check valve: piston type for small bore
    if vt == "CH" and size_inches is not None and size_inches <= 1.5:
        data["body_construction"] = (
            'Integral Flanged, Bolted Cover (Piston Type required for 1/2"-1-1/2")'
        )
        data["seat_construction"] = (
            "Spring assisted Metal to metal, Renewable Seat Ring"
        )
        data["operation"] = (
            "Horizontal installation only (piston type check valve)"
        )
        data["check_valve_note"] = (
            'Small bore check valves (1/2"-1-1/2") SHALL be Piston Type, '
            "horizontal only per PMS_PDF.pdf §6.2"
        )

    # Flange face note
    if ec in (EndConnection.RF, EndConnection.RTJ, EndConnection.FF):
        if pc_num <= 600:
            data["flange_face_note"] = (
                f"CL {pc_num}: Raised Face (RF) per PMS_PDF.pdf §6.22.1"
            )
        else:
            data["flange_face_note"] = (
                f"CL {pc_num}: Ring Type Joint (RTJ) per PMS_PDF.pdf §6.22.1"
            )

    # Operation
    data["operation"] = _resolve_operation(vt, size_inches, pc_num)

    # Body form
    if size_inches is not None and size_inches <= 1.5:
        data["body_form"] = "Forged"
    elif size_inches is not None:
        data["body_form"] = "Cast or Forged"
    else:
        data["body_form"] = (
            'Forged (1-1/2" and below), Cast or Forged (2" and above)'
        )

    # ────────────────────────────────────────────────────────────────────────
    # MATERIALS (PmsContext body material → reference tables fallback)
    # ────────────────────────────────────────────────────────────────────────
    body_mat = ctx.get_body_material_pms() or _rt.get("body_material", cat)
    if vt == "BF" and cat in ("SS316L", "SS316L_NACE") and not ctx.get_body_material_pms():
        body_mat = _BF_BODY_SS316L
    if size_inches is not None and size_inches <= 1.5 and vt != "BF":
        parts = body_mat.split("/")
        forged_parts = [p.strip() for p in parts if "forged" in p.lower()]
        if forged_parts:
            body_mat = forged_parts[0]
    data["body_material"] = body_mat

    data["stem_material"] = _stem_trim_row(
        cat, None, is_nace=is_nace, is_lt=is_lt,
    )
    data["gland_material"] = _rt.get("gland_material", cat)
    data["gland_packing"] = _rt.get("gland_packing", cat)
    data["lever_handwheel"] = "Solid ASTM A47 HDG/ ASTM A220 HDG/ SS316"

    # Spring row
    if vt == "BF":
        pass
    elif vt in ("BL", "BS", "CH", "GL"):
        data["spring_material"] = "Inconel 750"
    # NE/DB don't get spring_material

    # Valve-type-specific material rows
    if vt in ("BL", "BS", "DB"):
        data["ball_material"] = _rt.get("ball_material", cat)
        data["seat_material"] = _rt.get("seat_material", seat)
        if vt in ("BL", "BS"):
            data["seal_material"] = _rt.get("seal_material_ball", seat)
        if vt != "DB":
            data["seat_construction"] = _rt.get("seat_construction_by_seat", seat)
        if seat == "M" and vt in ("BL", "BS"):
            data["seat_coating"] = (
                "Tungsten Carbide overlay, min 1050 HV, 150-250 μm thickness"
            )
            if cat.startswith("CS"):
                data["hardness_requirement"] = (
                    "Body/disc min 250 BHN, min 50 BHN differential"
                )
            data["stellite_overlay"] = (
                "Stellite 6 by deposition, min 1.6 mm finished thickness"
            )
    elif vt == "GA":
        data["wedge_material"] = _rt.get("body_material", cat) + ", Hard faced"
        data["seat_material"] = _rt.get("seat_material", seat)
        data["seal_material"] = _rt.get("seal_material_gate", seat)
        if cat.startswith("CS") and seat == "M":
            data["hardness_requirement"] = (
                "Body seat and wedge min 250 BHN, min 50 BHN differential"
            )
    elif vt == "GL":
        data["disc_material"] = data["stem_material"] + ", Hard faced"
        data["seat_material"] = _rt.get("seat_material", seat)
        data["seal_material"] = _rt.get("seal_material_gate", seat)
        if cat.startswith("CS") and seat == "M":
            data["hardness_requirement"] = (
                "Body seat and disc min 250 BHN, min 50 BHN differential"
            )
    elif vt == "CH":
        data["disc_material"] = _rt.get("stem_material", cat)
        data["seat_material"] = _rt.get("seat_material", seat)
        # seal_material_gate only has M/T entries; PEEK (P) falls back to ball table
        try:
            data["seal_material"] = _rt.get("seal_material_gate", seat)
        except KeyError:
            data["seal_material"] = _rt.get("seal_material_ball", seat)
        if design == "S":
            data["hinge_pin_material"] = _rt.get("stem_material", cat)
        if cat in ("CS", "CS_NACE"):
            data["cover_material"] = "Forged - ASTM A105N"
            data["material_cover_material"] = "Forged - ASTM A105N"
    elif vt == "BF":
        data["shaft_material"] = _stem_trim_row(
            cat, None, is_nace=is_nace, is_lt=is_lt,
        )
        data["disc_material"] = data["shaft_material"] + ", Stellite Hard Faced"
        data["seal_material"] = _rt.get("seal_material_ball", seat)
        _seat_bf = _rt.get("seat_material", seat)
        if seat == "T":
            _seat_bf = "Reinforced PTFE"
        data["seat_material"] = _seat_bf
    elif vt == "NE":
        data["needle_material"] = _rt.get("stem_material", cat)
        data["seat_material"] = _rt.get("seat_material", seat)
        data["minimum_bore"] = "10 mm (instrument connections)"
        data["trim_material"] = data.get("stem_material", "")

    # BF: keep both stem + shaft; no spring
    if vt == "BF":
        data.pop("spring_material", None)

    # Backseat for GA, GL, NE
    if vt in ("GA", "GL", "NE"):
        data["backseat"] = "Back seated, renewable"

    # Back seat material (gate/globe/needle only)
    if vt in ("GA", "GL", "NE"):
        data["back_seat_material"] = (
            f'{data["stem_material"]}, Stellite Hard Faced'
        )

    # Seat pocket CRA overlay (CS NACE)
    if vt in ("GA", "GL", "CH") and is_nace and cat.startswith("CS"):
        data["seat_pocket_overlay"] = (
            "Body seat pockets overlayed with corrosion resistant material "
            "per PMS_PDF.pdf §6.15 (CS valve in corrosive service)"
        )

    # Elastomer explosive decompression resistance
    if is_nace or cat in ("CS_NACE", "LTCS_NACE"):
        data["elastomer_requirement"] = (
            "All elastomers in HC gas/liquid service with H₂, CH₄, or CO₂ "
            "shall have proven resistance to explosive decompression. "
            "Max O-ring section: 7 mm diameter per PMS_PDF.pdf §7.9. "
            "No precautions needed for gaseous service <30 barg."
        )

    # FFKM for methanol service
    service_str = data.get("service", "").lower()
    if ("methanol" in service_str or "glycol" in service_str) and data.get(
        "seal_material"
    ):
        data["seal_material_note"] = (
            "FFKM recommended for Methanol/Glycol service per PMS_PDF.pdf §7.8"
        )

    # Preferred resilient seating materials
    if seat in ("T", "P") and vt != "DB":
        data["resilient_seat_note"] = (
            "Preferred resilient seating: Nitrile, Viton, or RPTFE for -18°C to 93°C. "
            "Below -18°C: use softer materials (Kel-F, unreinforced PTFE). "
            "Not recommended where solids/abrasives present per PMS_PDF.pdf §7.8."
        )

    # Torque & operation limits
    data["max_torque"] = (
        "Max 150 Nm (handwheel), Max 270 Nm (lever) per PMS_PDF.pdf §6.11.2"
    )
    data["max_handwheel_diameter"] = "750 mm max per PMS_PDF.pdf §6.11.2"
    data["max_lever_length"] = "500 mm max each side per PMS_PDF.pdf §6.11.2"
    data["operating_force"] = (
        "Max 45 kg (100 lbs) to break open/close, 35 kg (75 lbs) at mid-stroke"
    )

    # ────────────────────────────────────────────────────────────────────────
    # BOLTING & GASKETS (PmsContext provides project-specific specs)
    # ────────────────────────────────────────────────────────────────────────
    gaskets = ctx.get_gaskets()
    if gaskets:
        data["gaskets"] = gaskets
    elif vt == "BF" and not is_rtj and cat in ("SS316L", "SS316L_NACE"):
        data["gaskets"] = _BF_GASKET_SS316L_RF
    else:
        data["gaskets"] = GASKET_MATERIAL.get(
            (cat, is_rtj), GASKET_MATERIAL.get((cat, False), "")
        )

    bolts = ctx.get_bolts()
    data["bolts"] = bolts or _rt.get("bolt_material", cat)
    nuts = ctx.get_nuts()
    data["nuts"] = nuts or _rt.get("nut_material", cat)

    if vt == "BF" and cat in ("SS316L", "SS316L_NACE") and not bolts:
        data["bolts"] = _BF_BOLT_SS316L
    if vt == "BF" and cat in ("SS316L", "SS316L_NACE") and not nuts:
        data["nuts"] = _BF_NUT_SS316L

    data["bolt_plating"] = (
        "No cadmium plating. XYLAN 1070 or equivalent fluoropolymer coating"
    )

    if vt in ("GA", "GL"):
        data["bonnet_material"] = _rt.get("body_material", cat)

    # ────────────────────────────────────────────────────────────────────────
    # HYDROTEST (from PmsContext derived conditions)
    # ────────────────────────────────────────────────────────────────────────
    shell_str, closure_str = ctx.get_hydrotest_display()
    data["hydrotest_shell"] = shell_str
    data["hydrotest_closure"] = closure_str

    # ────────────────────────────────────────────────────────────────────────
    # FIRE RATING
    # ────────────────────────────────────────────────────────────────────────
    if vt in ("BL", "BS"):
        mt = data.get("ball_mounting_type", "Mixed")
        if mt == "Trunnion":
            data["fire_rating"] = (
                "API SPEC 6FA (Trunnion), third-party witnessed"
            )
        elif mt == "Floating":
            data["fire_rating"] = (
                "API STD 607 / BS EN ISO 10497 (Floating), third-party witnessed"
            )
        else:
            data["fire_rating"] = (
                "API SPEC 6FA (Trunnion) / API STD 607 (Floating), third-party witnessed"
            )
    else:
        data["fire_rating"] = _rt.get("fire_rating", vt)

    if seat in ("T", "P"):
        if vt in ("BL", "BS"):
            data["fire_test"] = (
                "Required — BS EN ISO 10497 / API 607, third-party witnessed"
            )
            data["antistatic_device"] = (
                "Required for soft-seated ball valve (API 6D)"
            )
        elif vt == "DB":
            data["fire_test"] = (
                "Required — BS EN ISO 10497 / API 607, third-party witnessed"
            )
            data["antistatic_device"] = (
                "Required for soft-seated primary obturator per manufacturer / API 6D"
            )

    # ────────────────────────────────────────────────────────────────────────
    # INSPECTION & TESTING
    # ────────────────────────────────────────────────────────────────────────
    data["ndt_extent"] = _resolve_ndt_extent(pc_num, size_inches, cat)
    data["functional_test"] = (
        "5 cycles at manufacturer, 5 at fabrication yard, 5 offshore"
    )

    # Pressure test standard
    if (vt in ("BL", "BS") or vt == "DB") and pc_num > 150:
        data["pressure_test_standard"] = (
            f"Designed and tested per API 6D (CL {pc_num}) and applicable valve type codes"
        )
    else:
        data["pressure_test_standard"] = (
            "Designed per ASME B16.34, tested per API STD 598"
        )
    if vt in ("BL", "BS") and seat == "M":
        data["leakage_rate"] = (
            "Leakage rate not more than Rate 'B' per API 6D / ISO 5208 "
            "(metal seated ball valve)"
        )
    data["pressure_test_sequence"] = (
        "1) Body hydro test, 2) Seat hydro test, 3) Low pressure pneumatic seat test"
    )

    # Forged valve NDT
    if size_inches is not None and size_inches >= 2 and pc_num >= 600:
        if cat in ("LTCS_NACE",):
            data["forged_valve_ndt"] = (
                "MPE per ASTM A-275, acceptance per ASME B16.34 Annexe C "
                "(LTCS forged ≥2\", ≥600#)"
            )
        elif cat in ("SS316L", "SS316L_NACE", "DSS", "SDSS", "SDSS_NACE"):
            data["forged_valve_ndt"] = (
                "LPE per ASTM E-165, acceptance per ASME B16.34 Annexe D "
                "(SS/alloy forged ≥2\", ≥600#)"
            )

    # Austenitic SS requirements
    if cat in ("SS316L", "SS316L_NACE"):
        data["austenitic_ss_requirements"] = (
            "Carbon content ≤0.03% max for Type 316L including overlay. "
            "Capable of passing intergranular corrosion test per ASTM A262 "
            "Practice E. Class 1500/2500 castings: LP and RT examined."
        )
        data["chloride_restriction"] = (
            "300-series SS SHALL NOT be used where chloride >5 ppm AND "
            "temperature >60°C (stress corrosion cracking region) per "
            "PMS_PDF.pdf §7.2. Gaskets exempted for T ≤120°C."
        )

    if is_nace:
        data["fugitive_emissions_test"] = (
            "ISO 15848-1, Tightness Class BH, Endurance CC1/CO1"
        )
        if "elastomer_requirement" not in data:
            data["elastomer_requirement"] = (
                "Explosive decompression resistant per NORSOK M-710"
            )
        data["auxiliary_connections"] = (
            "Flanged welded construction only (no socket weld or seal-welded threads)"
        )
    if is_lt:
        data["impact_test"] = (
            "Charpy V-notch impact test per ASME B31.3 / ASME B16.34"
        )
    if cat in ("SS316L", "SS316L_NACE", "DSS", "SDSS", "SDSS_NACE", "CUNI"):
        data["pmi"] = (
            "Required — Positive Material Identification per project document, "
            "random PMI per mill cert"
        )

    # Locks
    if vt not in ("CH", "BF", "GL") and "locks" not in data:
        data["locks"] = "Valve lockable using padlock - Full Open, Fully Closed"
    if vt == "GL":
        data.pop("locks", None)

    # Position indicator
    if vt in ("BL", "BS", "BF", "DB"):
        data["position_indicator"] = "Visual position indicator required"

    # Extended stem, lifting lug, misc
    data["extended_stem"] = _resolve_extended_stem(size_inches)
    data["lifting_lug"] = (
        "Required if weight >= 25 kg (design load 2x, 5° tilt)"
    )
    data["asbestos_free"] = (
        "All packing, gaskets, and seals shall be asbestos-free"
    )
    data["nameplate"] = "SS316, 3 mm thick, per MSS-SP-25"

    # ── Project constants ──
    data.update(PROJECT_CONSTANTS)

    # Override leakage rate for metal-seated ball (must be AFTER PROJECT_CONSTANTS)
    if vt in ("BL", "BS") and seat == "M":
        data["leakage_rate"] = (
            "Leakage rate not more than Rate 'B' per API 6D / ISO 5208 "
            "(metal seated ball valve)"
        )

    # ── Dynamic project document codes (VDS-01) ──
    # PROJECT_CONSTANTS.finish has a hardcoded coating doc number from the frozen
    # rule_engine.  Override it with the dynamic project-specific value.
    _coating = get_coating_doc(project_name)
    data["finish"] = (
        f"General Specification for Paint and Protective Coating doc : {_coating}"
    )

    # ── Footer notes (dynamic PMS doc number + PMS project notes) ──
    _pms = get_pms_doc(project_name)
    data["datasheet_notes"] = _build_footer_notes_v2(
        vt, is_nace, _pms, ctx.get_project_notes(), ctx.get_class_note(),
    )

    # ── Clean up per valve type ──
    if vt == "DB":
        data.pop("back_seat_material", None)
        data.pop("seal_material", None)
        data.pop("seal_material_note", None)
        data.pop("spring_material", None)
    if vt == "NE":
        data.pop("spring_material", None)

    # ── No appendix override — new classes have no pms_vds_datasheets entry ──

    # ── Prune and BF fix ──
    prune_datasheet_by_valve_type(vt, design, seat, data)
    if vt == "BF":
        apply_bf_vms_construction_overrides(data)

    # ────────────────────────────────────────────────────────────────────────
    # PROVENANCE (v2 adds "PMS Generator" source tag)
    # ────────────────────────────────────────────────────────────────────────
    if return_provenance:
        provenance: dict[str, str] = {}
        for k in data:
            cite = rule_citations.get_citation(
                k, decoded, material_category=cat, size_inches=size_inches
            )
            formatted = rule_citations.format_citation(cite, brief=True)
            if formatted:
                provenance[k] = formatted
            else:
                provenance[k] = "PMS Generator JSON + engineering rules"

        # Tag fields that came directly from PMS Generator input
        _pms_direct_fields = {
            "service", "design_pressure", "pressure_class",
            "hydrotest_shell", "hydrotest_closure", "min_design_temp",
            "max_design_temp", "bolts", "nuts", "gaskets", "body_material",
            "flange_material", "end_connections", "material_class",
        }
        for f in _pms_direct_fields:
            if f in provenance:
                provenance[f] = f"PMS Generator ({ctx.get_class_code()}) + {provenance[f]}"

        return data, provenance

    return data
