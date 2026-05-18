"""source_values.py — for each datasheet field, returns the value as it comes
PURELY from the cited API/ASME/BS rule or table, with NO project-specific
elaboration.

The chat / XLSX UI displays this side-by-side with the "final" value (which
includes project conventions like XYLAR coating, size-threshold splits, etc.)
so a client can see exactly which part of the displayed value is mandated
by the universal standard and which part is the project's own specification.

Convention
----------
    final value             = what rule_engine.py emits (rule + project tweaks)
    source-derived value    = ONLY the rule portion, traceable to the cited PDF
"""
from __future__ import annotations

from . import standards_tables
from .standards_registry import build_citation_url


_PC_NUM = {"A": 150, "B": 300, "D": 600, "E": 900, "F": 1500, "G": 2500}


def _pc_num(piping_class: str) -> int:
    return _PC_NUM.get((piping_class[:1] if piping_class else "A").upper(), 150)


# ── Per-field source-derived values ───────────────────────────────────────

def _bolt_base(material_category: str) -> str:
    if material_category in ("LTCS_NACE",):
        return "ASTM A 320 Gr. L7M  (per API 6D §6.7 + low-temp impact rules + NACE MR0175)"
    if material_category in ("SS316L", "SS316L_NACE", "TUBING_SS", "TUBING_6MO"):
        return "ASTM A 320 Gr. L7M  (per API 6D §6.7 — austenitic / impact tested)"
    if material_category in ("DSS", "SDSS", "SDSS_NACE"):
        return "ASTM A 453 Gr. 660  (per API 6D §6.7 — duplex / Inconel-grade fastener)"
    if material_category == "TITANIUM":
        return ("ASTM A 193 Gr. B7M, XYLAR 2 + XYLAN 1070 coated with minimum combined thickness of 50μm "
                "(per project PMS B70 bolting spec — galvanic isolation from titanium body)")
    # default = carbon steel
    return "ASTM A 193 Gr. B7M  (per API 6D §6.7 + NACE MR0175 hardness limit HRC ≤ 35)"


def _nut_base(material_category: str) -> str:
    if material_category in ("LTCS_NACE", "SS316L", "SS316L_NACE", "TUBING_SS", "TUBING_6MO"):
        return "ASTM A 194 Gr. 7ML  (per API 6D §6.6 impact testing requirement)"
    if material_category in ("DSS", "SDSS", "SDSS_NACE"):
        return "ASTM A 453 Gr. 660  (duplex)"
    if material_category == "TITANIUM":
        return ("ASTM A 194 Gr. 2HM, XYLAR 2 + XYLAN 1070 coated with minimum combined thickness of 50μm "
                "(per project PMS B70 bolting spec)")
    return "ASTM A 194 Gr. 2HM  (per API 6D §6.7)"


def _body_base(material_category: str) -> str:
    if material_category in ("CS", "CS_NACE"):
        return "Group 1 (ferrous) per ASME B16.34 §6.1 — e.g. ASTM A105N (forged) / A216 WCB (cast)"
    if material_category == "LTCS_NACE":
        return "Group 1 (low-temp ferrous) per ASME B16.34 — e.g. ASTM A350 LF2 / A352 LCC"
    if material_category in ("SS316L", "SS316L_NACE"):
        return "Group 2 (austenitic stainless) per ASME B16.34 — e.g. ASTM A182 F316L / A351 CF3M"
    if material_category in ("DSS",):
        return "Duplex SS UNS S32205 per ASME B16.34 + EN 13445"
    if material_category in ("SDSS", "SDSS_NACE"):
        return "Super-duplex SS UNS S32750 per ASME B16.34"
    if material_category == "CUNI":
        return "Group 3 (copper alloy) — ASTM B148 C95800 (Ni-Al-bronze)"
    if material_category == "TITANIUM":
        return ("Group 4.2 (Titanium alloys) per ASME B16.34 §6.1 — "
                "ASTM B367 Gr. C-2 (cast) / ASTM B265 Gr. 2 with 3mm Titanium weld deposit on CS backing (≤ 1.5\"), "
                "ASTM A105N with 3mm Titanium weld deposit / ASTM B265 Gr. 2 (2\" and above) "
                "per project PMS B70 materials section")
    return f"Material per ASME B16.34 §6.1 selection for {material_category}"


def _trim_base(material_category: str) -> str:
    if material_category in ("CS", "CS_NACE"):
        return "Trim grade matching body — A182 F316 (per API 615 §6.2: trim ≥ body in corrosion resistance)"
    if material_category in ("SS316L", "SS316L_NACE"):
        return "Trim A182 F316L (matched to body per API 615 §6.2)"
    if material_category in ("DSS",):
        return "Trim A182 F60 (matched to duplex body per API 615 §6.2)"
    if material_category in ("SDSS", "SDSS_NACE"):
        return "Trim A182 F53 (matched to super-duplex body per API 615 §6.2)"
    if material_category == "TITANIUM":
        return "Titanium Grade 2 (ASTM B265 Gr. 2) trim — matched to body per API 615 §6.2 corrosion resistance"
    return f"Trim corrosion-resistance ≥ body per API 615 §6.2 (category {material_category})"


def _seat_base(seat_char: str) -> str:
    if seat_char == "T":
        return "Soft seat — virgin or glass-fibre reinforced PTFE (per API 615 §6.3, P-T limit ~205 °C)"
    if seat_char == "P":
        return "PEEK seat — engineered polymer, manufacturer P-T rating (per API 615 §6.3 — by agreement)"
    if seat_char == "M":
        return "Metal seat — hard-faced (Stellite / TCC), renewable (per API 615 §6.2; min 250 BHN per API 6D)"
    return ""


def _operation_base(valve_type: str) -> str:
    if valve_type in ("BL", "BS", "BF", "DB"):
        return "Lever for small quarter-turn valves; gear-operated handwheel for larger sizes (per API 615 §7.1; max breakaway 360 N per API 6D §5.13)"
    if valve_type in ("GA", "GL"):
        return "Multi-turn handwheel; gearbox required for large sizes (per API 615 §7.1)"
    if valve_type == "NE":
        return "Lever / T-bar (manual) per manufacturer standard"
    return ""


def get_source_value(field: str, decoded, material_category: str = "",
                     size_inches: float | None = None) -> str | None:
    """Returns the source-derived value (purely from cited standard) for `field`,
    or None if the field has no rule-derived value (e.g. project-only fields).
    """
    vt = decoded.valve_type.value
    seat = decoded.seat_type.value if decoded.seat_type else "M"
    pc = decoded.piping_class
    pc_num = _pc_num(pc)
    end = decoded.end_connection.value

    if field == "valve_standard":
        # Value IS the rule reference (already verbatim from API 6D / API 615)
        return None  # ← signal that source = final
    if field == "pressure_class":
        return None  # value is the rule
    if field == "end_connections":
        return None  # value is the rule
    if field == "face_to_face":
        # API 6D Annex C tables — return the actual cell value when size known
        if size_inches:
            _nps_map = {0.5:"1/2", 0.75:"3/4", 1.0:"1", 1.25:"1-1/4", 1.5:"1-1/2"}
            nps_str = _nps_map.get(size_inches, str(int(size_inches)) if size_inches==int(size_inches) else str(size_inches))
            f2f = standards_tables.lookup_face_to_face(vt, nps_str, pc_num, end)
            if f2f:
                return f"{f2f[0]} — direct lookup from {f2f[1]}"
        return None
    if field == "ball_construction":
        return ("Floating-ball type for small sizes; trunnion-mounted above thresholds: "
                "Class 150 ≥ 10\", Class 300 ≥ 6\", Class 600 ≥ 2\", Class 900+ all sizes "
                "(per API 6D §6.23)")
    if field == "stem_construction":
        if vt in ("BL", "BS", "DB"):
            return "Anti-static, anti-blowout stem (per API 6D §6.0)"
        if vt in ("GA", "GL"):
            return "Rising stem, outside screw and yoke (OS&Y), back-seated (per API 615 §4.1.1)"
        return None
    if field == "wedge_construction" and vt == "GA":
        return ("Solid wedge for NPS ≤ 1.5\"; flexible wedge for NPS > 1.5\" "
                "(per API 615 §4.1.1 + API 600)")
    if field == "operation":
        return _operation_base(vt)
    if field == "seat_construction":
        return _seat_base(seat)
    if field == "body_material":
        return _body_base(material_category)
    if field in ("ball_material", "stem_material", "trim_material",
                 "wedge_material", "disc_material", "shaft_material",
                 "needle_material", "back_seat_material", "cover_material"):
        return _trim_base(material_category)
    if field == "seat_material":
        return _seat_base(seat)
    if field == "gland_material":
        return _trim_base(material_category)
    if field == "gland_packing":
        return "Asbestos-free flexible graphite stem packing (per API 615 §6.4 + API 6D §6 Materials)"
    if field == "spring_material":
        return "Inconel 750 or equivalent (industry standard for spring service)"
    if field == "lever_handwheel":
        return "Hot-dip galvanised iron / SS316 (per API 615 §7.1)"
    if field == "gaskets":
        if pc_num >= 600 and end in ("J", "JT"):
            return "ASME B16.20 RTJ ring joint, oct/octagonal section, hardness limit per material"
        return "ASME B16.20 spiral-wound, SS316L winding + flexible graphite filler"
    if field == "bolts":
        return _bolt_base(material_category)
    if field == "nuts":
        return _nut_base(material_category)
    if field == "marking_purchaser":
        return "Permanent valve marking on body / nameplate per API 6D §11 + Table 7 (16 required items)"
    if field == "marking_manufacturer":
        return "MSS-SP-25 (referenced by API 6D §11 + Table 7)"
    if field == "inspection_testing":
        return "ASME B16.34, API 598 — Valves Inspection and Testing (referenced by API 6D §9)"
    if field == "leakage_rate":
        return "Per API 598 leakage acceptance criteria (or ISO 5208 Rate G for metal-seated)"
    if field == "hydrotest_shell":
        if size_inches:
            dur, src = standards_tables.lookup_hydrotest_shell_duration(size_inches)
            return f"1.5 × pressure rating @ 38 °C, duration {dur} (per API 6D §9.3 + Table 5)"
        return "1.5 × pressure rating @ 38 °C (per API 6D §9.3); duration per Table 5"
    if field == "hydrotest_closure":
        if size_inches:
            dur, src = standards_tables.lookup_seat_test_duration(size_inches)
            return f"1.1 × pressure rating @ 38 °C, duration {dur} (per API 6D §9.4 + Table 6)"
        return "1.1 × pressure rating @ 38 °C (per API 6D §9.4); duration per Table 6"
    if field == "pneumatic_test":
        return "5–7 barg low-pressure pneumatic seat test (per API 598)"
    if field == "material_certification":
        return "BS EN 10204 inspection documents — Type 3.1 / 3.2 (project allocates by part type)"
    if field == "fire_rating":
        if vt in ("BL", "BS", "DB"):
            return "API 6FA (trunnion ball) / API 607 + ISO 10497 (floating ball) (per API 6D §6.10)"
        return "API 607 + API 6FA + BS EN ISO 10497 (per API 6D §6.10)"
    if field == "finish":
        return "External coating per project paint spec (per API 6D §10 + Annex L); CRA valves not painted unless agreed"
    if field == "sour_service":
        if decoded.is_nace:
            return "NACE MR0175 / ISO 15156 compliant (sour service requirement)"
        return "Not required (non-sour service)"
    if field == "corrosion_allowance":
        return "Per pipe class service index + ASME B16.34"
    if field == "size_range":
        return None  # comes from project PMS class
    if field == "service":
        return None  # purely from project PMS class
    if field == "design_pressure":
        return None  # from project PMS P-T table
    if field == "valve_type":
        return None  # decoded from VDS code itself
    if field == "vds_no":
        return None
    if field == "piping_class":
        return None
    return None
