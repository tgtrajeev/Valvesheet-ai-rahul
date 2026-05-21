"""Runtime Rule Engine — derives a complete valve datasheet from VDS components + PMS data.

Instead of looking up pre-built entries from a static JSON index, this engine
*generates* a full datasheet for ANY valid VDS combination by applying:
  1. PMS piping class rules (materials, bolting, gaskets, hydrotest, design pressure)
  2. Valve type + design rules (construction, standards, operation)
  3. Seat type rules (seat material, seal material, seat construction)
  4. End connection rules (flanged RF, RTJ, BW, SW, etc.)
  5. Project constants (marking, testing, certification)

This makes the system genuinely intelligent — it can handle VDS codes it has
never seen before, as long as the combination is valid.
"""

import os
import re
from ..models.vds import DecodedVDS, ValveType, SeatType, EndConnection
from .pms_loader import get_pms_loader
from .pms_datasheet_loader import get_global_vds_loader, get_reference_tables
from .datasheet_prune import prune_datasheet_by_valve_type

# ============================================================================
# MATERIAL CATEGORY RESOLUTION
# ============================================================================

def _get_material_category(piping_class: str) -> str:
    """Derive material category from piping class code.

    Examples:
        A1  -> CS          B1N  -> CS_NACE       A1LN -> LTCS_NACE
        A10 -> SS316L      A10N -> SS316L_NACE   A20N -> DSS
        A25 -> SDSS        A25N -> SDSS_NACE     A3   -> GALV_SS_BODY
        A30 -> CUNI        A31  -> COPPER        A40  -> GRE
        T50A -> TUBING_SS  T60A -> TUBING_6MO
    """
    pc = piping_class.upper().strip()
    is_nace = "N" in pc
    is_lt = "L" in pc

    # Project PMS data is the source of truth for material family. The old
    # numeric fallback below is only a compatibility path for missing PMS rows.
    try:
        spec = get_pms_loader().get_spec(pc)
        material_description = (
            spec.header.material_description if spec and spec.header else None
        )
    except Exception:
        material_description = None
    cat_from_pms = _material_category_from_description(material_description, is_nace)
    if cat_from_pms:
        return cat_from_pms

    # Tubing classes
    if pc.startswith("T"):
        m = re.match(r"T(\d+)", pc)
        if m:
            return "TUBING_6MO" if int(m.group(1)) >= 60 else "TUBING_SS"
        return "TUBING_SS"

    # Standard classes: letter + number + optional modifiers
    m = re.match(r"[A-G](\d+)", pc)
    if not m:
        return "CS"

    num = int(m.group(1))
    category_map = {
        1: "LTCS_NACE" if (is_lt and is_nace) else ("CS_NACE" if is_nace else "CS"),
        2: "LTCS_NACE" if (is_lt and is_nace) else ("CS_NACE" if is_nace else "CS"),
        3: "GALV_SS_BODY",
        4: "GALV_SS_BODY",
        5: "GALV",
        6: "GALV",
        10: "SS316L_NACE" if is_nace else "SS316L",
        20: "DSS",
        25: "SDSS_NACE" if is_nace else "SDSS",
        30: "CUNI",
        31: "COPPER",
        40: "GRE",
        41: "GRE_BONSTRAND",
        42: "CPVC",
    }
    return category_map.get(num, "CS")


def _material_category_from_description(description: str | None, is_nace: bool) -> str | None:
    """Resolve material family from the project PMS header text."""
    if not description:
        return None
    text = description.lower()

    if "cpvc" in text:
        return "CPVC"
    if "gre" in text or "glass" in text or "rtrp" in text:
        return "GRE_BONSTRAND" if "bonstrand" in text else "GRE"
    if "copper" in text or "bronze" in text or "c12200" in text or "b42" in text:
        return "COPPER"
    if "cu-ni" in text or "cuni" in text or "cu ni" in text or "copper nickel" in text or "90/10" in text:
        return "CUNI"
    if "super duplex" in text or "sdss" in text or "s32750" in text:
        return "SDSS_NACE" if is_nace else "SDSS"
    if "duplex" in text or "dss" in text or "s31803" in text or "s32205" in text:
        return "DSS"
    if "316" in text or "stainless" in text or "ss" in text:
        return "SS316L_NACE" if is_nace else "SS316L"
    if "titanium" in text or "ti gr" in text or "b265" in text or "b367" in text:
        return "TITANIUM"
    if "galv" in text:
        return "GALV_SS_BODY" if "ss" in text or "stainless" in text else "GALV"
    if "ltcs" in text or "low temperature carbon" in text:
        return "LTCS_NACE" if is_nace else "CS"
    if "carbon" in text or text.strip() in {"cs", "c.s."}:
        return "CS_NACE" if is_nace else "CS"

    return None


# ============================================================================
# MATERIAL MAPS — what material spec applies for each material category
# ============================================================================

BODY_MATERIAL = {
    "CS":           "Carbon Steel, ASTM A216 Gr. WCB (cast) / ASTM A105N (forged)",
    "CS_NACE":      "Carbon Steel NACE-compliant, ASTM A216 Gr. WCB (cast) / ASTM A105N (forged)",
    "LTCS_NACE":    "Low Temperature Carbon Steel, ASTM A350 Gr. LF2 (NACE MR0175 / ISO 15156)",
    "SS316L":       "Stainless Steel 316L, ASTM A351 Gr. CF3M (cast) / ASTM A182 F316L (forged)",
    "SS316L_NACE":  "Stainless Steel 316L, ASTM A351 Gr. CF3M (NACE MR0175 / ISO 15156)",
    "DSS":          "Duplex Stainless Steel UNS S31803, ASTM A182 Gr. F51 (NACE MR0175 / ISO 15156)",
    "SDSS":         "Super Duplex Stainless Steel UNS S32750, ASTM A182 Gr. F53",
    "SDSS_NACE":    "Super Duplex Stainless Steel UNS S32750, ASTM A182 Gr. F53 (NACE MR0175 / ISO 15156)",
    "GALV":         "Carbon Steel, ASTM A216 Gr. WCB (Hot-Dip Galvanized per ASTM A123/A153)",
    "GALV_SS_BODY": "Stainless Steel, ASTM A351 Gr. CF3M (Valve body SS - piping CS galvanized)",
    "TITANIUM":     "Titanium Grade 2 — ASTM B265 Gr. 2 with 3mm Ti weld deposit on CS backing / ASTM B367 Gr. C-2 (cast), per ASME B16.34 Group 4.2",
    "CUNI":         "90/10 Cu-Ni Alloy UNS C70600 (EEMUA 234)",
    "COPPER":       "Bronze, ASTM B61 UNS C92200",
    "GRE":          "NAB (Nickel Aluminium Bronze) - Valve body for GRE piping",
    "GRE_BONSTRAND": "NAB (Nickel Aluminium Bronze) - Valve body for GRE Bonstrand piping",
    "CPVC":         "NAB (Nickel Aluminium Bronze) - Valve body for CPVC piping",
    "TUBING_SS":    "Stainless Steel 316/316L, ASTM A182 F316L",
    "TUBING_6MO":   "6Mo (UNS S31254) Tubing",
}

BALL_MATERIAL = {
    "CS": "Forged - ASTM A182-F316", "CS_NACE": "Forged - ASTM A182-F316L",
    "LTCS_NACE": "Forged - ASTM A182-F316L",
    "SS316L": "Forged - ASTM A182-F316L", "SS316L_NACE": "Forged - ASTM A182-F316L",
    "DSS": "Forged - ASTM A182 F60", "SDSS": "Forged - ASTM A182 F53",
    "SDSS_NACE": "Forged - ASTM A182 F53",
    "GALV": "Forged - ASTM A182-F316", "GALV_SS_BODY": "Forged - ASTM A182-F316L",
    "CUNI": "Monel K500", "COPPER": "Forged - ASTM B124 UNS NO C 37700",
    "GRE": "NAB UNS C95800", "GRE_BONSTRAND": "NAB UNS C95800", "CPVC": "NAB UNS C95800",
    "TUBING_SS": "Forged - ASTM A182-F316L", "TUBING_6MO": "Forged - 6Mo UNS S31254",
}

STEM_MATERIAL = {
    "CS": "Forged - ASTM A182 F316", "CS_NACE": "Forged - ASTM A182 F316L",
    "LTCS_NACE": "Forged - ASTM A182 F316L",
    "SS316L": "Forged - ASTM A182 F316L", "SS316L_NACE": "Forged - ASTM A182 F316L",
    "DSS": "Forged - ASTM A182 F60", "SDSS": "Forged - ASTM A182 F53",
    "SDSS_NACE": "Forged - ASTM A182 F53",
    "GALV": "Forged - ASTM A182 F316", "GALV_SS_BODY": "Forged - ASTM A182 F316L",
    "CUNI": "Monel K500", "COPPER": "Forged - ASTM B124 UNS NO C 37700",
    "GRE": "NAB UNS C95800", "GRE_BONSTRAND": "NAB UNS C95800", "CPVC": "NAB UNS C95800",
    "TUBING_SS": "Forged - ASTM A182 F316L", "TUBING_6MO": "Forged - 6Mo UNS S31254",
}


def _resolve_stem_grade_for_trim(
    cat: str,
    pms_stem: str,
    *,
    is_nace: bool,
    is_lt: bool,
) -> str:
    """When the material *category* expects 316L trim but PMS lists bare *F316*, use category STEM_MATERIAL.

    Applies from SS316L / NACE / LT categories (and any future category whose STEM row is 316L),
    not only when the VDS piping-class suffix flags NACE or low temperature — so back-seat and
    disc lines stay aligned with the stem row.
    """
    del is_nace, is_lt  # callers pass flags; normalization is driven by ``cat`` vs PMS text.
    fallback = get_reference_tables().get("stem_material", cat)
    if "316L" not in fallback.upper():
        return pms_stem
    u = (pms_stem or "").upper().replace(" ", "")
    if "F316L" in u or "316L" in (pms_stem or "").upper():
        return pms_stem
    if re.search(r"\bF316\b", pms_stem, re.I):
        return fallback
    # PMS shorthand: SS316 / bare "316" in ASTM string when category mandates 316L trim.
    if re.search(r"\bSS316\b(?!\s*L\b)", pms_stem, re.I):
        return fallback
    if re.search(r"\b316\b(?!\s*L\b)", pms_stem, re.I) and not re.search(r"F316", pms_stem, re.I):
        return fallback
    return pms_stem


def _stem_trim_row(
    cat: str,
    pms_stem: str | None,
    *,
    is_nace: bool,
    is_lt: bool,
) -> str:
    if pms_stem:
        return _resolve_stem_grade_for_trim(cat, pms_stem, is_nace=is_nace, is_lt=is_lt)
    return get_reference_tables().get("stem_material", cat)


GLAND_MATERIAL = {
    "CS": "Forged - ASTM A182 F6A CL 2", "CS_NACE": "Forged - ASTM A182 F6A CL 2",
    "LTCS_NACE": "Forged - ASTM A350 LF2",
    "SS316L": "Forged - ASTM A182 F316L", "SS316L_NACE": "Forged - ASTM A182 F316L",
    "DSS": "Forged - ASTM A182 F60", "SDSS": "Forged - ASTM A182 F53",
    "SDSS_NACE": "Forged - ASTM A182 F53",
    "GALV": "Forged - ASTM A182 F6A CL 2", "GALV_SS_BODY": "Forged - ASTM A182 F316L",
    "CUNI": "Monel K500", "COPPER": "Forged - ASTM B124 UNS NO C 37700",
    "GRE": "NAB UNS C95800", "GRE_BONSTRAND": "NAB UNS C95800", "CPVC": "NAB UNS C95800",
    "TUBING_SS": "Forged - ASTM A182 F316L", "TUBING_6MO": "Forged - 6Mo UNS S31254",
}

# Gland packing
_GLAND_PACKING_STD = "Flexible graphite with Braided (Non asbestos, yarn reinforced with Inconel, corrosion inhibitor), Renewable"
_GLAND_PACKING_SIMPLE = "Flexible graphite Braided (Non asbestos, corrosion inhibitor), Renewable"
# Butterfly appendix: short packing line (PMS gland_packing still wins when set).
_GLAND_PACKING_BF = "Flexible graphite, asbestos-free"
GLAND_PACKING = {
    "CS": _GLAND_PACKING_STD, "CS_NACE": _GLAND_PACKING_STD,
    "LTCS_NACE": _GLAND_PACKING_STD,
    "SS316L": _GLAND_PACKING_STD, "SS316L_NACE": _GLAND_PACKING_STD,
    "DSS": _GLAND_PACKING_STD, "SDSS": _GLAND_PACKING_STD, "SDSS_NACE": _GLAND_PACKING_STD,
    "GALV": _GLAND_PACKING_STD, "GALV_SS_BODY": _GLAND_PACKING_STD,
    "CUNI": _GLAND_PACKING_SIMPLE, "COPPER": _GLAND_PACKING_SIMPLE,
    "GRE": _GLAND_PACKING_SIMPLE, "GRE_BONSTRAND": _GLAND_PACKING_SIMPLE,
    "CPVC": _GLAND_PACKING_SIMPLE,
    "TUBING_SS": _GLAND_PACKING_STD, "TUBING_6MO": _GLAND_PACKING_STD,
}

# ============================================================================
# BOLTING & GASKETS — resolved from PMS first, then rule-based fallback
# ============================================================================

BOLT_MATERIAL = {
    "CS": "ASTM A193 Gr. B7M, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "CS_NACE": "ASTM A193 Gr. B7M, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "LTCS_NACE": "ASTM A320 Gr. L7M, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "SS316L": "ASTM A320 Gr. L7M, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "SS316L_NACE": "ASTM A320 Gr. L7M, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "DSS": "ASTM A453 Gr. 660", "SDSS": "ASTM A453 Gr. 660", "SDSS_NACE": "ASTM A453 Gr. 660",
    "GALV": "ASTM A193 Gr. B7M, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "GALV_SS_BODY": "ASTM A193 Gr. B7M, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "CUNI": "ASTM A193 Gr. B7M, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "COPPER": "ASTM A193 Gr. B7M, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "GRE": "ASTM A193 Gr. B7M, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "GRE_BONSTRAND": "ASTM A193 Gr. B7M, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "CPVC": "ASTM A193 Gr. B7 HDG per ASTM A153",
    "TUBING_SS": "ASTM A320 Gr. L7M, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "TUBING_6MO": "ASTM A320 Gr. L7M, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
}

NUT_MATERIAL = {
    "CS": "ASTM A194 Gr. 2HM, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "CS_NACE": "ASTM A194 Gr. 2HM, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "LTCS_NACE": "ASTM A194 Gr. 7ML, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "SS316L": "ASTM A194 Gr. 7ML, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "SS316L_NACE": "ASTM A194 Gr. 7ML, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "DSS": "ASTM A453 Gr. 660", "SDSS": "ASTM A453 Gr. 660", "SDSS_NACE": "ASTM A453 Gr. 660",
    "GALV": "ASTM A194 Gr. 2HM, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "GALV_SS_BODY": "ASTM A194 Gr. 2HM, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "CUNI": "ASTM A194 Gr. 2HM, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "COPPER": "ASTM A194 Gr. 2HM, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "GRE": "ASTM A194 Gr. 2HM, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "GRE_BONSTRAND": "ASTM A194 Gr. 2HM, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "CPVC": "ASTM A194 Gr. 2H HDG per ASTM A153, with 3.2 mm steel + CPVC washer on both sides",
    "TUBING_SS": "ASTM A194 Gr. 7ML, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
    "TUBING_6MO": "ASTM A194 Gr. 7ML, XYLAR 2 + XYLAN 1070 coated, min 50 \u03bcm combined",
}

# Wafer / lug butterfly on class B (RF) SS316L — flat elastomer ring per project appendix when PMS omits gaskets.
_BF_GASKET_SS316L_RF = "3mm thick flat ring of neoprene/ EPDM rubber as ASME B 16.21"
_BF_BODY_SS316L = 'ASTM A182 F316L (1.5" and below), A351 CF3M (2" and above)'
# Butterfly + austenitic SS piping class: appendix stud/nut grades when PMS bolting is absent.
_BF_BOLT_SS316L = (
    "ASTM A 193 Gr. B7M, XYLAR 2 + XYLAN 1070 coated with minimum combined thickness of 50\u03bcm"
)
_BF_NUT_SS316L = (
    "ASTM A 194 Gr. 2HM, XYLAR 2 + XYLAN 1070 coated with minimum combined thickness of 50\u03bcm"
)

GASKET_MATERIAL = {
    ("CS", False): "ASME B16.20, 4.5 mm, SS316/SS316L Spiral Wound with Flexible Graphite (F.G.) filler",
    ("CS_NACE", False): "ASME B16.20, 4.5 mm, SS316/SS316L Spiral Wound with Flexible Graphite (F.G.) filler",
    ("LTCS_NACE", False): "ASME B16.20, 4.5 mm, SS316/SS316L Spiral Wound with Flexible Graphite (F.G.) filler",
    ("CS", True): "ASME B16.20, OCT ring of Soft Iron, Max. Hardness 90 BHN, HDG",
    ("CS_NACE", True): "ASME B16.20, OCT ring of Soft Iron, Max. Hardness 90 BHN, HDG",
    ("LTCS_NACE", True): "ASME B16.20, OCT ring of Soft Iron, Max. Hardness 90 BHN",
    ("GALV", False): "3 mm thick flat ring of neoprene/EPDM rubber to ASME B16.21",
    ("GALV_SS_BODY", False): "3 mm thick flat ring of neoprene/EPDM rubber to ASME B16.21",
    ("SS316L", False): "ASME B16.20, 4.5 mm, SS316/SS316L Spiral Wound with Flexible Graphite (F.G.) filler",
    ("SS316L_NACE", False): "ASME B16.20, 4.5 mm, SS316/SS316L Spiral Wound with Flexible Graphite (F.G.) filler",
    ("SS316L", True): "ASME B16.20, OCT ring of SS316L, Max. Hardness 160 BHN",
    ("SS316L_NACE", True): "ASME B16.20, OCT ring of SS316L, Max. Hardness 160 BHN",
    ("DSS", False): "ASME B16.20, 4.5 mm, DSS UNS S31803 Spiral Wound with Flexible Graphite (F.G.) filler",
    ("DSS", True): "ASME B16.20, OCT ring of UNS S31803, Max. Hardness 22 HRC",
    ("SDSS", False): "ASME B16.20, 4.5 mm, DSS UNS S32750 Spiral Wound with Flexible Graphite (F.G.) filler",
    ("SDSS_NACE", False): "ASME B16.20, 4.5 mm, DSS UNS S32750 Spiral Wound with Flexible Graphite (F.G.) filler",
    ("SDSS", True): "ASME B16.20, OCT ring of UNS S32750, Max. Hardness 22 HRC",
    ("SDSS_NACE", True): "ASME B16.20, OCT ring of UNS S32750, Max. Hardness 22 HRC",
    ("CUNI", False): "3 mm thick flat ring of neoprene/EPDM rubber to ASME B16.21 (Full Face)",
    ("COPPER", False): "ASME B16.21, Full face gasket, 2 mm, CNAF",
    ("GRE", False): "EPDM Rubber Full Face Gasket with SS insert, Shore A Hardness 70 +/- 5, #150",
    ("GRE_BONSTRAND", False): "ASME B16.21, Flat Ring, 3 mm, CNAF, Oil Resistant, Glass Fibre Composite with NBR Binder",
    ("CPVC", False): "#150 Full face gasket, 3 mm, PTFE/EPDM, to ASME B16.21",
    ("TUBING_SS", False): "N/A - Instrumentation tubing class (compression fittings, no gaskets)",
    ("TUBING_6MO", False): "N/A - Instrumentation tubing class (compression fittings, no gaskets)",
}


# ============================================================================
# VALVE TYPE / DESIGN RULES
# ============================================================================

VALVE_TYPE_DESCRIPTION = {
    ("BL", "F"): "Ball Valve, Full Bore",
    ("BL", "R"): "Ball Valve, Reduced Bore",
    ("BL", "M"): "Ball Valve, Metal Seated",
    ("BS", "F"): "Ball Valve (SDSS), Full Bore",
    ("BS", "R"): "Ball Valve (SDSS), Reduced Bore",
    ("BS", "M"): "Ball Valve (SDSS), Metal Seated",
    ("BF", "W"): "Butterfly Valve, Wafer, Threaded lug type",
    ("BF", "T"): "Butterfly Valve, Triple Offset",
    ("BF", "P"): "Butterfly Valve, Triple Offset (TOV)",
    ("BF", "D"): "Butterfly Valve, Wafer, Threaded lug type",
    ("GA", "Y"): "Gate valve, Outside Screw and Yoke",
    ("GA", "W"): "Gate valve, Outside Screw and Yoke",
    ("GL", "Y"): "Globe valve, Outside Screw and Yoke",
    ("GL", "S"): "Globe valve, Outside Screw and Yoke",
    ("CH", "P"): "Check Valve, Piston Type",
    ("CH", "S"): "Check Valve, Swing type",
    ("CH", "D"): "Check Valve, Dual Plate, Wafer Threaded lug type",
    ("CH", "W"): "Check Valve, Dual Plate, Wafer Threaded lug type",
    ("DB", "R"): "Double Block and Bleed Valve",
    ("DB", "P"): "Double Block and Bleed Valve, Piston type (Instrument)",
    ("DB", "M"): "Double Block and Bleed Valve, Modular (Ball, Needle, Ball)",
    ("NE", "I"): "Needle Valve for instrumentation",
    ("NE", "A"): "Needle Valve for instrumentation, Angle type",
}

VALVE_STANDARD = {
    "BL": "API SPEC 6D / ISO 14313",
    "BS": "ISO 17292",
    "BF": "API STD 609",
    "GA": "API STD 600 / API STD 602",
    "GA_CRA": "API STD 603 (Corrosion-Resistant Bolted Bonnet Gate Valves)",
    "GL": "API STD 602 / BS EN ISO 15761 / BS 1873",
    ("CH", "P"): "API STD 602 / BS EN ISO 15761 / BS 1868",
    ("CH", "S"): "API STD 594 / API 6D / BS 1868",
    ("CH", "D"): "API STD 594",
    ("CH", "W"): "API STD 594",
    "DB": "API SPEC 6D",
    "NE": "BS EN ISO 15761",
    "BL_METAL": "API STD 608 / API SPEC 6D",
}

FIRE_RATING = {
    "BL": "API SPEC 6FA / API STD 607", "BS": "API SPEC 6FA / API STD 607",
    "DB": "API SPEC 6FA", "GA": "API SPEC 6FA",
    "GL": "API SPEC 6FA / BS EN 10497", "CH": "API SPEC 6FA",
    "BF": "API STD 607", "NE": "N/A",
}

FACE_TO_FACE = {
    "BL": "ASME B16.10 Long pattern, quarter turn",
    "BS": "ASME B16.10 Long pattern, quarter turn",
    "BF": "API 609 Cat B",
    ("CH", "D"): "API 594 Type A", ("CH", "W"): "API 594 Type A",
    ("CH", "P"): "ASME B16.10", ("CH", "S"): "ASME B16.10",
    "GA": "ASME B16.10", "GL": "ASME B16.10",
    "DB": "Manufacturer Standard", "NE": "Manufacturer Standard",
}

PRESSURE_CLASS = {
    "A": "ASME B16.34 Class 150", "B": "ASME B16.34 Class 300",
    "D": "ASME B16.34 Class 600", "E": "ASME B16.34 Class 900",
    "F": "ASME B16.34 Class 1500", "G": "ASME B16.34 Class 2500",
    "T": "N/A - Instrumentation Tubing Class",
}

# Design pressure per piping class (fallback when PMS data unavailable)
DESIGN_PRESSURE_FALLBACK = {
    "A1":   "19.6 @ -29\u00b0C, 13.8 @ 200\u00b0C",
    "B1":   "51.1 @ -29\u00b0C, 43.8 @ 200\u00b0C",
    "D1":   "102.1 @ -29\u00b0C, 87.6 @ 200\u00b0C",
    "E1":   "153.2 @ -29\u00b0C, 131.4 @ 200\u00b0C",
    "F1":   "255.3 @ -29\u00b0C, 219 @ 200\u00b0C",
    "G1":   "399.8 @ -29\u00b0C, 342.9 @ 200\u00b0C",
    "A2":   "19.6 @ -29\u00b0C, 13.8 @ 200\u00b0C",
    "A1N":  "19.6 @ -29\u00b0C, 13.8 @ 250\u00b0C",
    "B1N":  "51.1 @ -29\u00b0C, 43.8 @ 250\u00b0C",
    "D1N":  "102.1 @ -29\u00b0C, 87.6 @ 250\u00b0C",
    "E1N":  "153.2 @ -29\u00b0C, 131.4 @ 250\u00b0C",
    "F1N":  "255.3 @ -29\u00b0C, 219 @ 200\u00b0C",
    "G1N":  "399.8 @ -29\u00b0C, 342.9 @ 200\u00b0C",
    "A2N":  "19.6 @ -29\u00b0C, 13.8 @ 200\u00b0C",
    "B2N":  "51.1 @ -29\u00b0C, 43.8 @ 200\u00b0C",
    "D2N":  "102.1 @ -29\u00b0C, 87.6 @ 200\u00b0C",
    "E2N":  "153.2 @ -29\u00b0C, 131.4 @ 200\u00b0C",
    "F2N":  "255.3 @ -29\u00b0C, 219 @ 200\u00b0C",
    "G2N":  "399.8 @ -29\u00b0C, 342.9 @ 200\u00b0C",
    "A1LN": "19.6 @ -45\u00b0C, 13.8 @ 200\u00b0C",
    "B1LN": "51.1 @ -45\u00b0C, 43.8 @ 200\u00b0C",
    "D1LN": "102.1 @ -45\u00b0C, 87.6 @ 200\u00b0C",
    "E1LN": "153.2 @ -45\u00b0C, 131.4 @ 200\u00b0C",
    "F1LN": "255.3 @ -45\u00b0C, 219 @ 200\u00b0C",
    "G1LN": "399.8 @ -45\u00b0C, 342.9 @ 200\u00b0C",
    "A2LN": "19.6 @ -45\u00b0C, 13.8 @ 200\u00b0C",
    "B2LN": "51.1 @ -45\u00b0C, 43.8 @ 200\u00b0C",
    "D2LN": "102.1 @ -45\u00b0C, 87.6 @ 200\u00b0C",
    "E2LN": "153.2 @ -45\u00b0C, 131.4 @ 200\u00b0C",
    "F2LN": "255.3 @ -45\u00b0C, 219 @ 200\u00b0C",
    "G2LN": "399.8 @ -45\u00b0C, 342.9 @ 200\u00b0C",
    "A3":   "19.6 @ -29\u00b0C, 13.8 @ 200\u00b0C",
    "A4":   "19.6 @ -29\u00b0C, 13.8 @ 200\u00b0C",
    "B4":   "51.1 @ -29\u00b0C, 43.8 @ 200\u00b0C",
    "D4":   "102.1 @ -29\u00b0C, 87.6 @ 200\u00b0C",
    "A5":   "19.6 @ -29\u00b0C, 13.8 @ 200\u00b0C",
    "A6":   "19.6 @ -29\u00b0C, 13.8 @ 200\u00b0C",
    "A10":  "15.9 @ -100\u00b0C, 11.2 @ 200\u00b0C",
    "B10":  "41.4 @ -100\u00b0C, 29.2 @ 200\u00b0C",
    "D10":  "82.7 @ -100\u00b0C, 58.3 @ 200\u00b0C",
    "E10":  "124.1 @ -100\u00b0C, 87.5 @ 200\u00b0C",
    "F10":  "206.8 @ -100\u00b0C, 145.8 @ 200\u00b0C",
    "G10":  "344.7 @ -100\u00b0C, 243 @ 200\u00b0C",
    "A10N": "15.9 @ -100\u00b0C, 11.2 @ 200\u00b0C",
    "B10N": "41.4 @ -100\u00b0C, 29.2 @ 200\u00b0C",
    "D10N": "82.7 @ -100\u00b0C, 58.3 @ 200\u00b0C",
    "E10N": "124.1 @ -100\u00b0C, 87.5 @ 200\u00b0C",
    "F10N": "206.8 @ -100\u00b0C, 145.8 @ 200\u00b0C",
    "G10N": "344.7 @ -100\u00b0C, 243 @ 200\u00b0C",
    "A20N": "20 @ -46\u00b0C, 13.8 @ 200\u00b0C",
    "B20N": "51.7 @ -46\u00b0C, 42.7 @ 200\u00b0C",
    "D20N": "103.4 @ -46\u00b0C, 85.3 @ 200\u00b0C",
    "E20N": "155.1 @ -46\u00b0C, 128 @ 200\u00b0C",
    "F20N": "258.6 @ -46\u00b0C, 213.3 @ 200\u00b0C",
    "G20N": "430.9 @ -46\u00b0C, 355.4 @ 200\u00b0C",
    "A25":  "20 @ -46\u00b0C, 13.8 @ 200\u00b0C",
    "G25":  "430.9 @ -46\u00b0C, 355.4 @ 200\u00b0C",
    "A25N": "20 @ -46\u00b0C, 13.8 @ 200\u00b0C",
    "B25N": "51.7 @ -46\u00b0C, 42.7 @ 200\u00b0C",
    "D25N": "103.4 @ -46\u00b0C, 85.3 @ 200\u00b0C",
    "E25N": "155.1 @ -46\u00b0C, 128 @ 200\u00b0C",
    "F25N": "258.6 @ -46\u00b0C, 213.3 @ 200\u00b0C",
    "G25N": "430.9 @ -46\u00b0C, 355.4 @ 200\u00b0C",
    "A30":  "20 @ 0\u00b0C, 17.3 @ 100\u00b0C",
    "A31":  "20 @ 0\u00b0C, 17.3 @ 100\u00b0C",
    "A40":  "10 @ 0\u00b0C, 10 @ 93\u00b0C",
    "A41":  "10 @ 0\u00b0C, 10 @ 82\u00b0C",
    "A42":  "10 @ 32\u00b0C, 10 @ 65\u00b0C",
    "T50A": "125 @ 0\u00b0C, 116 @ 60\u00b0C",
    "T50B": "206 @ 0\u00b0C, 200 @ 60\u00b0C",
    "T50C": "325 @ 0\u00b0C, 325 @ 60\u00b0C",
    "T60A": "125 @ 0\u00b0C, 116 @ 60\u00b0C",
    "T60B": "206 @ 0\u00b0C, 200 @ 60\u00b0C",
    "T60C": "325 @ 0\u00b0C, 325 @ 60\u00b0C",
}

# Service per piping class (fallback when PMS data unavailable)
SERVICE_FALLBACK = {
    "A1":   "Cooling Water, HM, Diesel, Steam, WI, HC with low CO2 and H2S, Fresh Water, Hydraulic, Nitrogen, Exhaust, Fuel Oil, Tank Air Vent",
    "B1":   "Cooling Water, HM, Diesel, WI, HC with low CO2 and H2S, Steam, Hydraulic",
    "D1":   "Cooling Water, HM, Diesel, WI, HC with low CO2 and H2S, Steam, Hydraulic",
    "E1":   "Diesel, WI, HC with low CO2 and H2S, Steam, Hydraulic",
    "F1":   "Diesel, WI, HC with low CO2 and H2S, Steam, Hydraulic",
    "G1":   "HC with low CO2 and H2S, Steam, Hydraulic",
    "A2":   "Crude Oil",
    "A1N":  "Glycol, Flare Gas, HC service",
    "B1N":  "Glycol, Flare Gas, HC service",
    "D1N":  "Glycol, Flare Gas, HC service",
    "E1N":  "Glycol, Flare Gas, HC service",
    "F1N":  "Glycol, Flare Gas, HC service",
    "G1N":  "Glycol, Flare Gas, HC service",
    "A2N":  "Corrosive HC service",
    "B2N":  "Corrosive HC service",
    "D2N":  "Corrosive HC service",
    "E2N":  "Corrosive HC service",
    "F2N":  "Corrosive HC service",
    "G2N":  "Corrosive HC service",
    "A1LN": "Flare, Corrosive HC service (Low Temperature)",
    "B1LN": "Flare, Corrosive HC service (Low Temperature)",
    "D1LN": "Corrosive HC service (Low Temperature)",
    "E1LN": "Corrosive HC service (Low Temperature)",
    "F1LN": "Corrosive HC service (Low Temperature)",
    "G1LN": "Gas Lift, Corrosive HC service (Low Temperature)",
    "A2LN": "Corrosive HC service (Low Temperature)",
    "B2LN": "Corrosive HC service (Low Temperature)",
    "D2LN": "Corrosive HC service (Low Temperature)",
    "E2LN": "Corrosive HC service (Low Temperature)",
    "F2LN": "Corrosive HC service (Low Temperature)",
    "G2LN": "Corrosive HC service (Low Temperature)",
    "A3":   "Utility Water",
    "A4":   "Bilge, Drain, Sewage, Produced Water, CO2 Gas",
    "B4":   "Bilge, Drain, Sewage, Produced Water, CO2 Gas",
    "D4":   "Bilge, Drain, Sewage, Produced Water, CO2 Gas",
    "A5":   "Chemical penetration, Firewater penetration, Seawater penetration, Ballast, Inert Gas, COW/Tank Cleaning, Slop, Stripping, Seawater",
    "A6":   "Ballast, Inert Gas, COW/Tank Cleaning, Slop, Seawater, Firewater",
    "A10":  "Air, Nitrogen, Lube Oil, Chemical, Foam, Hydraulic, Instrument Air, Diesel Fuel",
    "B10":  "Air, Nitrogen, Lube Oil, Chemical, Foam, Hydraulic, Instrument Air, Diesel Fuel",
    "D10":  "Air, Nitrogen, Lube Oil, Chemical, Hydraulic",
    "E10":  "Air, Nitrogen, Lube Oil, Chemical, Hydraulic",
    "F10":  "Air, Nitrogen, Lube Oil, Chemical, Hydraulic",
    "G10":  "Air, Nitrogen, Lube Oil, Chemical, Hydraulic",
    "A10N": "Glycol, Corrosive HC service",
    "B10N": "Glycol, Corrosive HC service",
    "D10N": "Glycol, Corrosive HC service",
    "E10N": "Glycol, Corrosive HC service",
    "F10N": "Glycol, Corrosive HC service",
    "G10N": "Glycol, Corrosive HC service",
    "A20N": "Corrosive HC service",
    "B20N": "Corrosive HC service",
    "D20N": "Corrosive HC service",
    "E20N": "Corrosive HC service",
    "F20N": "Corrosive HC service",
    "G20N": "Corrosive HC service",
    "A25":  "Firewater, Raw Seawater, Topsides Seawater",
    "G25":  "Topside Seawater, Water Injection",
    "A25N": "Corrosive HC service",
    "B25N": "Corrosive HC service",
    "D25N": "Corrosive HC service",
    "E25N": "Corrosive HC service",
    "F25N": "Corrosive HC service",
    "G25N": "Corrosive HC service",
    "A30":  "Raw Sea Water, Fire Water",
    "A31":  "Potable Water",
    "A40":  "Raw Sea Water",
    "A41":  "Hypochlorite",
    "A42":  "Sewage, Hypochlorite",
    "T50A": "Chemical Injection (Except Hypochlorite) - 125 barg",
    "T50B": "Chemical Injection (Except Hypochlorite) - 206 barg",
    "T50C": "Chemical Injection (Except Hypochlorite) - 330 barg",
    "T60A": "Chemical Injection (Except Hypochlorite) - 125 barg",
    "T60B": "Chemical Injection (Except Hypochlorite) - 206 barg",
    "T60C": "Chemical Injection (Except Hypochlorite) - 330 barg",
}

SIZE_RANGE_FALLBACK = {
    "A1": '1/2" - 36"', "A1N": '1/2" - 32"', "A1LN": '1/2" - 30"',
    "A2": '1/2" - 30"', "A2N": '1/2" - 30"', "A2LN": '1/2" - 30"',
    "A3": '1/2" - 24"', "A4": '1/2" - 24"', "A5": '1/2" - 24"', "A6": '1/2" - 24"',
    "A10": '1/2" - 24"', "A10N": '1/2" - 24"',
    "A20N": '1/2" - 32"', "A25": '1/2" - 32"', "A25N": '1/2" - 32"',
    "A30": '1/2" - 28"', "A31": '1/2" - 4"',
    "A40": '1/2" - 40"', "A41": '1/2" - 6"', "A42": '1/2" - 8"',
    "B1": '1/2" - 24"', "B1N": '1/2" - 24"', "B1LN": '1/2" - 24"',
    "B2N": '1/2" - 24"', "B2LN": '1/2" - 24"', "B4": '1/2" - 24"',
    "B10": '1/2" - 24"', "B10N": '1/2" - 24"',
    "B20N": '1/2" - 32"', "B25N": '1/2" - 32"',
    "D1": '1/2" - 24"', "D1N": '1/2" - 24"', "D1LN": '1/2" - 24"',
    "D2N": '1/2" - 24"', "D2LN": '1/2" - 24"', "D4": '1/2" - 24"',
    "D10": '1/2" - 24"', "D10N": '1/2" - 24"',
    "D20N": '1/2" - 24"', "D25N": '1/2" - 24"',
    "E1": '1/2" - 24"', "E1N": '1/2" - 24"', "E1LN": '1/2" - 24"',
    "E2N": '1/2" - 24"', "E2LN": '1/2" - 24"',
    "E10": '1/2" - 24"', "E10N": '1/2" - 24"',
    "E20N": '1/2" - 24"', "E25N": '1/2" - 24"',
    "F1": '1/2" - 24"', "F1N": '1/2" - 24"', "F1LN": '1/2" - 24"',
    "F2N": '1/2" - 24"', "F2LN": '1/2" - 24"',
    "F10": '1/2" - 24"', "F10N": '1/2" - 24"',
    "F20N": '1/2" - 24"', "F25N": '1/2" - 24"',
    "G1": '1/2" - 24"', "G1N": '1/2" - 24"', "G1LN": '1/2" - 24"',
    "G2N": '1/2" - 24"', "G2LN": '1/2" - 24"',
    "G10": '1/2" - 12"', "G10N": '1/2" - 12"',
    "G20N": '1/2" - 18"', "G25": '1/2" - 24"', "G25N": '1/2" - 24"',
    "T50A": '1/2" - 1-1/2"', "T50B": '1/2" - 1-1/2"', "T50C": '1/2" - 1-1/2"',
    "T60A": '1/2" - 1-1/2"', "T60B": '1/2" - 1-1/2"', "T60C": '1/2" - 1-1/2"',
}

# Construction templates per valve type
CONSTRUCTION = {
    "BL": {
        "body_construction": 'Bi-Directional, One piece with Top entry (1-1/2" & below), Two piece split body (or) 3piece with Fully contained bolting , butt weld ball valves shall be top-entry design (2" and above), c/w vent and drain fitted with NPT plugs',
        "ball_construction": 'Floating (8" and below), Trunnion mounted (10" and above), no vent hole, Solid Type',
        "stem_construction": "Anti-static, Anti blowout proof type",
        "locks": "Valve lockable using padlock - Full Open, Fully Closed",
        "operation": 'Lever (4" and below), Gear operated c/w Hand wheel (6" and above) Fully enclosed, dust proof, with Position Indicator',
    },
    "BS": {
        "body_construction": 'Bi-Directional, One piece with Top entry (1-1/2" & below), Two piece split body (or) 3piece with Fully contained bolting , butt weld ball valves shall be top-entry design (2" and above), c/w vent and drain fitted with NPT plugs',
        "ball_construction": 'Floating (8" and below), Trunnion mounted (10" and above), no vent hole, Solid Type',
        "stem_construction": "Anti-static, Anti blowout proof type",
        "locks": "Valve lockable using padlock - Full Open, Fully Closed",
        "operation": 'Lever (4" and below), Gear operated c/w Hand wheel (6" and above) Fully enclosed, dust proof, with Position Indicator',
    },
    "BF": {
        "body_construction": "Wafer Type, Solid Fully Lugged, Threaded Lug",
        "disc_construction": "Rotating, Eccentric",
        "stem_construction": "Rotating, Blowout proof stem",
        "shaft_construction": "Strengthen, Blow out-Proof shaft, antistatic device",
        "seat_construction": "Double-offset seat",
        "operation": 'Lever Operated for 4" and below ; Gear box for 6" and above, Fully enclosed, dust proof, with Position Indicator',
    },
    "GA": {
        "body_construction": "Bolted bonnet, Integral Flanged End",
        "stem_construction": "Rising stem, outside screw and yoke, Back Seated",
        "back_seat_construction": "Renewable back seat",
        "packing_construction": "Bolted gland, Live-load packing, Renewable packing rings",
        "wedge_construction": "Solid wedge, One piece",
        "locks": "Valve lockable using padlock - Full Open, Fully Closed",
        "operation": 'Hand wheel, Non-rising (Gear for 14" and above, Fully enclosed, dust proof), with Position Indicator',
    },
    "GL": {
        "body_construction": "Bolted bonnet, Integral Flanged End",
        "stem_construction": "Rising stem, outside screw and yoke, Back Seated",
        "back_seat_construction": "Renewable back seat",
        "packing_construction": "Bolted gland, Live-load packing, Renewable packing rings",
        "disc_construction": "Ball / Plug Hard Faced",
        "operation": 'Hand wheel, non-rising (Gear for 8" and above, Fully enclosed, dust proof), with Position Indicator',
    },
    "CH_P": {
        "body_construction": "Integral Flanged, Bolted Cover",
        "seat_construction": "Spring assisted Metal to metal, Renewable Seat Ring",
        "operation": "Horizontal and vertical upward flow",
    },
    "CH_S": {
        "body_construction": "Integral Flanged End, Bolted Cover, Integral Hinge",
        "seat_construction": "Spring assisted Metal to metal, Renewable Seat Ring",
        "operation": "Horizontal and vertical upward flow",
    },
    "CH_D": {
        "body_construction": "Wafer Type, Solid Fully Lugged, Threaded Lug, Retainerless",
        "seat_construction": "Metal to metal, Renewable seat ring",
        "operation": "Spring assisted for horizontal and vertical upward flow",
    },
    "DB": {
        "body_construction": "Integral one piece body (Non-cartridge style)",
        "stem_construction": "Anti-static, Anti blowout proof type",
        "seat_construction": "Soft Seated, Self-energised, Self-relieving, Emergency sealant injection system",
        "locks": "Valve lockable using padlock - Full Open, Fully Closed",
        "operation": "Lever (Ball)/ T-Bar (Needle), with Position Indicator",
    },
    "NE": {
        "body_construction": "Integral body, straight or angle pattern, Outside Screw and Yoke (OS&Y) per PMS_PDF.pdf §6.5",
        "stem_construction": "Non-rotating stem tip, Outside Screw and Yoke (OS&Y), Back Seated",
        "operation": "Hand wheel / T-bar handle",
    },
}


def apply_bf_vms_construction_overrides(data: dict) -> None:
    """In-place: butterfly construction matches project datasheet grid (PMS appendix).

    Locks are not on this grid. ML/index may drift; re-apply canonical BF lines.
    """
    bf = CONSTRUCTION.get("BF") or {}
    data.pop("locks", None)
    for key in (
        "body_construction",
        "disc_construction",
        "stem_construction",
        "shaft_construction",
        "seat_construction",
    ):
        val = bf.get(key)
        if val:
            data[key] = val


# Seat material depends on seat type, not material category
SEAT_MATERIAL = {
    "M": "Metal seated, hard faced, Renewable",
    "P": "PEEK (max 200\u00b0C)",
    "T": "Reinforced PTFE (max 200\u00b0C)",
}

SEAT_CONSTRUCTION_BY_SEAT = {
    "M": "Metal Seated, Self-energised, Self-relieving, Emergency sealant injection system",
    "P": "Soft Seated, Self-energised, Self-relieving, Emergency sealant injection system",
    "T": "Soft Seated, Self-energised, Self-relieving, Emergency sealant injection system",
}

SEAL_MATERIAL_BALL = {"M": "Viton AED", "P": "Viton AED", "T": "PTFE"}
SEAL_MATERIAL_GATE = {"M": "Flexible Graphite", "T": "PTFE"}

# Project constants (same for every valve in FPSO Albacora)
PROJECT_CONSTANTS = {
    "marking_purchaser": "Hard marked with Valve Type on a stainless steel label, attached using tamper resistant stainless steel fastener, and with Unique Valve Tag Number",
    "marking_manufacturer": "MSS-SP-25",
    "inspection_testing": "ASME B16.34, API 598, BS EN 12266-1/2",
    "leakage_rate": "As per API 598",
    "pressure_testing_standards": "API STD 598, BS EN ISO 5208, BS 6755 (production pressure testing)",
    "pneumatic_test": "5.5 barg",
    "material_certification": "Pressure Retaining Parts BS EN 10204 Type 3.2, Other parts BS EN 10204 Type 3.1",
    "casting_quality_standard": "MSS SP-55 (Quality Standard for Steel Castings for Valves)",
    "flange_surface_finish": "Per ASME B46.1 / MSS SP-6 (Standard Finishes for Contact Faces)",
    "welding_procedure": "WPS per BS EN 288-2, PQR per BS EN 287-1, welding per ASME B31.3 / ASME SEC.IX",
    "finish": "General Specification for Paint and Protective Coating doc : XXX",
    "quality_system": "BS EN ISO 9001 compliant",
    "design_life": "15 years per PMS_PDF.pdf §6.8",
}


# ============================================================================
# END CONNECTION RESOLUTION
# ============================================================================

def _resolve_end_connection(end_conn: EndConnection, piping_class: str, cat: str,
                            size_inches: float | None = None,
                            pms_flange_face: str | None = None,
                            pms_flange_type: str | None = None,
                            pms_flange_std: str | None = None) -> str:
    """Derive the full end connection description from the end connection code.

    Per PMS_PDF.pdf §6.22:
      - Flanges ≤24" per ASME B16.5
      - Flanges 26"+ per ASME B16.47 Series A

    When the PMS sheet provides explicit flange data (face, type, standard) it
    wins over rule-derived values.
    """
    ec = end_conn.value
    letter = piping_class[0] if piping_class else "A"

    if pms_flange_std:
        flange_std = pms_flange_std
    else:
        flange_std = "ASME B16.5"
        if size_inches is not None and size_inches >= 26:
            flange_std = "ASME B16.47 Series A"

    if pms_flange_type and ec in ("R", "J", "F"):
        face_descriptor = pms_flange_face or {"R": "RF", "J": "RTJ", "F": "FF"}.get(ec, ec)
        return f"Flanged ({face_descriptor}) - {pms_flange_type}"

    if pms_flange_face and ec in ("R", "J", "F"):
        return f"Flanged {flange_std} ({pms_flange_face})"

    ec_map = {
        "R": f"Flanged {flange_std} RF (Raised Face)",
        "J": f"Flanged {flange_std} RTJ (Ring Type Joint)",
        "F": f"Flanged {flange_std} FF (Flat Face)",
        "W": "Butt Weld, ASME B16.25",
        "S": "Socket Weld, ASME B16.11",
        "H": "Hub Connector (Grayloc® / Techlok® / G-Lok® compatible), per NORSOK L-005",
        "T": "NPT Female, ASME B1.20.1",
        "JT": f"Flanged {flange_std} RTJ + NPT Female",
    }

    base = ec_map.get(ec, f"Flanged {flange_std} {ec}")

    if cat in ("CUNI",):
        base = base.replace(flange_std, "EEMUA 234")
    elif cat in ("GRE", "GRE_BONSTRAND"):
        base = base.replace(flange_std, "GRE Flange")
    elif cat in ("CPVC",):
        base = base.replace(flange_std, "CPVC Flange")

    pc_num_local = _PRESSURE_CLASS_NUM.get(letter, 150)
    if pc_num_local >= 1500 and size_inches is not None and size_inches >= 3:
        base += " (Compact Flanges / Hub Clamp Connector also acceptable per §6.22.1)"

    return base


# ============================================================================
# CORROSION ALLOWANCE
# ============================================================================

def _resolve_corrosion_allowance(cat: str, pms_value: str | None = None) -> str:
    """Resolve corrosion allowance — PMS value (project-specific) wins over category default."""
    if pms_value:
        s = str(pms_value).strip()
        if s.upper() in ("NIL", "NONE", "N/A", "-"):
            return "0 mm"
        if s and not any(c.isalpha() for c in s):
            return f"{s} mm"
        return s
    if cat in ("SS316L", "SS316L_NACE", "DSS", "SDSS", "SDSS_NACE"):
        return "0 mm (CRA material)"
    if cat in ("CUNI", "COPPER"):
        return "0 mm"
    if cat in ("GRE", "GRE_BONSTRAND", "CPVC"):
        return "0 mm (non-metallic piping)"
    if cat in ("TUBING_SS", "TUBING_6MO"):
        return "0 mm"
    return "3 mm"


# ============================================================================
# PMS DATA RESOLUTION (authoritative source for bolting, gaskets, hydrotest)
# ============================================================================

# --- Size range from synced PMS (valve_assignments / nps_sizes / pipe_schedule) ---

_NPS_INCH_LABEL_BY_VALUE: dict[float, str] = {
    0.125: "1/8", 0.25: "1/4", 0.375: "3/8", 0.5: "1/2", 0.625: "5/8",
    0.75: "3/4", 0.875: "7/8", 1.0: "1", 1.125: "1-1/8", 1.25: "1-1/4",
    1.375: "1-3/8", 1.5: "1-1/2", 1.625: "1-5/8", 1.75: "1-3/4", 1.875: "1-7/8",
    2.0: "2", 2.125: "2-1/8", 2.25: "2-1/4", 2.375: "2-3/8", 2.5: "2-1/2",
    2.625: "2-5/8", 2.75: "2-3/4", 2.875: "2-7/8", 3.0: "3",
}


def _normalize_pms_vds_code(code: str | None) -> str:
    if not code or not isinstance(code, str):
        return ""
    s = code.upper().strip()
    if s.startswith("VDS-"):
        s = s[4:].strip()
    return s


def _nps_inch_display(n: float) -> str:
    x = float(n)
    key = round(x, 4)
    label = _NPS_INCH_LABEL_BY_VALUE.get(key)
    if label is not None:
        return label
    if abs(key - round(key)) < 1e-6 and key >= 2:
        return str(int(round(key)))
    t = round(key, 3)
    if abs(t - int(t)) < 1e-6:
        return str(int(t))
    s = f"{t:.3f}".rstrip("0").rstrip(".")
    return s


def _size_range_display(lo: float, hi: float) -> str:
    return f'{_nps_inch_display(lo)}" - {_nps_inch_display(hi)}"'


def _iter_assignment_vds_codes(row: dict) -> list[str]:
    out: list[str] = []
    codes = row.get("vds_codes")
    if isinstance(codes, list):
        for c in codes:
            if isinstance(c, str) and c.strip():
                for part in c.split(","):
                    norm = _normalize_pms_vds_code(part)
                    if norm:
                        out.append(norm)
    one = row.get("vds_code")
    if isinstance(one, str) and one.strip():
        for part in one.split(","):
            norm = _normalize_pms_vds_code(part)
            if norm:
                out.append(norm)
    return list(dict.fromkeys(out))


def _pms_row_nps_bounds(row: dict) -> tuple[float, float] | None:
    try:
        lo = row.get("nps_min")
        hi = row.get("nps_max")
        if lo is None or hi is None:
            return None
        return float(lo), float(hi)
    except (TypeError, ValueError):
        return None


def _row_to_size_range(row: dict) -> str | None:
    b = _pms_row_nps_bounds(row)
    if not b:
        return None
    lo, hi = b
    return _size_range_display(lo, hi)


def _pick_assignment_row_by_size(rows: list[dict], size_inches: float | None) -> dict | None:
    if size_inches is None:
        return None
    try:
        sz = float(size_inches)
    except (TypeError, ValueError):
        return None
    for r in rows:
        b = _pms_row_nps_bounds(r)
        if b and b[0] <= sz <= b[1]:
            return r
    return None


def _pms_valve_assignment_tags(valve_type_code: str, design: str) -> list[str]:
    vt = (valve_type_code or "").upper()
    d = (design or "").upper()
    if vt in ("BL", "BS"):
        return ["BALL"]
    if vt == "BF":
        return ["BUTTERFLY"]
    if vt == "GA":
        return ["GATE"]
    if vt == "GL":
        return ["GLOBE"]
    if vt == "CH":
        if d == "P":
            return ["CHECK_PISTON"]
        return ["CHECK_SWING"]
    if vt == "DB":
        return ["DBB_PROCESS", "DBB_INST"]
    if vt == "NE":
        return ["NEEDLE", "NE", "INSTRUMENT_NEEDLE"]
    return []


def _select_dbb_assignment_row(rows: list[dict], size_inches: float | None) -> dict | None:
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    picked = _pick_assignment_row_by_size(rows, size_inches)
    if picked:
        return picked
    for r in rows:
        if r.get("valve_type") == "DBB_PROCESS":
            return r
    return rows[0]


def _size_range_from_valve_assignments(
    assignments: list[dict],
    raw_vds: str | None,
    valve_type_code: str,
    design: str,
    size_inches: float | None,
) -> str | None:
    if not assignments:
        return None
    norm = _normalize_pms_vds_code(raw_vds)
    vmatch: list[dict] = []
    for row in assignments:
        if not isinstance(row, dict):
            continue
        if norm and norm in _iter_assignment_vds_codes(row):
            vmatch.append(row)
    if len(vmatch) > 1:
        row = _pick_assignment_row_by_size(vmatch, size_inches) or vmatch[0]
        return _row_to_size_range(row)
    if len(vmatch) == 1:
        return _row_to_size_range(vmatch[0])

    tags = _pms_valve_assignment_tags(valve_type_code, design)
    if not tags:
        return None
    family = [r for r in assignments if isinstance(r, dict) and r.get("valve_type") in tags]
    if not family:
        return None
    if valve_type_code.upper() == "DB":
        row = _select_dbb_assignment_row(family, size_inches)
    elif len(family) > 1:
        row = _pick_assignment_row_by_size(family, size_inches) or family[0]
    else:
        row = family[0]
    return _row_to_size_range(row) if row else None


def _size_range_from_pipe_schedule(rows: list[dict]) -> str | None:
    if not rows:
        return None
    sizes: list[float] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        n = r.get("nps_inch")
        if n is None:
            continue
        try:
            sizes.append(float(n))
        except (TypeError, ValueError):
            continue
    if not sizes:
        return None
    return _size_range_display(min(sizes), max(sizes))


def _dbb_is_instrument_isolation(
    decoded: DecodedVDS,
    valve_assignments: list | None = None,
) -> bool:
    """Instrumentation / tubing DBB — omit separate elastomer *seal_material* row."""
    if (decoded.design or "").upper() == "P":
        return True
    pc = (decoded.piping_class or "").upper().strip()
    if re.match(r"^T\d", pc):
        return True
    vnorm = _normalize_pms_vds_code(decoded.raw_vds)
    if not vnorm:
        return False
    for row in valve_assignments or []:
        if not isinstance(row, dict):
            continue
        if row.get("valve_type") != "DBB_INST":
            continue
        if vnorm in _iter_assignment_vds_codes(row):
            return True
    return False


def _select_flange_for_size(flanges: list, size_inches: float | None):
    """Pick the flange entry whose NPS range covers ``size_inches``."""
    if not flanges:
        return None
    if size_inches is None or len(flanges) == 1:
        return flanges[0]
    for fl in flanges:
        lo = fl.nps_min if fl.nps_min is not None else 0.0
        hi = fl.nps_max if fl.nps_max is not None else 9999.0
        if lo <= float(size_inches) <= hi:
            return fl
    return flanges[0]


def _hydrotest_pressures_barg_from_spec(spec) -> tuple[float, float] | None:
    """Return (shell_test_barg, closure_test_barg) from PMS (same logic as app)."""
    dp: float | None = None
    if spec.index_row and spec.index_row.design_pressure_barg is not None:
        try:
            dp = float(spec.index_row.design_pressure_barg)
        except (TypeError, ValueError):
            dp = None
    if dp is None and spec.header.design_pressure_barg is not None:
        try:
            dp = float(spec.header.design_pressure_barg)
        except (TypeError, ValueError):
            dp = None

    shell: float | None = None
    if spec.index_row and spec.index_row.hydrotest_barg is not None:
        try:
            shell = float(spec.index_row.hydrotest_barg)
        except (TypeError, ValueError):
            shell = None
    if shell is None and spec.header.hydrotest_pressure_barg is not None:
        try:
            shell = float(spec.header.hydrotest_pressure_barg)
        except (TypeError, ValueError):
            shell = None
    if shell is None and dp is not None:
        shell = round(dp * 1.5, 2)

    if shell is None:
        return None

    if dp is not None:
        closure = round(dp * 1.1, 2)
    else:
        closure = round((shell / 1.5) * 1.1, 2)

    return round(shell, 2), closure


def _resolve_from_pms(
    piping_class: str,
    cat: str,
    is_rtj: bool,
    size_inches: float | None = None,
    raw_vds: str | None = None,
    valve_type: str = "",
    design: str = "",
) -> dict:
    """Resolve datasheet fields from PMS data (authoritative when present)."""
    pms_fields = {}
    try:
        pms = get_pms_loader()
        spec = pms.get_spec(piping_class)
    except (FileNotFoundError, Exception):
        return pms_fields

    if not spec:
        return pms_fields

    if spec.bolting_gaskets:
        if spec.bolting_gaskets.stud_bolt_spec:
            pms_fields["bolts"] = spec.bolting_gaskets.stud_bolt_spec
        if spec.bolting_gaskets.hex_nut_spec:
            pms_fields["nuts"] = spec.bolting_gaskets.hex_nut_spec
        if spec.bolting_gaskets.gasket_spec:
            pms_fields["gaskets"] = spec.bolting_gaskets.gasket_spec

    if spec.index_row:
        if spec.index_row.design_pressure_barg:
            dp = spec.index_row.design_pressure_barg
            min_temp = spec.index_row.min_temp_c
            bps = spec.index_row.pt_breakpoints or []
            if bps and min_temp is not None:
                last_bp = bps[-1] if len(bps) > 1 else bps[0]
                pms_fields["design_pressure"] = (
                    f"{dp} @ {int(min_temp)}\u00b0C, "
                    f"{last_bp['press_barg']} @ {last_bp['temp_c']}\u00b0C"
                )

        if spec.index_row.min_temp_c is not None:
            pms_fields["min_design_temp"] = f"{int(spec.index_row.min_temp_c)}°C"

    if "design_pressure" not in pms_fields and spec.header.design_pressure_barg:
        pms_fields["design_pressure"] = f"{spec.header.design_pressure_barg} barg"

    _ht = _hydrotest_pressures_barg_from_spec(spec)
    if _ht:
        _shell, _closure = _ht
        pms_fields["hydrotest_shell"] = f"{_shell} barg"
        pms_fields["hydrotest_closure"] = f"{_closure} barg"

    if spec.header.service:
        pms_fields["service"] = spec.header.service

    if spec.header.corrosion_allowance:
        pms_fields["corrosion_allowance"] = spec.header.corrosion_allowance

    if spec.header.design_code:
        pms_fields["design_code"] = spec.header.design_code

    if spec.header.valve_rating_label:
        pms_fields["pressure_class_label"] = spec.header.valve_rating_label

    if spec.header.nace_flag:
        pms_fields["nace_flag"] = True
    if spec.header.lt_flag:
        pms_fields["lt_flag"] = True

    if spec.header.material_description:
        pms_fields["material_class"] = spec.header.material_description

    if spec.flanges:
        fl = _select_flange_for_size(spec.flanges, size_inches)
        if fl:
            if fl.flange_face:
                pms_fields["flange_face"] = fl.flange_face
            if fl.flange_moc:
                pms_fields["flange_moc"] = fl.flange_moc
            if fl.flange_type:
                pms_fields["flange_type"] = fl.flange_type
                m = re.search(r"ASME\s*B\s*16\.\d+(?:\s*Series\s*[A-Z])?", fl.flange_type)
                if m:
                    pms_fields["flange_std"] = m.group(0)

    # Size range — valve row for this VDS / type, else class NPS table, else pipe
    sr_assign = _size_range_from_valve_assignments(
        spec.valve_assignments, raw_vds, valve_type, design, size_inches,
    )
    if sr_assign:
        pms_fields["size_range"] = sr_assign
    elif spec.nps_sizes:
        sz_list: list[float] = []
        for s in spec.nps_sizes:
            n = s.get("nps_inch")
            if n is None:
                continue
            try:
                sz_list.append(float(n))
            except (TypeError, ValueError):
                continue
        sizes = sorted(set(sz_list))
        if sizes:
            pms_fields["size_range"] = _size_range_display(sizes[0], sizes[-1])
    elif spec.pipe_schedule:
        sr_pipe = _size_range_from_pipe_schedule(spec.pipe_schedule)
        if sr_pipe:
            pms_fields["size_range"] = sr_pipe

    return pms_fields


# ============================================================================
# HYDROTEST CALCULATION (fallback when PMS has no hydrotest data)
# ============================================================================

def _calc_hydrotest(design_pressure_str: str) -> tuple[str, str]:
    """Calculate hydrotest shell & closure from design pressure string."""
    try:
        first_val = float(design_pressure_str.split("@")[0].strip())
        shell = round(first_val * 1.5, 2)
        closure = round(first_val * 1.1, 2)
        return f"{shell} barg", f"{closure} barg"
    except (ValueError, IndexError):
        return "-", "-"


# ============================================================================
# SIZE-DEPENDENT ENGINEERING RULES (PMS_PDF.pdf)
# ============================================================================

# Ball valve: Floating vs Trunnion thresholds
_BALL_MOUNTING = {
    150: {"max_floating": 8, "min_trunnion": 10},
    300: {"max_floating": 4, "min_trunnion": 6},
    600: {"max_floating": 1.5, "min_trunnion": 2},
    900: {"max_floating": 0, "min_trunnion": 0},
    1500: {"max_floating": 0, "min_trunnion": 0},
    2500: {"max_floating": 0, "min_trunnion": 0},
}

# Gearbox thresholds (min size for gear operation)
_GEARBOX = {
    "BL": {150: 6, 300: 6, 600: 4, 900: 3, 1500: 3, 2500: 3},
    "BS": {150: 6, 300: 6, 600: 4, 900: 3, 1500: 3, 2500: 3},
    "BF": {150: 6, 300: 6},
    "GA": {150: 14, 300: 14, 600: 12, 900: 6, 1500: 3, 2500: 3},
    "GL": {150: 10, 300: 8, 600: 6, 900: 6, 1500: 3, 2500: 3},
}

# Sealant injection thresholds (min size)
_SEALANT_INJECTION = {150: 10, 300: 6, 600: 2, 900: 0, 1500: 0, 2500: 0}

_PRESSURE_CLASS_NUM = {"A": 150, "B": 300, "D": 600, "E": 900, "F": 1500, "G": 2500}

# NDT RT extent by pressure class and DN threshold (inches)
_NDT_EXTENT = {
    150: [(24, "25%"), (999, "100%")],      # DN<=600 (24") -> 25%, above -> 100%
    300: [(16, "25%"), (999, "100%")],       # DN<=400 (16") -> 25%, above -> 100%
    600: [(0, "100%")],
    900: [(0, "100%")],
    1500: [(0, "100%")],
    2500: [(0, "100%")],
}


def _resolve_ball_mounting(size_inches: float | None, pressure_class: int) -> dict:
    """Determine floating vs trunnion mounting per PMS_PDF.pdf Clause 5."""
    thresholds = _BALL_MOUNTING.get(pressure_class, _BALL_MOUNTING[150])
    max_float = thresholds["max_floating"]

    if max_float == 0:
        # All trunnion for 900+
        return {
            "type": "Trunnion",
            "description": f"Trunnion Mounted (Class {pressure_class} - all sizes)",
        }

    if size_inches is None:
        return {
            "type": "Mixed",
            "description": f'Floating ({max_float}" and below), Trunnion mounted ({thresholds["min_trunnion"]}" and above)',
        }

    if size_inches <= max_float:
        return {"type": "Floating", "description": f"Floating Ball ({size_inches}\")"}
    return {"type": "Trunnion", "description": f"Trunnion Mounted ({size_inches}\")"}


def _resolve_operation(vt: str, size_inches: float | None, pressure_class: int) -> str:
    """Compute operation method per PMS_PDF.pdf Clause 9."""
    gear_table = _GEARBOX.get(vt, {})
    gear_min = gear_table.get(pressure_class)

    if vt in ("BL", "BS"):
        if size_inches is not None and gear_min is not None and size_inches >= gear_min:
            return f'Gear operated c/w Handwheel ({size_inches}" >= {gear_min}" threshold), Fully enclosed, dust proof, with Position Indicator'
        if size_inches is not None and size_inches <= 4:
            return f'Lever ({size_inches}"), with Position Indicator'
        return 'Lever (4" and below), Gear operated c/w Handwheel (6" and above), Fully enclosed, dust proof, with Position Indicator'

    if vt == "BF":
        if size_inches is not None and gear_min is not None and size_inches >= gear_min:
            return f'Gear operated ({size_inches}" >= {gear_min}" threshold), Fully enclosed, dust proof, with Position Indicator'
        return 'Lever Operated for 4" and below; Gear box for 6" and above, Fully enclosed, dust proof, with Position Indicator'

    if vt == "GA":
        if size_inches is not None and gear_min is not None and size_inches >= gear_min:
            return f'Gear operated c/w Hand wheel ({size_inches}" >= {gear_min}" threshold), Fully enclosed, dust proof, with Position Indicator'
        return f'Hand wheel, Non-rising (Gear for {gear_min}" and above, Fully enclosed, dust proof), with Position Indicator'

    if vt == "GL":
        if size_inches is not None and gear_min is not None and size_inches >= gear_min:
            return f'Gear operated c/w Hand wheel ({size_inches}" >= {gear_min}" threshold), Fully enclosed, dust proof, with Position Indicator'
        return f'Hand wheel, non-rising (Gear for {gear_min}" and above, Fully enclosed, dust proof), with Position Indicator'

    if vt == "DB":
        return "Lever (Ball) / T-Bar (Needle), with Position Indicator"

    if vt == "NE":
        return "Handwheel / T-bar handle"

    return CONSTRUCTION.get(vt, {}).get("operation", "Handwheel")


def _resolve_ndt_extent(pressure_class: int, size_inches: float | None, cat: str) -> str:
    """Determine NDT/RT inspection extent per PMS_PDF.pdf Clause 15."""
    # NACE / SS / alloys always 100%
    if cat in ("CS_NACE", "LTCS_NACE", "SS316L", "SS316L_NACE", "DSS",
               "SDSS", "SDSS_NACE", "CUNI", "COPPER"):
        return "100% RT per ASME B16.34 Annexure B (alloy / NACE material)"

    extents = _NDT_EXTENT.get(pressure_class, [(0, "100%")])
    if size_inches is not None:
        for max_size, extent in extents:
            if size_inches <= max_size:
                return f"{extent} RT per ASME B16.34 Annexure B"
    return f"Per ASME B16.34 Annexure B (provide size for exact extent)"


def _resolve_extended_stem(size_inches: float | None) -> str:
    """Return extended stem requirement for insulated lines per PMS_PDF.pdf Clause 10."""
    if size_inches is None:
        return '75mm (1/2"-1-1/2"), 100mm (2"-6"), 150mm (8" and above) — if insulated line'
    if size_inches <= 1.5:
        return "75 mm extension (for insulated lines)"
    if size_inches <= 6:
        return "100 mm extension (for insulated lines)"
    return "150 mm extension (for insulated lines)"


def _resolve_wedge_type(size_inches: float | None) -> str:
    """Gate valve wedge type per PMS_PDF.pdf Clause 6."""
    if size_inches is None:
        return 'Solid wedge (1-1/2" and below), Flexible wedge (2" and above)'
    if size_inches <= 1.5:
        return "Solid wedge, One piece"
    return "Flexible wedge"


# Item-4 forged-part noun per valve type for the standard footer-notes block.
_FORGED_PART_BY_VALVE_TYPE = {
    "BL": "Ball",
    "BS": "Ball",
    "DB": "Ball",
    "GA": "Wedge",
    "BF": "Disc",
    "CH": "Disc",
    "GL": "Disc",
    "NE": "Needle",
}


def build_footer_notes(valve_type: str, is_nace: bool) -> list[str]:
    """Standard datasheet footer notes block.

    Six notes for NACE valves, five for non-NACE (NACE compliance note dropped).
    Item 4 noun varies by valve type (Ball / Wedge / Disc / Needle).
    """
    forged_part = _FORGED_PART_BY_VALVE_TYPE.get(valve_type, "Disc")
    notes = [
        "This data sheet shall be completed and returned with the quotation. "
        "Failure to return the completed data sheet will deem the offer technically not acceptable.",
        "Data sheet shall be read in conjunction with Piping Material Specification, "
        "Doc No. 40801-SPE-80000-PP-SP-0001.",
        "Hydrostatic shell test pressure shall be 1.5 times of Max. design pressure, "
        "and hydraulic seat test shall be 1.1 times of Max. design pressure for seats.",
        f"{forged_part}, Stem and Gland material shall be forged, Castings are not acceptable.",
        "All stud bolts and nuts shall be XYLAR 2 + XYLAN 1070 coated with minimum "
        "combined thickness of 50\u03bcm.",
    ]
    if is_nace:
        notes.append("Valve shall be in accordance with NACE MR0175 /ISO 15156-1/2/3.")
    return notes


def footer_notes_as_text(valve_type: str, is_nace: bool) -> str:
    """Return the footer notes as a single numbered multi-line string."""
    items = build_footer_notes(valve_type, is_nace)
    return "\n".join(f"{i}. {note}" for i, note in enumerate(items, start=1))


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def generate_datasheet(decoded: DecodedVDS, size_inches: float | None = None) -> dict[str, str]:
    """Generate a complete valve datasheet from a decoded VDS using engineering rules.

    This is the core intelligence of the system. Instead of looking up a static
    index, it derives every field from first principles:
      - Material category from piping class
      - Body/ball/stem/gland materials from material category
      - Construction from valve type
      - Bolting/gaskets/hydrotest from PMS data (authoritative) or rules (fallback)
      - Standards and constants from project requirements
      - Size-dependent rules from PMS_PDF.pdf

    Args:
        decoded: A DecodedVDS object from vds_decoder.decode_vds()
        size_inches: Optional valve size for size-dependent rules

    Returns:
        Flat dict of field_name -> value, ready to populate a datasheet card.
    """
    _rt = get_reference_tables()
    vt = decoded.valve_type.value     # e.g. "BL"
    design = decoded.design            # e.g. "R" (reduced bore)
    seat = decoded.seat_type.value if decoded.seat_type else "M"
    pc = decoded.piping_class          # e.g. "A1N"
    ec = decoded.end_connection        # EndConnection enum
    is_nace = decoded.is_nace
    is_lt = decoded.is_low_temp
    is_rtj = ec == EndConnection.RTJ or ec == EndConnection.RTJ_NPT

    try:
        get_pms_loader().refresh_spec_from_backend(pc)
    except Exception:
        pass

    # Material category drives most material selections. Resolve it after the
    # PMS refresh so project header data can override legacy code-number maps.
    cat = _get_material_category(pc)

    # Pressure class letter and number
    pc_letter = pc[0] if pc else "A"
    pc_num = _PRESSURE_CLASS_NUM.get(pc_letter, 150)

    # ── Resolve PMS data first (authoritative) ──
    pms = _resolve_from_pms(
        pc,
        cat,
        is_rtj,
        size_inches=size_inches,
        raw_vds=decoded.raw_vds,
        valve_type=vt,
        design=design,
    )

    if pms.get("nace_flag"):
        is_nace = True
    if pms.get("lt_flag"):
        is_lt = True

    _spec_for_class = None
    try:
        _spec_for_class = get_pms_loader().get_spec(pc)
    except Exception:
        _spec_for_class = None
    _valve_assignments = (
        list(_spec_for_class.valve_assignments)
        if _spec_for_class and _spec_for_class.valve_assignments
        else []
    )
    _dbb_inst = _dbb_is_instrument_isolation(decoded, _valve_assignments) if vt == "DB" else False
    _pms_mat = _spec_for_class.materials if _spec_for_class and _spec_for_class.materials else None

    # ── Build the datasheet ──
    data: dict[str, str] = {}

    # Header / identification
    data["vds_no"] = decoded.display_vds
    data["valve_type"] = VALVE_TYPE_DESCRIPTION.get((vt, design), f"{vt} Valve, design {design}")
    data["piping_class"] = pc

    # Service & size — PMS first, then fallback
    data["service"] = pms.get("service", SERVICE_FALLBACK.get(pc, ""))
    data["size_range"] = pms.get("size_range", SIZE_RANGE_FALLBACK.get(pc, '1/2" - 24"'))

    # Standards — context-dependent selection per VMS §6.1, §6.2
    if vt == "GA" and cat in ("SS316L", "SS316L_NACE", "DSS", "SDSS", "SDSS_NACE"):
        # API STD 603 for corrosion-resistant gate valves (VMS §6.2)
        data["valve_standard"] = _rt.get("valve_standard", "GA_CRA")
    elif vt in ("BL", "BS") and seat == "M":
        # API STD 608 for metal ball valves (VMS §4.3)
        data["valve_standard"] = _rt.get("valve_standard", "BL_METAL")
    elif vt in ("BL", "BS"):
        # ISO 17292 only up to 24", CL 600 and below; above that API 6D (VMS §6.1)
        if size_inches is not None and (size_inches > 24 or pc_num > 600):
            data["valve_standard"] = "API SPEC 6D / ISO 14313"
        else:
            data["valve_standard"] = _rt.lookup("valve_standard", vt, design)
    else:
        data["valve_standard"] = _rt.lookup("valve_standard", vt, design)
    data["pressure_class"] = pms.get("pressure_class_label") or _rt.get("pressure_class", pc_letter)

    # Design pressure — PMS first, then fallback
    data["design_pressure"] = pms.get("design_pressure", DESIGN_PRESSURE_FALLBACK.get(pc, ""))

    data["corrosion_allowance"] = _resolve_corrosion_allowance(cat, pms.get("corrosion_allowance"))

    # NACE / sour service / low temp
    if is_nace:
        data["sour_service"] = "NACE MR0175 / ISO 15156 compliant"
        data["nace_compliant"] = "Yes"
    else:
        data["sour_service"] = "-"
        data["nace_compliant"] = "No"

    if vt == "GA" and is_nace:
        data["sour_service"] = "NACE MR0175 /ISO 15156-1/2/3, SSC Region 3, Non-exposed, internal only"

    if is_lt:
        data["low_temperature"] = "Yes - Impact tested"
        _default_lt_temp = "-46\u00b0C" if cat in ("DSS", "SDSS", "SDSS_NACE") else "-45\u00b0C"
        data["min_design_temp"] = pms.get("min_design_temp") or _default_lt_temp
    else:
        data["low_temperature"] = "No"
        _default_temp = "-29\u00b0C" if cat.startswith("CS") else "-100\u00b0C" if cat.startswith("SS") else "-46\u00b0C"
        data["min_design_temp"] = pms.get("min_design_temp") or _default_temp

    data["design_code"] = pms.get("design_code") or "ASME B31.3"

    if pms.get("material_class"):
        data["material_class"] = pms["material_class"]

    data["end_connections"] = _resolve_end_connection(
        ec, pc, cat, size_inches,
        pms_flange_face=pms.get("flange_face"),
        pms_flange_type=pms.get("flange_type"),
        pms_flange_std=pms.get("flange_std"),
    )

    if pms.get("flange_moc"):
        data["flange_material"] = pms["flange_moc"]

    # Face to face
    data["face_to_face"] = _rt.lookup("face_to_face", vt, design)

    # ── Construction (from valve type template) ──
    tmpl_key = f"{vt}_{design}" if vt == "CH" else vt
    tmpl = CONSTRUCTION.get(tmpl_key, CONSTRUCTION.get(vt, {}))
    for field, value in tmpl.items():
        data[field] = value

    # ── Size-dependent construction (PMS_PDF.pdf) ──
    if vt in ("BL", "BS"):
        mounting = _resolve_ball_mounting(size_inches, pc_num)
        data["ball_construction"] = f'{mounting["description"]}, no vent hole, Solid Type'
        data["ball_mounting_type"] = mounting["type"]
        if mounting["type"] == "Trunnion":
            data["dbb_feature"] = "Double Block and Bleed capability"
            data["seat_loading"] = "Spring-loaded seat rings"
            data["body_vent_drain"] = "Body vent and drain fitted with NPT threaded plugs"
            sealant_min = _SEALANT_INJECTION.get(pc_num, 0)
            if size_inches is None or size_inches >= sealant_min:
                data["sealant_injection"] = "Seat sealant injection system fitted"
        elif mounting["type"] == "Floating":
            data["body_cavity_relief"] = "Body cavity pressure relief required"

    if vt == "GA":
        data["wedge_construction"] = _resolve_wedge_type(size_inches)

    if vt == "DB" and size_inches is not None and not _dbb_inst:
        if size_inches <= 2:
            data["body_construction"] = "One-piece forged body, integral construction"
            data["dbb_end_connection"] = 'Flange x 1/2" NPT'
        else:
            data["body_construction"] = "Three-piece bolted body"
            data["dbb_end_connection"] = "Flanged both ends"

    # Check valve: piston type required for small bore 1/2"-1.5" per VMS §6.2
    if vt == "CH" and size_inches is not None and size_inches <= 1.5:
        data["body_construction"] = "Integral Flanged, Bolted Cover (Piston Type required for 1/2\"-1-1/2\")"
        data["seat_construction"] = "Spring assisted Metal to metal, Renewable Seat Ring"
        data["operation"] = "Horizontal installation only (piston type check valve)"
        data["check_valve_note"] = "Small bore check valves (1/2\"-1-1/2\") SHALL be Piston Type, horizontal only per PMS_PDF.pdf §6.2"

    if vt == "DB" and _dbb_inst:
        data["body_construction"] = (
            "Integral forged instrument double-block-and-bleed pattern per API 6D / "
            "project tubing-class PMS; vent and bleed connections per manufacturer."
        )
        data["seat_construction"] = (
            "Primary seating per seat material column; stem and packing seals per "
            "manufacturer's instrument block design (no separate body elastomer seal on this sheet)."
        )
        data.pop("dbb_end_connection", None)

    # End flange class/face table per VMS §6.22.1
    if ec in (EndConnection.RF, EndConnection.RTJ, EndConnection.FF):
        if pc_num <= 600:
            data["flange_face_note"] = f"CL {pc_num}: Raised Face (RF) per PMS_PDF.pdf §6.22.1"
        else:
            data["flange_face_note"] = f"CL {pc_num}: Ring Type Joint (RTJ) per PMS_PDF.pdf §6.22.1"

    data["operation"] = _resolve_operation(vt, size_inches, pc_num)

    # Body form
    if size_inches is not None and size_inches <= 1.5:
        data["body_form"] = "Forged"
    elif size_inches is not None:
        data["body_form"] = "Cast or Forged"
    else:
        data["body_form"] = 'Forged (1-1/2" and below), Cast or Forged (2" and above)'

    # ── Materials — PMS ``materials`` block first, then category rules (same as app) ──
    body_mat = (_pms_mat.body_material if _pms_mat else None) or _rt.get("body_material", cat)
    if vt == "BF" and cat in ("SS316L", "SS316L_NACE") and not (_pms_mat and _pms_mat.body_material):
        body_mat = _BF_BODY_SS316L
    if size_inches is not None and size_inches <= 1.5 and vt != "BF":
        parts = body_mat.split("/")
        forged_parts = [p.strip() for p in parts if "forged" in p.lower()]
        if forged_parts:
            body_mat = forged_parts[0]
    data["body_material"] = body_mat
    data["stem_material"] = _stem_trim_row(
        cat,
        (_pms_mat.stem_material if _pms_mat else None),
        is_nace=is_nace,
        is_lt=is_lt,
    )
    data["gland_material"] = (_pms_mat.gland_material if _pms_mat else None) or _rt.get("gland_material", cat)
    data["gland_packing"] = (_pms_mat.gland_packing if _pms_mat else None) or _rt.get("gland_packing", cat)
    if vt == "BF" and not (_pms_mat and _pms_mat.gland_packing):
        data["gland_packing"] = _GLAND_PACKING_BF
    data["lever_handwheel"] = (_pms_mat.lever_handwheel if _pms_mat else None) or "Solid ASTM A47 HDG/ ASTM A220 HDG/ SS316"
    _pms_spring = _pms_mat.spring_material if _pms_mat else None
    # Spring row: ball / check / globe only; BF / DB / NE have no spring trim line on VMS.
    if vt == "BF":
        pass
    elif vt in ("BL", "BS", "CH", "GL"):
        data["spring_material"] = _pms_spring or "Inconel 750"
    elif _pms_spring and vt not in ("NE", "DB", "BF"):
        data["spring_material"] = _pms_spring

    if vt in ("BL", "BS", "DB"):
        data["ball_material"] = (_pms_mat.ball_material if _pms_mat else None) or _rt.get("ball_material", cat)
        data["seat_material"] = (_pms_mat.seat_material if _pms_mat else None) or _rt.get("seat_material", seat)
        if vt in ("BL", "BS"):
            data["seal_material"] = _rt.get("seal_material_ball", seat)
        if vt != "DB":
            data["seat_construction"] = _rt.get("seat_construction_by_seat", seat)
        if seat == "M" and vt in ("BL", "BS"):
            data["seat_coating"] = "Tungsten Carbide overlay, min 1050 HV, 150-250 \u03bcm thickness"
            if cat.startswith("CS"):
                data["hardness_requirement"] = "Body/disc min 250 BHN, min 50 BHN differential"
            data["stellite_overlay"] = "Stellite 6 by deposition, min 1.6 mm finished thickness"
    elif vt == "GA":
        data["wedge_material"] = _rt.get("body_material", cat) + ", Hard faced"
        data["seat_material"] = _rt.get("seat_material", seat)
        data["seal_material"] = _rt.get("seal_material_gate", seat)
        if cat.startswith("CS") and seat == "M":
            data["hardness_requirement"] = "Body seat and wedge min 250 BHN, min 50 BHN differential"
    elif vt == "GL":
        data["disc_material"] = data["stem_material"] + ", Hard faced"
        data["seat_material"] = (
            (_pms_mat.seat_material if _pms_mat else None)
            or _rt.get("seat_material", seat)
        )
        data["seal_material"] = _rt.get("seal_material_gate", seat)
        if cat.startswith("CS") and seat == "M":
            data["hardness_requirement"] = (
                "Body seat and disc min 250 BHN, min 50 BHN differential"
            )
    elif vt == "CH":
        data["disc_material"] = _rt.get("stem_material", cat)
        data["seat_material"] = _rt.get("seat_material", seat)
        data["seal_material"] = _rt.get("seal_material_gate", seat)
        if design == "S":
            data["hinge_pin_material"] = _rt.get("stem_material", cat)
        if cat in ("CS", "CS_NACE"):
            data["cover_material"] = "Forged - ASTM A105N"
            data["material_cover_material"] = "Forged - ASTM A105N"
    elif vt == "BF":
        data["shaft_material"] = _stem_trim_row(
            cat,
            (_pms_mat.stem_material if _pms_mat else None),
            is_nace=is_nace,
            is_lt=is_lt,
        )
        # Butterfly material grid: disc + seal rows align with PMS appendix / VDS index pattern.
        data["disc_material"] = data["shaft_material"] + ", Stellite Hard Faced"
        data["seal_material"] = _rt.get("seal_material_ball", seat)
        _seat_bf = (_pms_mat.seat_material if _pms_mat else None) or _rt.get("seat_material", seat)
        if seat == "T" and not (_pms_mat and _pms_mat.seat_material):
            _seat_bf = "Reinforced PTFE"
        data["seat_material"] = _seat_bf
    elif vt == "NE":
        data["needle_material"] = _rt.get("stem_material", cat)
        data["seat_material"] = _rt.get("seat_material", seat)
        data["minimum_bore"] = "10 mm (instrument connections)"
        data["trim_material"] = data.get("stem_material", "")

    # Butterfly: the PMS appendix has BOTH Stem Material and Shaft Material rows
    # (typically same value). Keep both; only spring isn't on the BF grid.
    if vt == "BF":
        data.pop("spring_material", None)

    # Backseat for GA, GL, NE
    if vt in ("GA", "GL", "NE"):
        data["backseat"] = "Back seated, renewable"

    if vt in ("GA", "GL", "NE"):
        data["back_seat_material"] = f'{data["stem_material"]}, Stellite Hard Faced'

    # Seat pocket CRA overlay in corrosive service (VMS §6.15)
    if vt in ("GA", "GL", "CH") and is_nace and cat.startswith("CS"):
        data["seat_pocket_overlay"] = (
            "Body seat pockets overlayed with corrosion resistant material "
            "per PMS_PDF.pdf §6.15 (CS valve in corrosive service)"
        )

    # Elastomer explosive decompression resistance (VMS §7.9)
    if is_nace or cat in ("CS_NACE", "LTCS_NACE"):
        data["elastomer_requirement"] = (
            "All elastomers in HC gas/liquid service with H\u2082, CH\u2084, or CO\u2082 "
            "shall have proven resistance to explosive decompression. "
            "Max O-ring section: 7 mm diameter per PMS_PDF.pdf §7.9. "
            "No precautions needed for gaseous service <30 barg."
        )

    # FFKM for methanol service (VMS §7.8)
    service_str = data.get("service", "").lower()
    if ("methanol" in service_str or "glycol" in service_str) and data.get("seal_material"):
        data["seal_material_note"] = "FFKM recommended for Methanol/Glycol service per PMS_PDF.pdf §7.8"

    # Preferred resilient seating materials (VMS §7.8)
    if seat in ("T", "P") and vt != "DB":
        data["resilient_seat_note"] = (
            "Preferred resilient seating: Nitrile, Viton, or RPTFE for -18\u00b0C to 93\u00b0C. "
            "Below -18\u00b0C: use softer materials (Kel-F, unreinforced PTFE). "
            "Not recommended where solids/abrasives present per PMS_PDF.pdf §7.8."
        )

    # Torque and operation limits (VMS §6.11.2)
    data["max_torque"] = "Max 150 Nm (handwheel), Max 270 Nm (lever) per PMS_PDF.pdf §6.11.2"
    data["max_handwheel_diameter"] = "750 mm max per PMS_PDF.pdf §6.11.2"
    data["max_lever_length"] = "500 mm max each side per PMS_PDF.pdf §6.11.2"
    data["operating_force"] = "Max 45 kg (100 lbs) to break open/close, 35 kg (75 lbs) at mid-stroke"

    # ── Bolting & gaskets (PMS bolting_gaskets block wins; BF SS316L RF uses appendix gasket if unset) ──
    if pms.get("gaskets"):
        data["gaskets"] = pms["gaskets"]
    elif (
        vt == "BF"
        and not is_rtj
        and cat in ("SS316L", "SS316L_NACE")
    ):
        data["gaskets"] = _BF_GASKET_SS316L_RF
    else:
        data["gaskets"] = GASKET_MATERIAL.get((cat, is_rtj), GASKET_MATERIAL.get((cat, False), ""))
    data["bolts"] = pms.get("bolts", _rt.get("bolt_material", cat))
    data["nuts"] = pms.get("nuts", _rt.get("nut_material", cat))
    if (
        vt == "BF"
        and cat in ("SS316L", "SS316L_NACE")
        and not pms.get("bolts")
    ):
        data["bolts"] = _BF_BOLT_SS316L
    if (
        vt == "BF"
        and cat in ("SS316L", "SS316L_NACE")
        and not pms.get("nuts")
    ):
        data["nuts"] = _BF_NUT_SS316L
    data["bolt_plating"] = "No cadmium plating. XYLAN 1070 or equivalent fluoropolymer coating"

    if vt in ("GA", "GL"):
        data["bonnet_material"] = _rt.get("body_material", cat)

    # ── Hydrotest ──
    if "hydrotest_shell" in pms:
        data["hydrotest_shell"] = pms["hydrotest_shell"]
        data["hydrotest_closure"] = pms["hydrotest_closure"]
    else:
        data["hydrotest_shell"], data["hydrotest_closure"] = _calc_hydrotest(data.get("design_pressure", ""))

    # Fire rating — size-dependent for ball valves
    if vt in ("BL", "BS"):
        mt = data.get("ball_mounting_type", "Mixed")
        if mt == "Trunnion":
            data["fire_rating"] = "API SPEC 6FA (Trunnion), third-party witnessed"
        elif mt == "Floating":
            data["fire_rating"] = "API STD 607 / BS EN ISO 10497 (Floating), third-party witnessed"
        else:
            data["fire_rating"] = "API SPEC 6FA (Trunnion) / API STD 607 (Floating), third-party witnessed"
    else:
        data["fire_rating"] = _rt.get("fire_rating", vt)

    if seat in ("T", "P"):
        if vt in ("BL", "BS"):
            data["fire_test"] = "Required \u2014 BS EN ISO 10497 / API 607, third-party witnessed"
            data["antistatic_device"] = "Required for soft-seated ball valve (API 6D)"
        elif vt == "DB" and not _dbb_inst:
            data["fire_test"] = "Required \u2014 BS EN ISO 10497 / API 607, third-party witnessed"
            data["antistatic_device"] = "Required for soft-seated primary obturator per manufacturer / API 6D"

    # ── Inspection & testing (PMS_PDF.pdf) ──
    data["ndt_extent"] = _resolve_ndt_extent(pc_num, size_inches, cat)
    data["functional_test"] = "5 cycles at manufacturer, 5 at fabrication yard, 5 offshore"

    # Pressure test standard selection (VMS §9.1)
    if pc_num <= 150:
        data["pressure_test_standard"] = "Designed per ASME B16.34, tested per API STD 598"
    else:
        data["pressure_test_standard"] = f"Designed and tested per API 6D (CL {pc_num}) and applicable valve type codes"
    if vt in ("BL", "BS") and seat == "M":
        data["leakage_rate"] = "Leakage rate not more than Rate 'B' per API 6D / ISO 5208 (metal seated ball valve)"
    data["pressure_test_sequence"] = "1) Body hydro test, 2) Seat hydro test, 3) Low pressure pneumatic seat test"

    # Forged valve NDT (VMS §7.5)
    if size_inches is not None and size_inches >= 2 and pc_num >= 600:
        if cat in ("LTCS_NACE",):
            data["forged_valve_ndt"] = "MPE per ASTM A-275, acceptance per ASME B16.34 Annexe C (LTCS forged \u22652\", \u2265600#)"
        elif cat in ("SS316L", "SS316L_NACE", "DSS", "SDSS", "SDSS_NACE"):
            data["forged_valve_ndt"] = "LPE per ASTM E-165, acceptance per ASME B16.34 Annexe D (SS/alloy forged \u22652\", \u2265600#)"

    # Austenitic SS specific requirements (VMS §7.2)
    if cat in ("SS316L", "SS316L_NACE"):
        data["austenitic_ss_requirements"] = (
            "Carbon content \u22640.03% max for Type 316L including overlay. "
            "Capable of passing intergranular corrosion test per ASTM A262 Practice E. "
            "Class 1500/2500 castings: LP and RT examined."
        )
        data["chloride_restriction"] = (
            "300-series SS SHALL NOT be used where chloride >5 ppm AND temperature >60\u00b0C "
            "(stress corrosion cracking region) per PMS_PDF.pdf \u00a77.2. "
            "Gaskets exempted for T \u2264120\u00b0C."
        )

    if is_nace:
        data["fugitive_emissions_test"] = "ISO 15848-1, Tightness Class BH, Endurance CC1/CO1"
        # Only set basic elastomer requirement if the detailed one wasn't already set
        if "elastomer_requirement" not in data:
            data["elastomer_requirement"] = "Explosive decompression resistant per NORSOK M-710"
        data["auxiliary_connections"] = "Flanged welded construction only (no socket weld or seal-welded threads)"
    if is_lt:
        data["impact_test"] = "Charpy V-notch impact test per ASME B31.3 / ASME B16.34"
    if cat in ("SS316L", "SS316L_NACE", "DSS", "SDSS", "SDSS_NACE", "CUNI"):
        data["pmi"] = "Required \u2014 Positive Material Identification per project document, random PMI per mill cert"
    # Butterfly VMS layout has no Locks row; other quarter-turn / multTurn types do.
    if vt not in ("CH", "BF", "GL") and "locks" not in data:
        data["locks"] = "Valve lockable using padlock - Full Open, Fully Closed"
    if vt == "GL":
        data.pop("locks", None)
    if vt in ("BL", "BS", "BF", "DB"):
        data["position_indicator"] = "Visual position indicator required"
    data["extended_stem"] = _resolve_extended_stem(size_inches)
    data["lifting_lug"] = "Required if weight >= 25 kg (design load 2x, 5\u00b0 tilt)"
    data["asbestos_free"] = "All packing, gaskets, and seals shall be asbestos-free"
    data["nameplate"] = "SS316, 3 mm thick, per MSS-SP-25"

    data.update(PROJECT_CONSTANTS)

    # Override leakage rate for metal seated ball valves (must be AFTER PROJECT_CONSTANTS)
    if vt in ("BL", "BS") and seat == "M":
        data["leakage_rate"] = "Leakage rate not more than Rate 'B' per API 6D / ISO 5208 (metal seated ball valve)"

    # Standard datasheet footer notes (numbered list rendered in XLSX Notes section
    # and returned in API response). NACE variant adds note 6 (NACE MR0175 compliance).
    data["datasheet_notes"] = footer_notes_as_text(vt, is_nace)

    if vt == "DB":
        data.pop("back_seat_material", None)
        data.pop("seal_material", None)
        data.pop("seal_material_note", None)
        data.pop("spring_material", None)
    if vt == "NE":
        data.pop("spring_material", None)

    # ── Per-VDS PMS override (PMS_PDF.pdf is authoritative) ─────────────────
    # Policy: use appendix data only for VDS codes that have an appendix record
    # (existing 745 codes). New classes from PMS Generator have no appendix
    # entry — those codes naturally synthesize from reference tables + rules.
    # Class-level fields (size_range, pressure_class, design_pressure, etc.)
    # always come from live PMS class data, never appendix.
    #
    # SWITCH: env var DATASHEET_USE_APPENDIX_OVERRIDE
    #   "1" / unset (default) → appendix override ENABLED. Existing codes
    #     get rich appendix material/construction data. New codes synthesize.
    #   "0" → appendix override DISABLED. Forces synthesis path for all codes.
    _appendix_flag = (os.environ.get("DATASHEET_USE_APPENDIX_OVERRIDE", "1") or "1").strip().lower()
    _use_appendix = _appendix_flag in ("1", "true", "on", "yes")
    try:
        _gvds = get_global_vds_loader() if _use_appendix else None
    except Exception:
        _gvds = None
    _vds_rec = _gvds.get(decoded.display_vds) if _gvds else None
    if _vds_rec:
        # For VDS codes with an appendix entry, every populated appendix field
        # wins over the sync-derived value — this includes class-level fields
        # (size_range, pressure_class, design_pressure, etc.) sourced from the
        # six A0 datasheet workbooks. New codes coming from PMS Generator have
        # no appendix entry and continue to flow through the sync path.
        _direct = (
            "service", "valve_type", "piping_class",
            "valve_standard", "operation",
            "size_range", "pressure_class", "design_pressure",
            "corrosion_allowance", "sour_service", "end_connections",
            "hydrotest_shell", "hydrotest_closure",
            "body_material", "ball_material", "disc_material",
            "wedge_material", "needle_material", "seat_material",
            "seal_material", "stem_material", "shaft_material",
            "gland_material", "gland_packing", "lever_handwheel",
            "gaskets", "bolts", "nuts",
            "marking_purchaser", "marking_manufacturer", "inspection_testing",
            "leakage_rate",
            "material_certification", "fire_rating", "finish",
        )
        for _k in _direct:
            if _k not in _vds_rec:
                continue
            _v = _vds_rec[_k]
            if _v is None:
                continue
            if _v == "":
                data.pop(_k, None)
            else:
                data[_k] = _v
        if _vds_rec.get("spring"):
            data["spring_material"] = _vds_rec["spring"]
        if _vds_rec.get("face_to_face_dimension"):
            data["face_to_face"] = _vds_rec["face_to_face_dimension"]

        # Promote nested _materials_extra into top-level engine keys (cover/
        # trim/hinge_pin live in this sibling dict in the appendix). Write
        # both canonical and "material_*"-prefixed key — frontend field-order
        # maps use either form depending on valve type.
        _mat_extra = _vds_rec.get("_materials_extra") or {}
        for _ek in ("cover_material", "trim_material", "hinge_pin_material"):
            _v = _mat_extra.get(_ek) or _mat_extra.get(_ek.replace("_material", ""))
            if _v and _v != "-":
                data[_ek] = _v
                data[f"material_{_ek}"] = _v

        # PMS-mirroring for material rows: drop rule-template material fields
        # PMS did not list for this VDS (mirrors the construction block below).
        _material_pms_to_engine = {
            "body_material":"body_material","ball_material":"ball_material",
            "disc_material":"disc_material","wedge_material":"wedge_material",
            "needle_material":"needle_material","seat_material":"seat_material",
            "seal_material":"seal_material","stem_material":"stem_material",
            "shaft_material":"shaft_material","gland_material":"gland_material",
            "gland_packing":"gland_packing","lever_handwheel":"lever_handwheel",
            "back_seat_material":"back_seat_material","spring":"spring_material",
        }
        if any(_vds_rec.get(_pk) for _pk in _material_pms_to_engine):
            _mat_kept = {_ek for _pk, _ek in _material_pms_to_engine.items() if _vds_rec.get(_pk)}
            if vt == "GL":
                _mat_kept.add("back_seat_material")
            for _ek in set(_material_pms_to_engine.values()):
                if _ek not in _mat_kept:
                    data.pop(_ek, None)
        _cons = _vds_rec.get("construction") or {}
        _construction_map = (
            ("body", "body_construction"), ("bonnet", "bonnet_construction"),
            ("ball", "ball_construction"),
            ("disc", "disc_construction"), ("wedge", "wedge_construction"),
            ("stem", "stem_construction"), ("shaft", "shaft_construction"),
            ("seat", "seat_construction"), ("locks", "locks"),
            ("packing", "packing_construction"), ("back_seat", "back_seat_construction"),
        )
        if any(_cons.get(_k) for _k, _ in _construction_map):
            _kept = {ek for ck, ek in _construction_map if _cons.get(ck)}
            for _ek in (e for _, e in _construction_map):
                if _ek not in _kept and _ek != "locks":
                    data.pop(_ek, None)
        for _ck, _ek in _construction_map:
            _cv = _cons.get(_ck)
            if _cv:
                data[_ek] = _cv

    prune_datasheet_by_valve_type(vt, design, seat, data, dbb_instrument=_dbb_inst)

    if vt == "BF":
        apply_bf_vms_construction_overrides(data)

    return data
