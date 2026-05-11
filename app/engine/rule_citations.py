"""rule_citations.py — every datasheet field maps to the API/ISO/ASME rule
that DRIVES its value, with the exact section + page in the source standard.

This is what makes the engine genuinely standard-driven (vs. a hardcoded
lookup): when generate_datasheet() emits a value, the citation it returns
points to the universal rule in API 6D, API 615, ASME B16.34, etc., NOT to
a copied appendix datasheet.

For a new project, no citation here changes — the standards are universal.
Only the project's piping-class data (materials per category, P-T ratings)
varies per project.

Citation structure
------------------
    {
      "rule":          "Plain-English statement of the rule",
      "primary": {
          "doc":          "API SPEC 6D",
          "section":      "5.2 Pressure and Temperature Rating",
          "printed_page": 13,        # page number printed on the PDF page
          "pdf_page":     27,        # 1-based PDF page index
          "quote":        "Verbatim sentence from the standard",
      },
      "supporting": [               # other standards relied on for this field
          {"doc": "ASME B16.34", "purpose": "Pressure-temperature rating tables"},
      ],
    }

Page offsets in the standards we have on disk
---------------------------------------------
    API SPEC 6D, 24th ed. : printed page X  =  PDF page (X + 14)
    API RP 615, 2nd ed.   : printed page X  =  PDF page (X + 7)
"""
from __future__ import annotations

# ── Document metadata ───────────────────────────────────────────────────────

API_6D = "API SPEC 6D"
API_615 = "API RP 615"
API_598 = "API STD 598"
API_607 = "API STD 607"
API_6FA = "API SPEC 6FA"
API_600 = "API STD 600"
API_602 = "API STD 602"
API_603 = "API STD 603"
API_608 = "API STD 608"
API_594 = "API STD 594"
API_609 = "API STD 609"
API_623 = "API STD 623"
ASME_B1634 = "ASME B16.34"
ASME_B165 = "ASME B16.5"
ASME_B1610 = "ASME B16.10"
ASME_B1620 = "ASME B16.20"
ASME_B1647 = "ASME B16.47"
MSS_SP25 = "MSS-SP-25"
MSS_SP44 = "MSS-SP-44"
ISO_10497 = "ISO 10497"
ISO_5208 = "ISO 5208"
ISO_15761 = "BS EN ISO 15761"
ISO_17292 = "BS EN ISO 17292"
BS_1873 = "BS 1873"
BS_1868 = "BS 1868"
EN_10204 = "BS EN 10204"
NACE_MR0175 = "NACE MR0175 / ISO 15156"

# Page-offset helpers — printed page number on the PDF + (offset) = PDF page index
def _api6d(printed_page: int) -> int:  return printed_page + 14
def _api615(printed_page: int) -> int: return printed_page + 7


# ── Citation primitives ────────────────────────────────────────────────────

def _cite(doc: str, section: str, printed_page: int, pdf_page: int, quote: str = "") -> dict:
    return {
        "doc": doc,
        "section": section,
        "printed_page": printed_page,
        "pdf_page": pdf_page,
        "quote": quote,
    }


def _support(doc: str, purpose: str) -> dict:
    return {"doc": doc, "purpose": purpose}


# ── Per-field citations (look up by field name + valve type) ───────────────

# Each entry returns a dict — a function so it can branch on valve type / context.

def cite_valve_standard(valve_type: str) -> dict:
    """The 'Valve Standard' field on a datasheet — which API / BS / ISO design code applies."""
    if valve_type in ("BL", "BS"):
        return {
            "rule": "Ball valves shall comply with API 6D or ISO 17292",
            "primary": _cite(API_6D, "1 Scope + 4.1.3 Ball Valves", 1, _api6d(1),
                             "this specification defines requirements for the design, manufacturing... ball, check, gate, and plug valves"),
            "supporting": [
                _support(ISO_17292, "Steel ball valves for petroleum, petrochemical and allied industries"),
                _support(API_608, "Metal ball valves: flanged and butt-welding ends"),
                _support(API_615, "Valve selection guide §4.1.2 — ball valves"),
            ],
        }
    if valve_type == "GA":
        return {
            "rule": "Gate valves shall comply with API 600, API 602, or API 603 as applicable",
            "primary": _cite(API_615, "4.1.1 Gate Valves (4.1.1.2 API 600, 4.1.1.3 API 602, 4.1.1.4 API 603)", 4, _api615(4),
                             "Gate valves shall comply with API 600, 602 or 603 as applicable"),
            "supporting": [
                _support(API_600, "Steel gate valves NPS 1+ for refinery service"),
                _support(API_602, "Compact steel gate, globe & check valves up to NPS 4"),
                _support(API_603, "Corrosion-resistant gate valves"),
                _support(ASME_B1634, "Pressure-temperature ratings"),
            ],
        }
    if valve_type == "GL":
        return {
            "rule": "Globe valves shall comply with API 602, BS EN ISO 15761, or BS 1873",
            "primary": _cite(API_615, "4.3 Globe Valves", 9, _api615(9),
                             "Globe valves are covered in API 602 in sizes up to NPS 4 and in API 623 for sizes NPS 2 up to NPS 24"),
            "supporting": [
                _support(API_623, "Steel globe valves — flanged & butt-welding ends NPS 2-24"),
                _support(ISO_15761, "Steel gate, globe and check valves DN 100 and smaller"),
                _support(BS_1873, "Steel globe and globe stop and check valves"),
            ],
        }
    if valve_type == "CH":
        return {
            "rule": "Check valves shall comply with API 594, API 6D, BS 1868, BS EN ISO 15761, or API 602",
            "primary": _cite(API_615, "4.2 Check Valves", 8, _api615(8),
                             "API standards covering check valves are API 594, API 602, and API 6D"),
            "supporting": [
                _support(API_594, "Check valves — flanged, lug, wafer and butt-welding"),
                _support(API_6D,  "Pipeline and piping check valves"),
                _support(BS_1868, "Steel check valves for petroleum, petrochemical and allied industries"),
                _support(ISO_15761, "Check valves DN 100 and smaller"),
            ],
        }
    if valve_type == "BF":
        return {
            "rule": "Butterfly valves shall comply with API 609",
            "primary": _cite(API_615, "4.1.4 API 609 Butterfly Valves", 6, _api615(6),
                             "Butterfly valves are defined in API 609 as two major types, Category A and Category B"),
            "supporting": [_support(API_609, "Butterfly valves: double-flanged, lug- and wafer-type")],
        }
    if valve_type == "DB":
        return {
            "rule": "Double block-and-bleed valves shall be designed per ASME B16.34 with API 6D §3.1.10 functionality",
            "primary": _cite(API_6D, "3.1.10 Double Block and Bleed Valve", 5, _api6d(5),
                             "Single valve with two seating surfaces that... can be vented"),
            "supporting": [
                _support(API_615, "§7.5 Double Block-and-Bleed (DB&B) Valves"),
                _support(ASME_B1634, "Pressure-temperature ratings"),
            ],
        }
    if valve_type == "NE":
        return {
            "rule": "Needle valves shall be designed per BS EN ISO 15761; alternative ASME B16.34",
            "primary": _cite(ASME_B1634, "Pressure-temperature & wall-thickness rules", 0, 0,
                             "Manufacturer standard supplemented by ISO 15761 for stem & body design"),
            "supporting": [
                _support(ISO_15761, "Steel gate, globe and check valves DN 100 and smaller — used as basis"),
                _support(API_602, "Compact valves up to NPS 4"),
            ],
        }
    return {
        "rule": f"No standard mapped for valve type '{valve_type}'",
        "primary": _cite("UNKNOWN", "", 0, 0, ""),
        "supporting": [],
    }


def cite_pressure_class() -> dict:
    """The 'Pressure Class' field — class letter from VDS code → ASME class number."""
    return {
        "rule": "Pressure-temperature ratings per ASME B16.34; permitted classes 150 / 300 / 400 / 600 / 900 / 1500 / 2500",
        "primary": _cite(API_6D, "5.2 Pressure and Temperature Rating", 13, _api6d(13),
                         "Valves... shall be furnished in one of the following pressure classes: Class 150, Class 300, Class 400, Class 600, Class 900, Class 1500, or Class 2500"),
        "supporting": [_support(ASME_B1634, "Pressure-temperature rating tables (Group 1, 2, 3 materials)")],
    }


def cite_end_connections(end_char: str) -> dict:
    """End connection field — flange face standard from end character (R/J/F/T/W/H)."""
    if end_char == "R":  # RF
        return {
            "rule": "Raised-face flanges per ASME B16.5 (≤NPS 24) / MSS SP-44 (NPS 22) / ASME B16.47 Series A (≥NPS 26)",
            "primary": _cite(API_6D, "5.7.1.1 Flanged Ends", 15, _api6d(15),
                             "Flanges shall be furnished with a raised face or ring joint face... in accordance with ASME B16.5 for sizes up to NPS 24"),
            "supporting": [
                _support(ASME_B165, "Pipe flanges and flanged fittings — RF dimensions"),
                _support(MSS_SP44, "Steel pipeline flanges — NPS 22"),
                _support(ASME_B1647, "Large-diameter flanges NPS 26 and above"),
            ],
        }
    if end_char == "J":  # RTJ
        return {
            "rule": "Ring-joint flanges per ASME B16.5; ring joint groove number marked on flange OD",
            "primary": _cite(API_6D, "5.7.1.1 Flanged Ends", 15, _api6d(15),
                             "Flanges shall be furnished with a raised face or ring joint face"),
            "supporting": [
                _support(ASME_B165, "RTJ flange + ring groove dimensions"),
                _support(ASME_B1620, "Metallic gaskets for pipe flanges — ring joint, spiral wound, jacketed"),
            ],
        }
    if end_char == "F":  # FF
        return {
            "rule": "Flat-face flanges per ASME B16.5 (typically Class 150, low-temp service)",
            "primary": _cite(API_6D, "5.7.1.1 Flanged Ends", 15, _api6d(15), ""),
            "supporting": [_support(ASME_B165, "FF flange dimensions")],
        }
    if end_char == "T":  # NPT
        return {
            "rule": "NPT female threaded ends per ASME B1.20.1",
            "primary": _cite(API_6D, "5.9 Drains (drain thread reference)", 17, _api6d(17),
                             "Tapered threads shall be capable of providing a seal and comply with ASME B1.20.1"),
            "supporting": [_support("ASME B1.20.1", "Pipe Threads, General Purpose, Inch")],
        }
    if end_char == "W":  # Wafer
        return {
            "rule": "Wafer / lug type per API 594 (check) or API 609 (butterfly)",
            "primary": _cite(API_594, "API 594 Type A wafer & lug check valves", 0, 0, ""),
            "supporting": [_support(API_609, "Butterfly valves wafer / lug type")],
        }
    if end_char == "H":  # Hub
        return {
            "rule": "Hub end connector per Norsok L-005 / compact flange",
            "primary": _cite("Norsok L-005", "Compact flanged connections", 0, 0, ""),
            "supporting": [],
        }
    return {
        "rule": f"End connection type '{end_char}' — manufacturer standard",
        "primary": _cite("Manufacturer standard", "", 0, 0, ""),
        "supporting": [],
    }


def cite_face_to_face(valve_type: str) -> dict:
    """Face-to-face / end-to-end dimensions."""
    if valve_type in ("BL", "BS"):
        return {
            "rule": "Ball valves long-pattern face-to-face per API 6D Table C.3 (or ASME B16.10)",
            "primary": _cite(API_6D, "5.4 Face-to-face / End-to-end + Annex C Table C.3", 14, _api6d(14),
                             "Face-to-face (A) and end-to-end (B and C) dimensions shall be in accordance with Table C.1 to C.5"),
            "supporting": [_support(ASME_B1610, "Face-to-face and end-to-end dimensions of ferrous valves")],
        }
    if valve_type == "GA":
        return {
            "rule": "Gate valves face-to-face per API 6D Table C.1 / ASME B16.10",
            "primary": _cite(API_6D, "5.4 + Annex C Table C.1", 14, _api6d(14), ""),
            "supporting": [_support(ASME_B1610, "Face-to-face dimensions")],
        }
    if valve_type in ("CH", "GL"):
        return {
            "rule": f"{'Check' if valve_type == 'CH' else 'Globe'} valves face-to-face per ASME B16.10",
            "primary": _cite(ASME_B1610, "Face-to-face / end-to-end dimensions", 0, 0, ""),
            "supporting": [_support(API_6D, "5.4 Face-to-face dimensions")],
        }
    if valve_type == "BF":
        return {
            "rule": "Butterfly valves face-to-face per API 609 Category A / B",
            "primary": _cite(API_609, "API 609 Cat A / Cat B face-to-face dimensions", 0, 0, ""),
            "supporting": [],
        }
    if valve_type in ("DB", "NE"):
        return {"rule": "Manufacturer standard", "primary": _cite("Manufacturer standard","",0,0,""), "supporting": []}
    return {"rule": "Manufacturer standard", "primary": _cite("Manufacturer standard","",0,0,""), "supporting": []}


def cite_construction_body(valve_type: str) -> dict:
    if valve_type in ("BL", "BS"):
        return {
            # cite §6.23 (printed p.25) — that section spells out floating vs trunnion
            # thresholds by class+size, which IS what the value text describes.
            "rule": "Ball valve body — top-entry, two-piece split, or three-piece bolted; floating (small)/trunnion (large) per §6.23 size+class table",
            "primary": _cite(API_6D, "6.23 Ball Valves: Floating Ball / Trunnion Mount", 25, _api6d(25),
                             "Trunnion-supported valves: 10-in and larger for 150 lb rating, 6-in and larger for 300 lb, 2-in and larger for 600 lb, all sizes for 900 lb and above"),
            "supporting": [_support(API_615, "§4.1.2 Ball Valves")],
        }
    if valve_type == "GA":
        return {
            "rule": "Gate valve — bolted bonnet, integral flanged end, OS&Y stem with backseat",
            "primary": _cite(API_6D, "4.1.1 Gate Valves + Figures B.1–B.2", 10, _api6d(10),
                             "Gate valves shall be provided with a back seat or secondary stem sealing feature"),
            "supporting": [_support(API_600, "Steel gate valves — flanged & butt-welding ends")],
        }
    if valve_type == "CH":
        return {
            "rule": "Check valve — bolted cover; piston / swing / dual-plate types",
            "primary": _cite(API_6D, "4.1.4 Check Valves + Figures B.7–B.13", 10, _api6d(10),
                             "Check valves... wafer, axial flow, and lift type"),
            "supporting": [_support(API_594, "Check valves wafer/lug")],
        }
    if valve_type == "BF":
        return {
            "rule": "Butterfly valve — wafer / lug type with quarter-turn disc",
            "primary": _cite(API_615, "§4.1.4 Butterfly Valves", 6, _api615(6), ""),
            "supporting": [_support(API_609, "Butterfly valves Cat A / B")],
        }
    if valve_type == "DB":
        return {
            "rule": "DBB valve — single body with two seats and bleed connection",
            "primary": _cite(API_6D, "3.1.10 Double Block and Bleed", 5, _api6d(5),
                             "Single valve with two seating surfaces that, in the closed position, provides a seal against pressure from both ends... with a means of venting/bleeding the cavity between"),
            "supporting": [_support(API_615, "§7.5 DBB Valves")],
        }
    return {"rule": "Manufacturer standard body construction", "primary": _cite("Manufacturer standard","",0,0,""), "supporting": []}


def cite_construction_stem(valve_type: str) -> dict:
    if valve_type in ("BL", "BS", "DB"):
        return {
            # cite the design rule that mandates antistatic devices for soft-seated
            # quarter-turn valves (API 6D body, NOT §5.18 actuators).
            "rule": "Soft-seated ball, plug and butterfly valves shall be supplied with antistatic devices; stem must be anti-blowout",
            "primary": _cite(API_6D, "6 Design — antistatic device requirement", 18, _api6d(18),
                             "Soft seated ball, plug and butterfly valves shall be supplied with antistatic devices"),
            "supporting": [_support(API_615, "§4.1.2 Ball valves antistatic stem")],
        }
    if valve_type in ("GA", "GL"):
        return {
            "rule": "Rising stem, outside screw and yoke (OS&Y), back-seated",
            "primary": _cite(API_615, "§4.1.1 Gate Valves + Figure A.1 (OS&Y)", 4, _api615(4),
                             "Annex A Figure A.1: Typical API 600 Bolted Bonnet Gate Valve — Outside Screw and Yoke"),
            "supporting": [_support(API_600, "OS&Y stem requirement"), _support(API_6D, "5.18 stem extensions")],
        }
    if valve_type == "NE":
        return {"rule": "Inside-screw stem, needle point", "primary": _cite("Manufacturer standard","",0,0,""), "supporting": []}
    return {"rule": "Manufacturer standard stem", "primary": _cite("Manufacturer standard","",0,0,""), "supporting": []}


def cite_construction_seat(seat_char: str, valve_type: str = "") -> dict:
    if seat_char == "T":  # PTFE
        return {
            "rule": "Soft (PTFE) seat — virgin or glass-fiber-reinforced PTFE; service limit ~177 °C to 205 °C",
            "primary": _cite(API_615, "§6.3 Seating Surfaces — Soft Seats", 12, _api615(12),
                             "API 608 and API 609 cover PTFE and reinforced PTFE materials with P-T ratings defined... PTFE service temperature limit is typically 177 °C to 205 °C"),
            "supporting": [_support(API_608, "Ball valve soft seat P-T ratings"), _support(API_609, "Butterfly soft seat P-T")],
        }
    if seat_char == "P":  # PEEK
        return {
            "rule": "PEEK seat — engineered polymer, higher temperature than PTFE; manufacturer P-T rating",
            "primary": _cite(API_615, "§6.3 Soft Seats (other materials by agreement)", 12, _api615(12),
                             "Other soft seat materials are available with P-T ratings established by agreement between the purchaser and manufacturer"),
            "supporting": [],
        }
    if seat_char == "M":  # Metal
        return {
            "rule": "Metal seat — hard-faced (Stellite / TCC), renewable; min hardness 250 BHN with 50 BHN differential",
            "primary": _cite(API_615, "§6.2 Trim & Seating Surface Hardfacing", 12, _api615(12),
                             "Hardfacing... applied to the seating surfaces of valves to provide for longer life and improved resistance to galling"),
            "supporting": [_support(API_6D, "5.10 Injection points, 6 Materials"), _support(API_600, "Hardfaced seat ring requirement")],
        }
    return {"rule": "Manufacturer standard seat", "primary": _cite("Manufacturer standard","",0,0,""), "supporting": []}


def cite_operation(valve_type: str, size_inches: float | None = None, pressure_class: int = 150) -> dict:
    """Operator/actuator selection."""
    if valve_type in ("BL", "BS", "BF", "DB"):
        return {
            "rule": "Quarter-turn valves: lever for small sizes (< NPS 4), gear-operated handwheel for larger sizes; max breakaway force 360 N (80 lbf)",
            "primary": _cite(API_615, "§7.1 Valve Operation", 14, _api615(14),
                             "Levers or handles are usually adequate for small, quarter-turn valves less than NPS 4... for larger valves, a means of assisted operation is often required"),
            "supporting": [
                _support(API_6D, "5.13 Handwheels / Wrenches / Levers — max 360 N breakaway force; HW diameter ≤ 1016 mm"),
                _support(API_6D, "5.16 Position indicator required"),
            ],
        }
    if valve_type in ("GA", "GL"):
        return {
            "rule": "Multi-turn valves: handwheel-operated; gearbox required for larger sizes (e.g. ≥10\" globe, ≥14\" gate)",
            "primary": _cite(API_615, "§7.1 Valve Operation", 14, _api615(14),
                             "Gate and globe valve operation is normally by means of a handwheel"),
            "supporting": [_support(API_6D, "5.13 Handwheels / Wrenches"), _support(API_600, "Gearbox requirement for large gate valves")],
        }
    if valve_type == "NE":
        return {"rule": "T-bar / lever for needle valves", "primary": _cite("Manufacturer standard","",0,0,""), "supporting": []}
    return {"rule": "Operator per manufacturer standard", "primary": _cite("Manufacturer standard","",0,0,""), "supporting": []}


def cite_body_material(material_category: str) -> dict:
    """Body material — derived from piping class category + ASME B16.34 Group."""
    return {
        # ASME B16.34 §6.1 Table 1 defines the Group + valid grades. The
        # specific grade chosen AND any size-threshold split (e.g. forged
        # ASTM A105N below 1.5", cast ASTM A216 WCB above) is the project's
        # PMS decision — not in ASME B16.34 itself.
        "rule": f"Material Group selection per ASME B16.34 §6.1 Table 1 for {material_category}; specific grade + any size-threshold split is project-specific (project PMS materials section)",
        "primary": _cite(ASME_B1634, f"Table 1 — Material Specification List (Group 1 ferrous / Group 2 austenitic / Group 3 nickel)", 0, 0,
                         "Pressure-containing parts shall be designed with materials specified in Table 1; grade selection per service requirements"),
        "supporting": [
            _support(API_6D, "6.1 Material Specification — chemistry, heat treatment, mechanical properties"),
            _support(API_615, "§6.1 Body Material Selection"),
            _support("Project PMS materials section", f"Specific ASTM grade(s) for class {material_category} + size-threshold split between forged and cast"),
        ],
    }


def cite_trim_material(material_category: str) -> dict:
    """Ball / disc / wedge / stem trim material — must be at least as corrosion-resistant as the body."""
    return {
        "rule": "Trim material shall have corrosion-resistance properties at least equal to the body material",
        "primary": _cite(API_615, "§6.2 Trim", 12, _api615(12),
                         "Trim is to be of the same nominal chemical composition as the shell and have mechanical and corrosion-resistance properties similar to those of the shell"),
        "supporting": [_support(API_6D, "6.1 Materials"), _support("Project PMS", "Specific trim grade per piping class")],
    }


def cite_fire_rating(valve_type: str) -> dict:
    if valve_type in ("BL", "BS", "DB"):
        return {
            "rule": "Ball valves shall be fire-tested per API 6FA (trunnion) or API 607 / ISO 10497 (floating)",
            "primary": _cite(API_6D, "8 Quality Control + Annex H supplementary tests", 27, _api6d(27), ""),
            "supporting": [
                _support(API_6FA, "Fire Test for Trunnion-Mounted Ball Valves"),
                _support(API_607, "Fire Test for Quarter-Turn Valves with Nonmetallic Seats"),
                _support(ISO_10497, "Testing of valves — Fire type-testing requirements"),
            ],
        }
    if valve_type in ("GA", "GL", "CH"):
        return {
            "rule": "Fire-test per API 607 / API 6FA / ISO 10497 (when soft seats / seals are present)",
            "primary": _cite(ISO_10497, "Testing of valves — fire type-testing", 0, 0, ""),
            "supporting": [_support(API_607, "Quarter-turn fire test"), _support(API_6FA, "Trunnion ball fire test")],
        }
    if valve_type == "BF":
        return {
            "rule": "Butterfly fire test per ISO 10497 / API 6FA / API 607",
            "primary": _cite(ISO_10497, "Fire type-testing requirements", 0, 0, ""),
            "supporting": [],
        }
    return {"rule": "Fire test by agreement", "primary": _cite("By agreement","",0,0,""), "supporting": []}


def cite_marking_manufacturer() -> dict:
    return {
        "rule": "Markings on the valve shall be per MSS-SP-25; API 6D Table 7 enumerates required marking items",
        # Table 7 itself is on printed p.34 (PDF p.48) — cite that page, the value
        # MSS-SP-25 is the manufacturer-mark standard explicitly invoked there.
        "primary": _cite(API_6D, "Table 7 — Valve Marking", 34, _api6d(34),
                         "Body marking shall be MSS-SP-25 compliant; see Table 7 for the full required-item list"),
        "supporting": [_support(MSS_SP25, "Standard Marking System for Valves, Fittings, Flanges and Unions")],
    }


def cite_inspection_testing() -> dict:
    return {
        "rule": "Each valve shall be tested in the final assembled condition per API 6D §9 + API 598",
        "primary": _cite(API_6D, "9.1 General — pressure testing", 29, _api6d(29),
                         "Each valve shall be tested in the final assembled condition prior to shipment"),
        "supporting": [_support(API_598, "Valve Inspection and Testing — leakage acceptance criteria")],
    }


def cite_leakage_rate() -> dict:
    return {
        "rule": "Acceptance per API 598 (or ISO 5208 Rate G for metal-seated check valves)",
        "primary": _cite(API_598, "Valve Inspection and Testing — leakage acceptance criteria", 0, 0, ""),
        "supporting": [_support(ISO_5208, "Industrial valves — pressure testing of metallic valves — leakage rates")],
    }


def cite_hydrotest_shell() -> dict:
    return {
        "rule": "Hydrostatic shell test pressure = 1.5 × pressure rating @ 38 °C; duration per API 6D Table 5 (2 / 5 / 15 / 30 min by NPS)",
        "primary": _cite(API_6D, "9.3 Hydrostatic Shell Test + Table 5", 30, _api6d(30),
                         "Hydrostatic shell test pressure shall be 1.5 × the pressure rating; duration per Table 5"),
        "supporting": [],
    }


def cite_hydrotest_seat() -> dict:
    return {
        "rule": "Hydrostatic seat test = 1.1 × pressure rating @ 38 °C; duration per API 6D Table 6",
        "primary": _cite(API_6D, "9.4 Hydrostatic Seat Test + Table 6", 31, _api6d(31),
                         "The test pressure for all seat tests shall not be less than 1.1 times the pressure rating... at 100 °F (38 °C)"),
        "supporting": [],
    }


def cite_pneumatic_test() -> dict:
    return {
        "rule": "Low-pressure pneumatic seat test 5–7 barg per API 598",
        "primary": _cite(API_598, "Low-pressure pneumatic seat test (typical 5.5 barg)", 0, 0, ""),
        "supporting": [_support(API_6D, "Annex H supplementary gas test requirements")],
    }


def cite_material_certification() -> dict:
    return {
        # BS EN 10204 defines the document types (3.1, 3.2). Which type applies
        # to which parts (pressure-retaining vs other) is a project decision.
        "rule": "BS EN 10204 defines inspection document types (3.1, 3.2). Allocation (which parts get 3.2 vs 3.1) is project-specific.",
        "primary": _cite(EN_10204, "BS EN 10204 — Metallic Materials Inspection Documents (3.1, 3.2)", 0, 0, ""),
        "supporting": [
            _support(API_6D, "6.1 Material Specification — certification requirements"),
            _support("Project PMS certification section", "Allocates 3.2 to pressure-retaining parts and 3.1 to others"),
        ],
    }


def cite_finish() -> dict:
    return {
        # API 6D §10 establishes that non-corrosion-resistant valves SHALL be
        # coated per the manufacturer's (or project's) paint spec. The actual
        # paint-spec document number printed in the value is by definition
        # project-specific — API 6D points to it but doesn't define it.
        "rule": "Per API 6D §10: external coating per the project's paint spec document; the exact paint-spec ID is project-specific",
        "primary": _cite(API_6D, "10 Coating/Painting + Annex L External Coating for End Connections", 33, _api6d(33),
                         "All non-corrosion-resistant valves shall be coated or painted externally in accordance with the manufacturer's standards"),
        "supporting": [_support("Project Paint Specification", "Project-specific paint document — references the site coating standard")],
    }


def cite_bolts() -> dict:
    return {
        # The base bolting GRADE (B7M / L7M / etc.) is mandated by API 6D §6.7
        # in combination with NACE MR0175 sour-service hardness limits + the
        # piping-class material category. Any coating spec (e.g. XYLAR 2 +
        # XYLAN 1070, PTFE etc.) is explicitly project-specific and lives on
        # the project's bolting table — NOT in API 6D.
        "rule": "Base bolt grade per API 6D §6.7 Bolting + NACE MR0175 hardness limits; ANY coating / surface treatment is project-specific (project PMS bolting table)",
        "primary": _cite(API_6D, "6.7 Bolting", 23, _api6d(23),
                         "Bolting material shall be suitable for the specified valve service and pressure rating. Carbon and low-alloy steel bolting with hardness exceeding HRC 35 (HBW 321) shall not be used for valve applications where hydrogen embrittlement can occur"),
        "supporting": [
            _support("ASTM A193", "Standard Specification for Alloy-Steel and Stainless Steel Bolting (B7, B7M, B16…)"),
            _support("ASTM A320", "Bolting Materials for Low-Temperature Service (L7M…)"),
            _support(NACE_MR0175, "Sour-service bolting hardness limits — drives B7M / L7M selection"),
            _support("Project PMS bolting & gasket table", "Specific grade per piping class + any coating spec (XYLAR / PTFE / fluoropolymer)"),
        ],
    }


def cite_nuts() -> dict:
    return {
        "rule": "Base nut grade per ASTM A194 + API 6D §6.6 impact testing rules; ANY coating (e.g. XYLAR / XYLAN) is project-specific",
        "primary": _cite(API_6D, "6.7 Bolting + 6.6 Impact Testing (A194 Gr 7M / 2HM)", 23, _api6d(23),
                         "A 320 Gr L7M studs and A194 Gr 7M nuts shall be impact tested at -101°C"),
        "supporting": [
            _support("ASTM A194", "Standard Specification for Carbon and Alloy Steel Nuts"),
            _support("Project PMS bolting & gasket table", "Specific nut grade per piping class + any coating spec"),
        ],
    }


def cite_gaskets() -> dict:
    return {
        "rule": "Gaskets per ASME B16.20 — spiral wound or RTJ; project PMS bolting & gasket table fixes the grade",
        "primary": _cite(ASME_B1620, "Metallic Gaskets for Pipe Flanges — Ring Joint, Spiral Wound, Jacketed", 0, 0, ""),
        "supporting": [_support("Project PMS", "Bolting & gasket table specifies inner-ring grade")],
    }


def cite_gland_packing() -> dict:
    return {
        # API 615 §6.4 is the rule (asbestos-free flexible graphite). Any
        # additional yarn-reinforcement / corrosion-inhibitor specification is
        # project-specific and lives on the project's PMS materials section.
        "rule": "Asbestos-free flexible graphite stem packing per API 615 §6.4; specific reinforcement (e.g. Inconel braid, corrosion inhibitor) is project-specific",
        "primary": _cite(API_615, "6.4 Stem Sealing — Fugitive Emissions; flexible graphite", 13, _api615(13),
                         "Flexible graphite valve stem packing material is widely used"),
        "supporting": [
            _support(API_6D, "6 Materials — asbestos-free requirement"),
            _support("Project PMS materials section", "Reinforcement weave + corrosion-inhibitor formulation per project"),
        ],
    }


def cite_sour_service(is_nace: bool) -> dict:
    if is_nace:
        return {
            "rule": "NACE MR0175 / ISO 15156 compliance for materials in H2S service",
            "primary": _cite(NACE_MR0175, "Materials for use in H2S-containing environments in oil & gas production", 0, 0, ""),
            "supporting": [_support(API_6D, "References Section 2 — NACE MR0175 cited"),
                           _support(API_615, "§5.7 Sour Service")],
        }
    return {"rule": "Not required (non-sour service)", "primary": _cite("","",0,0,""), "supporting": []}


# ── Convenience: format a citation as a one-line provenance string ─────────

def format_citation(cite: dict, brief: bool = True) -> str:
    """Render a citation as the source string the engine emits.

    brief=True  → "API SPEC 6D §5.2 (p.13)"
    brief=False → "API SPEC 6D §5.2 (p.13) — 'Pressure-temperature ratings...'"
    """
    p = cite.get("primary", {})
    doc = p.get("doc", "?")
    sec = p.get("section", "")
    pp  = p.get("printed_page", 0)
    base = f"{doc} §{sec}" if sec else doc
    if pp:
        base += f" (p.{pp})"
    if not brief and p.get("quote"):
        base += f" — \"{p['quote']}\""
    return base


def citation_link(cite: dict) -> str | None:
    """Build a clickable URL from a citation, pointing to the cited PDF page.
    Returns a URL like '/api/standards/api-6d#page=27' or None if the doc
    isn't in the standards registry / has no on-disk PDF.
    """
    from .standards_registry import build_citation_url
    p = cite.get("primary", {})
    doc = p.get("doc", "")
    pdf_p = p.get("pdf_page") or 0
    printed = p.get("printed_page") or 0
    if pdf_p:
        return build_citation_url(doc, pdf_page=pdf_p)
    if printed:
        return build_citation_url(doc, printed_page=printed)
    return build_citation_url(doc) if doc else None


def citation_quote(cite: dict) -> str | None:
    """Return the verbatim quote from the cited PDF page that supports the
    value (None if the citation doesn't carry a quote).
    """
    p = cite.get("primary", {})
    q = p.get("quote", "")
    return q if q else None


# ── Top-level dispatcher ──────────────────────────────────────────────────

def get_citation(field: str, decoded, material_category: str = "", size_inches: float | None = None) -> dict:
    """Return the citation for a given datasheet field.

    `decoded` is a DecodedVDS (from vds_decoder).
    """
    vt = decoded.valve_type.value
    seat = decoded.seat_type.value if decoded.seat_type else "M"
    end = decoded.end_connection.value
    pc_letter = decoded.piping_class[:1] if decoded.piping_class else "A"
    pc_num_map = {"A":150,"B":300,"D":600,"E":900,"F":1500,"G":2500}
    pc_num = pc_num_map.get(pc_letter, 150)

    if field == "valve_standard":          return cite_valve_standard(vt)
    if field == "pressure_class":          return cite_pressure_class()
    if field == "end_connections":         return cite_end_connections(end)
    if field == "face_to_face":            return cite_face_to_face(vt)
    if field == "body_construction":       return cite_construction_body(vt)
    if field == "stem_construction":       return cite_construction_stem(vt)
    if field == "ball_construction":       return cite_construction_body(vt)
    if field == "seat_construction":       return cite_construction_seat(seat, vt)
    if field == "operation":               return cite_operation(vt, size_inches, pc_num)
    if field in ("body_material", "ball_material", "wedge_material", "disc_material",
                 "stem_material", "trim_material", "needle_material", "shaft_material",
                 "back_seat_material", "cover_material", "gland_material"):
        return cite_trim_material(material_category) if field != "body_material" else cite_body_material(material_category)
    if field == "fire_rating":             return cite_fire_rating(vt)
    if field == "marking_manufacturer":    return cite_marking_manufacturer()
    if field == "marking_purchaser":       return cite_marking_manufacturer()
    if field == "inspection_testing":      return cite_inspection_testing()
    if field == "leakage_rate":            return cite_leakage_rate()
    if field == "hydrotest_shell":         return cite_hydrotest_shell()
    if field == "hydrotest_closure":       return cite_hydrotest_seat()
    if field == "pneumatic_test":          return cite_pneumatic_test()
    if field == "material_certification":  return cite_material_certification()
    if field == "finish":                  return cite_finish()
    if field == "bolts":                   return cite_bolts()
    if field == "nuts":                    return cite_nuts()
    if field == "gaskets":                 return cite_gaskets()
    if field == "gland_packing":           return cite_gland_packing()
    if field == "sour_service":            return cite_sour_service(decoded.is_nace)
    return {"rule": "", "primary": _cite("Engineering rule (rule_engine.py)", "", 0, 0, ""), "supporting": []}
