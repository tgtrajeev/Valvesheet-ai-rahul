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

import re
from ..models.vds import DecodedVDS, ValveType, SeatType, EndConnection
from .pms_loader import get_pms_loader

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
    "GL": "BS 1873",
    ("CH", "P"): "API STD 602 / BS 1868",
    ("CH", "S"): "API STD 594 / BS 1868",
    ("CH", "D"): "API STD 594",
    ("CH", "W"): "API STD 594",
    "DB": "API SPEC 6D",
    "NE": "BS EN ISO 15761",
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
        "stem_construction": "Rotating, Blowout proof stem",
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
        "operation": 'Hand wheel, Non-rising (Gear for 14" and above, Fully enclosed, dust proof ), with Position Indicator',
    },
    "GL": {
        "body_construction": "Bolted bonnet, Integral Flanged End",
        "stem_construction": "Rising stem, outside screw and yoke, Back Seated",
        "back_seat_construction": "Renewable back seat",
        "packing_construction": "Bolted gland, Live-load packing, Renewable packing rings",
        "disc_construction": "Ball / Plug Hard Faced",
        "operation": 'Hand wheel, Non-rising (Gear for 10" and above, Fully enclosed, dust proof ), with Position Indicator',
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
        "body_construction": "Integral body, straight or angle pattern",
        "stem_construction": "Non-rotating stem tip",
        "operation": "Hand wheel / T-bar handle",
    },
}

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
    "inspection_testing": "ASME B16.34, API 598",
    "leakage_rate": "As per API 598",
    "pneumatic_test": "5.5 barg",
    "material_certification": "Pressure Retaining Parts EN 10204 3.2, Other parts EN 10204 3.1",
    "finish": "General Specification for Paint and Protective Coating doc : 50501-SPE-80000-ME-ET-0006",
}


# ============================================================================
# END CONNECTION RESOLUTION
# ============================================================================

def _resolve_end_connection(end_conn: EndConnection, piping_class: str, cat: str) -> str:
    """Derive the full end connection description from the end connection code."""
    ec = end_conn.value
    letter = piping_class[0] if piping_class else "A"

    # ASME B16.5 standard flanged connections
    ec_map = {
        "R": "Flanged ASME B16.5 RF (Raised Face)",
        "J": "Flanged ASME B16.5 RTJ (Ring Type Joint)",
        "F": "Flanged ASME B16.5 FF (Flat Face)",
        "W": "Butt Weld, ASME B16.25",
        "S": "Socket Weld, ASME B16.11",
        "H": "Hub Connector (Grayloc / Vector type)",
        "T": "NPT Female, ASME B1.20.1",
        "JT": "Flanged ASME B16.5 RTJ + NPT Female",
    }

    base = ec_map.get(ec, f"Flanged ASME B16.5 {ec}")

    # Cu-Ni / GRE / CPVC use different flange standards
    if cat in ("CUNI",):
        base = base.replace("ASME B16.5", "EEMUA 234")
    elif cat in ("GRE", "GRE_BONSTRAND"):
        base = base.replace("ASME B16.5", "GRE Flange")
    elif cat in ("CPVC",):
        base = base.replace("ASME B16.5", "CPVC Flange")

    return base


# ============================================================================
# CORROSION ALLOWANCE
# ============================================================================

def _resolve_corrosion_allowance(cat: str) -> str:
    """Derive corrosion allowance based on material category."""
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

def _resolve_from_pms(piping_class: str, cat: str, is_rtj: bool) -> dict:
    """Try to resolve bolts, nuts, gaskets, hydrotest, design pressure from PMS data.

    PMS data is authoritative — if available, it overrides the rule-based fallbacks.
    """
    pms_fields = {}
    try:
        pms = get_pms_loader()
        spec = pms.get_spec(piping_class)
    except (FileNotFoundError, Exception):
        return pms_fields

    if not spec:
        return pms_fields

    # Bolting & gaskets from PMS
    if spec.bolting_gaskets:
        if spec.bolting_gaskets.stud_bolt_spec:
            pms_fields["bolts"] = spec.bolting_gaskets.stud_bolt_spec
        if spec.bolting_gaskets.hex_nut_spec:
            pms_fields["nuts"] = spec.bolting_gaskets.hex_nut_spec
        if spec.bolting_gaskets.gasket_spec:
            pms_fields["gaskets"] = spec.bolting_gaskets.gasket_spec

    # Design pressure from PMS INDEX
    if spec.index_row:
        if spec.index_row.design_pressure_barg:
            dp = spec.index_row.design_pressure_barg
            min_temp = spec.index_row.min_temp_c
            bps = spec.index_row.pt_breakpoints or []
            if bps and min_temp is not None:
                first_bp = bps[0]
                last_bp = bps[-1] if len(bps) > 1 else bps[0]
                pms_fields["design_pressure"] = (
                    f"{first_bp['press_barg']} @ {int(min_temp)}\u00b0C, "
                    f"{last_bp['press_barg']} @ {last_bp['temp_c']}\u00b0C"
                )

        # Hydrotest from PMS INDEX
        if spec.index_row.hydrotest_barg:
            shell = round(spec.index_row.hydrotest_barg, 2)
            closure = round((shell / 1.5) * 1.1, 2)
            pms_fields["hydrotest_shell"] = f"{shell} barg"
            pms_fields["hydrotest_closure"] = f"{closure} barg"

    # Service from PMS header
    if spec.header.service:
        pms_fields["service"] = spec.header.service

    # Size range from NPS sizes
    if spec.nps_sizes:
        sizes = sorted(set(s.get("nps_inch", 0) for s in spec.nps_sizes if s.get("nps_inch")))
        if sizes:
            pms_fields["size_range"] = f'{sizes[0]}" - {sizes[-1]}"'

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
# SIZE-DEPENDENT ENGINEERING RULES (MY-K-20-PI-SP-0002)
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
    """Determine floating vs trunnion mounting per MY-K-20-PI-SP-0002 Clause 5."""
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
    """Compute operation method per MY-K-20-PI-SP-0002 Clause 9."""
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
            return f'Gear operated c/w Handwheel ({size_inches}" >= {gear_min}" threshold), Fully enclosed, dust proof, with Position Indicator'
        return 'Handwheel, Non-rising (Gear for 14" and above, Fully enclosed, dust proof), with Position Indicator'

    if vt == "GL":
        if size_inches is not None and gear_min is not None and size_inches >= gear_min:
            return f'Gear operated c/w Handwheel ({size_inches}" >= {gear_min}" threshold), Fully enclosed, dust proof, with Position Indicator'
        return 'Handwheel, Non-rising (Gear for 10" and above, Fully enclosed, dust proof), with Position Indicator'

    if vt == "DB":
        return "Lever (Ball) / T-Bar (Needle), with Position Indicator"

    if vt == "NE":
        return "Handwheel / T-bar handle"

    return CONSTRUCTION.get(vt, {}).get("operation", "Handwheel")


def _resolve_ndt_extent(pressure_class: int, size_inches: float | None, cat: str) -> str:
    """Determine NDT/RT inspection extent per MY-K-20-PI-SP-0002 Clause 15."""
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
    """Return extended stem requirement for insulated lines per MY-K-20-PI-SP-0002 Clause 10."""
    if size_inches is None:
        return '75mm (1/2"-1-1/2"), 100mm (2"-6"), 150mm (8" and above) — if insulated line'
    if size_inches <= 1.5:
        return "75 mm extension (for insulated lines)"
    if size_inches <= 6:
        return "100 mm extension (for insulated lines)"
    return "150 mm extension (for insulated lines)"


def _resolve_wedge_type(size_inches: float | None) -> str:
    """Gate valve wedge type per MY-K-20-PI-SP-0002 Clause 6."""
    if size_inches is None:
        return 'Solid wedge (1-1/2" and below), Flexible wedge (2" and above)'
    if size_inches <= 1.5:
        return "Solid wedge, One piece"
    return "Flexible wedge"


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
      - Size-dependent rules from MY-K-20-PI-SP-0002

    Args:
        decoded: A DecodedVDS object from vds_decoder.decode_vds()
        size_inches: Optional valve size for size-dependent rules

    Returns:
        Flat dict of field_name -> value, ready to populate a datasheet card.
    """
    vt = decoded.valve_type.value     # e.g. "BL"
    design = decoded.design            # e.g. "R" (reduced bore)
    seat = decoded.seat_type.value if decoded.seat_type else "M"
    pc = decoded.piping_class          # e.g. "A1N"
    ec = decoded.end_connection        # EndConnection enum
    is_nace = decoded.is_nace
    is_lt = decoded.is_low_temp
    is_rtj = ec == EndConnection.RTJ or ec == EndConnection.RTJ_NPT

    # Material category drives most material selections
    cat = _get_material_category(pc)

    # Pressure class letter and number
    pc_letter = pc[0] if pc else "A"
    pc_num = _PRESSURE_CLASS_NUM.get(pc_letter, 150)

    # ── Resolve PMS data first (authoritative) ──
    pms = _resolve_from_pms(pc, cat, is_rtj)

    # ── Build the datasheet ──
    data: dict[str, str] = {}

    # Header / identification
    data["vds_no"] = decoded.raw_vds
    data["valve_type"] = VALVE_TYPE_DESCRIPTION.get((vt, design), f"{vt} Valve, design {design}")
    data["piping_class"] = pc

    # Service & size — PMS first, then fallback
    data["service"] = pms.get("service", SERVICE_FALLBACK.get(pc, ""))
    data["size_range"] = pms.get("size_range", SIZE_RANGE_FALLBACK.get(pc, '1/2" - 24"'))

    # Standards
    data["valve_standard"] = VALVE_STANDARD.get((vt, design), VALVE_STANDARD.get(vt, ""))
    data["pressure_class"] = PRESSURE_CLASS.get(pc_letter, "")

    # Design pressure — PMS first, then fallback
    data["design_pressure"] = pms.get("design_pressure", DESIGN_PRESSURE_FALLBACK.get(pc, ""))

    # Corrosion allowance
    data["corrosion_allowance"] = _resolve_corrosion_allowance(cat)

    # NACE / sour service / low temp
    if is_nace:
        data["sour_service"] = "NACE MR0175 / ISO 15156 compliant"
        data["nace_compliant"] = "Yes"
    else:
        data["sour_service"] = "-"
        data["nace_compliant"] = "No"

    if is_lt:
        data["low_temperature"] = "Yes - Impact tested"
        data["min_design_temp"] = "-46\u00b0C" if cat in ("DSS", "SDSS", "SDSS_NACE") else "-45\u00b0C"
    else:
        data["low_temperature"] = "No"
        data["min_design_temp"] = "-29\u00b0C" if cat.startswith("CS") else "-100\u00b0C" if cat.startswith("SS") else "-46\u00b0C"

    data["design_code"] = "ASME B31.3"

    # End connections
    data["end_connections"] = _resolve_end_connection(ec, pc, cat)

    # Face to face
    data["face_to_face"] = FACE_TO_FACE.get((vt, design), FACE_TO_FACE.get(vt, ""))

    # ── Construction (from valve type template) ──
    tmpl_key = f"{vt}_{design}" if vt == "CH" else vt
    tmpl = CONSTRUCTION.get(tmpl_key, CONSTRUCTION.get(vt, {}))
    for field, value in tmpl.items():
        data[field] = value

    # ── Size-dependent construction (MY-K-20-PI-SP-0002) ──
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

    if vt == "DB" and size_inches is not None:
        if size_inches <= 2:
            data["body_construction"] = "One-piece forged body, integral construction"
            data["dbb_end_connection"] = 'Flange x 1/2" NPT'
        else:
            data["body_construction"] = "Three-piece bolted body"
            data["dbb_end_connection"] = "Flanged both ends"

    data["operation"] = _resolve_operation(vt, size_inches, pc_num)

    # Body form
    if size_inches is not None and size_inches <= 1.5:
        data["body_form"] = "Forged"
    elif size_inches is not None:
        data["body_form"] = "Cast or Forged"
    else:
        data["body_form"] = 'Forged (1-1/2" and below), Cast or Forged (2" and above)'

    # ── Materials (from material category) ──
    body_mat = BODY_MATERIAL.get(cat, BODY_MATERIAL["CS"])
    if size_inches is not None and size_inches <= 1.5:
        parts = body_mat.split("/")
        forged_parts = [p.strip() for p in parts if "forged" in p.lower()]
        if forged_parts:
            body_mat = forged_parts[0]
    data["body_material"] = body_mat
    data["stem_material"] = STEM_MATERIAL.get(cat, STEM_MATERIAL["CS"])
    data["gland_material"] = GLAND_MATERIAL.get(cat, GLAND_MATERIAL["CS"])
    data["gland_packing"] = GLAND_PACKING.get(cat, _GLAND_PACKING_STD)
    data["lever_handwheel"] = "Solid ASTM A47 HDG/ ASTM A220 HDG/ SS316"
    data["spring_material"] = "Inconel 750"

    if vt in ("BL", "BS", "DB"):
        data["ball_material"] = BALL_MATERIAL.get(cat, BALL_MATERIAL["CS"])
        data["seat_material"] = SEAT_MATERIAL.get(seat, "Metal seated, hard faced, Renewable")
        data["seal_material"] = SEAL_MATERIAL_BALL.get(seat, "Viton AED")
        if vt != "DB":
            data["seat_construction"] = SEAT_CONSTRUCTION_BY_SEAT.get(seat, "")
        if seat == "M" and vt in ("BL", "BS"):
            data["seat_coating"] = "Tungsten Carbide overlay, min 1050 HV, 150-250 \u03bcm thickness"
            if cat.startswith("CS"):
                data["hardness_requirement"] = "Body/disc min 250 BHN, min 50 BHN differential"
            data["stellite_overlay"] = "Stellite 6 by deposition, min 1.6 mm finished thickness"
    elif vt == "GA":
        data["wedge_material"] = BODY_MATERIAL.get(cat, BODY_MATERIAL["CS"]) + ", Hard faced"
        data["seal_material"] = SEAL_MATERIAL_GATE.get(seat, "Flexible Graphite")
        if cat.startswith("CS") and seat == "M":
            data["hardness_requirement"] = "Body seat and wedge min 250 BHN, min 50 BHN differential"
    elif vt == "GL":
        data["disc_material"] = STEM_MATERIAL.get(cat, STEM_MATERIAL["CS"]) + ", Hard faced"
    elif vt == "CH":
        data["disc_material"] = STEM_MATERIAL.get(cat, STEM_MATERIAL["CS"])
        if design == "S":
            data["hinge_pin_material"] = STEM_MATERIAL.get(cat, STEM_MATERIAL["CS"])
    elif vt == "BF":
        data["shaft_material"] = STEM_MATERIAL.get(cat, STEM_MATERIAL["CS"])
        data["seat_material"] = SEAT_MATERIAL.get(seat, "Reinforced PTFE (max 200\u00b0C)")
    elif vt == "NE":
        data["needle_material"] = STEM_MATERIAL.get(cat, STEM_MATERIAL["CS"])
        data["minimum_bore"] = "10 mm (instrument connections)"

    # Backseat for GA, GL, NE
    if vt in ("GA", "GL", "NE"):
        data["backseat"] = "Back seated, renewable"

    # ── Bolting & gaskets ──
    data["bolts"] = pms.get("bolts", BOLT_MATERIAL.get(cat, BOLT_MATERIAL["CS"]))
    data["nuts"] = pms.get("nuts", NUT_MATERIAL.get(cat, NUT_MATERIAL["CS"]))
    data["gaskets"] = pms.get("gaskets", GASKET_MATERIAL.get((cat, is_rtj), GASKET_MATERIAL.get((cat, False), "")))
    data["bolt_plating"] = "No cadmium plating. XYLAN 1070 or equivalent fluoropolymer coating"

    if vt in ("GA", "GL"):
        data["bonnet_material"] = BODY_MATERIAL.get(cat, BODY_MATERIAL["CS"])

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
        data["fire_rating"] = FIRE_RATING.get(vt, "N/A")

    if seat in ("T", "P"):
        data["fire_test"] = "Required \u2014 BS EN ISO 10497 / API 607, third-party witnessed"
        data["antistatic_device"] = "Required for soft-seated valve"

    # ── Inspection & testing (MY-K-20-PI-SP-0002) ──
    data["ndt_extent"] = _resolve_ndt_extent(pc_num, size_inches, cat)
    data["functional_test"] = "5 cycles at manufacturer, 5 at fabrication yard, 5 offshore"
    if is_nace:
        data["fugitive_emissions_test"] = "ISO 15848-1, Tightness Class BH, Endurance CC1/CO1"
        data["elastomer_requirement"] = "Explosive decompression resistant per NORSOK M-710"
        data["auxiliary_connections"] = "Flanged welded construction only (no socket weld or seal-welded threads)"
    if is_lt:
        data["impact_test"] = "Charpy V-notch impact test per ASME B16.34"
    if cat in ("SS316L", "SS316L_NACE", "DSS", "SDSS", "SDSS_NACE", "CUNI"):
        data["pmi"] = "Required \u2014 Positive Material Identification"
    if vt != "CH" and "locks" not in data:
        data["locks"] = "Valve lockable using padlock - Full Open, Fully Closed"
    if vt in ("BL", "BS", "BF", "DB"):
        data["position_indicator"] = "Visual position indicator required"
    data["extended_stem"] = _resolve_extended_stem(size_inches)
    data["lifting_lug"] = "Required if weight >= 25 kg (design load 2x, 5\u00b0 tilt)"
    data["asbestos_free"] = "All packing, gaskets, and seals shall be asbestos-free"
    data["nameplate"] = "SS316, 3 mm thick, per MSS-SP-25"

    data.update(PROJECT_CONSTANTS)
    return data
