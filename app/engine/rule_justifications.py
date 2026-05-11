"""rule_justifications.py — plain-English engineering justification per field.

For each datasheet field, this module returns a short paragraph that explains:
  1. The engineering rule that mandates the value
  2. Why this specific value applies for this VDS / class / size
  3. (When applicable) which portion is the project's addition vs the standard

Style: specific to the field — no generic "per the standard" filler. A piping
engineer should read it and understand WHY the value is what it is.

The text is rendered alongside the Value + Source-Derived + citation in the
chat preview modal and in column F of the downloaded XLSX.
"""
from __future__ import annotations


_PC_NUM = {"A": 150, "B": 300, "D": 600, "E": 900, "F": 1500, "G": 2500}


def _pc_num(piping_class: str) -> int:
    return _PC_NUM.get((piping_class[:1] if piping_class else "A").upper(), 150)


# ── Per-field justifications ──────────────────────────────────────────────

def _bolt_justify(material_category: str, is_nace: bool) -> str:
    if material_category == "LTCS_NACE":
        return ("Low-temp carbon-steel bolts in sour service: per API 6D §6.7, "
                "low-alloy steel bolts must be impact-tested for service down to "
                "−46 °C (API uses −101 °C standard impact test temperature) AND "
                "limited to HRC 35 hardness for H2S resistance per NACE MR0175. "
                "ASTM A 320 Gr. L7M is the only A 320 sub-grade meeting both. "
                "Any anti-corrosion coating (e.g. XYLAR 2 + XYLAN 1070) in the "
                "Value column is the project's own bolting-table specification.")
    if material_category in ("DSS", "SDSS", "SDSS_NACE"):
        return ("Duplex/super-duplex stainless body needs a bolt with matching "
                "corrosion class — per API 6D §6.7, ASTM A 453 Gr. 660 is the "
                "industry standard for duplex SS service (Inconel-grade strength "
                "+ chloride/H2S resistance). Standard A193 carbon-steel bolts "
                "would fail by chloride-induced stress cracking.")
    if material_category in ("SS316L", "SS316L_NACE", "TUBING_SS"):
        return ("Austenitic SS body — per API 6D §6.7, A 320 Gr. L7M bolts are "
                "used (impact-tested low-alloy steel, NACE-compliant hardness). "
                "Any coating in the Value column is project's PMS bolting-table "
                "addition for atmospheric corrosion protection.")
    if is_nace:
        return ("Carbon-steel bolts in sour (H2S) service: per API 6D §6.7 + "
                "NACE MR0175, hardness must NOT exceed HRC 35 to prevent "
                "sulfide-stress cracking. ASTM A 193 Gr. B7M is the only A 193 "
                "sub-grade that meets the HRC 35 limit (B7M = 'Modified', "
                "tempered to lower hardness than standard B7). The XYLAR + XYLAN "
                "coating in the Value column is the project's PMS spec — adds "
                "atmospheric-corrosion protection on top of the API 6D rule.")
    return ("Carbon-steel bolts: per API 6D §6.7, ASTM A 193 Gr. B7M is the "
            "industry standard for valves in service up to 480 °C. The Modified "
            "(M) grade ensures hardness ≤ HRC 35 — valid for both sweet and "
            "sour service (NACE-compliant). Any coating in the Value column is "
            "the project's PMS bolting-table addition.")


def _nut_justify(material_category: str, is_nace: bool) -> str:
    if material_category in ("LTCS_NACE", "SS316L", "SS316L_NACE", "TUBING_SS"):
        return ("Nuts must match the bolt grade per API 6D §6.6. ASTM A 194 "
                "Gr. 7ML is the matched-strength nut for A 320 L7M studs in "
                "low-temp / NACE service — both are tempered low-alloy grades "
                "with HRC 35 limit. Impact-tested at −101 °C.")
    if material_category in ("DSS", "SDSS", "SDSS_NACE"):
        return ("Duplex SS bolting uses ASTM A 453 Gr. 660 nuts to match the "
                "bolts (Inconel-grade strength). Standard A 194 carbon-steel "
                "nuts would not survive chloride-stress conditions.")
    return ("ASTM A 194 Gr. 2HM nuts are the matched-strength carbon-steel "
            "nut for A 193 Gr. B7M studs (per API 6D §6.6). The Modified "
            "(M) grade ensures hardness ≤ HRC 35 — NACE-compliant.")


def _body_justify(material_category: str) -> str:
    if material_category in ("CS", "CS_NACE"):
        return ("Carbon-steel body — per ASME B16.34 §6.1 Table 1 (Group 1 "
                "ferrous). The project's PMS specifies ASTM A105N for forged "
                "sizes (small NPS, where forging is economical) and ASTM A216 "
                "WCB for cast sizes (larger NPS, where casting is faster + "
                "cheaper). Both are widely-used Group 1 grades; the 1.5-inch "
                "/ 2-inch size split between forging and casting is a project "
                "convention.")
    if material_category == "LTCS_NACE":
        return ("Low-temp carbon-steel for sour service: ASTM A350 LF2 (forged) "
                "and A352 LCC (cast) are Group 1 grades certified for −46 °C "
                "minimum design metal temperature. Per API 6D §7.3 + ASME B16.34 "
                "§6.1, NACE MR0175 hardness limits also apply.")
    if material_category in ("SS316L", "SS316L_NACE"):
        return ("316L stainless body: ASME B16.34 §6.1 Table 1 Group 2 "
                "(austenitic). ASTM A182 F316L is the forged grade and A351 "
                "CF3M is the cast equivalent — both have ≤0.03% C ('L' grade) "
                "to prevent intergranular corrosion after welding.")
    if material_category == "DSS":
        return ("22%Cr Duplex stainless steel body — UNS S32205 (formerly "
                "S31803). Forged grade ASTM A182 F60 / cast grade A995 4A. "
                "Used for chloride-rich service where 316L would crack.")
    if material_category in ("SDSS", "SDSS_NACE"):
        return ("25%Cr Super-duplex SS body — UNS S32750. Forged ASTM A182 F53 "
                "/ cast ASTM A995 5A. Used for severe chloride + H2S service "
                "where standard duplex isn't enough.")
    if material_category == "CUNI":
        return ("Cu-Ni / Ni-Al-bronze body — ASTM B148 C95800 — used for raw "
                "seawater service where carbon steel and stainless would both "
                "fail by chloride pitting.")
    return f"Material per ASME B16.34 §6.1 selection for category {material_category}."


def _operation_justify(valve_type: str, size_inches: float | None, pc_num: int) -> str:
    if valve_type in ("BL", "BS", "BF", "DB"):
        return ("Quarter-turn valve operation per API 615 §7.1: a lever is "
                "adequate for small valves (≤ ~3-4″) where breakaway torque is "
                "manageable by hand. Larger valves need a worm-gear operator "
                "to multiply mechanical advantage — API 6D §5.13 limits the "
                "manual breakaway force to 360 N (80 lbf). The 4″/6″ thresholds "
                "in the Value column are the project's specific cutoffs.")
    if valve_type in ("GA", "GL"):
        return ("Multi-turn valve operation per API 615 §7.1: gate and globe "
                "valves use a hand-wheel for ordinary sizes. For larger sizes "
                "(typically NPS 14+ for gates, NPS 10+ for globes), a gearbox "
                "is needed because the stem thrust grows with bore + pressure. "
                "Project-specific size thresholds are in the Value column.")
    if valve_type == "NE":
        return ("Needle valves are inherently small (typ. ½″–2″) and use a "
                "T-bar / lever — no gear required. Operation per manufacturer "
                "standard, supplemented by ISO 15761 stem-design rules.")
    return "Operation per API 615 §7.1 + valve manufacturer standard."


def _ball_construction_justify(size_inches: float | None, pc_num: int) -> str:
    return ("Per API 6D §6.23 — Floating-ball vs Trunnion-mounted is decided "
            f"by size + pressure class. For Class {pc_num}: floating ball is "
            "allowed up to about 8″ (small enough that the ball can hold "
            "pressure against the downstream seat), trunnion-mount is required "
            "above. At higher classes, the trunnion threshold drops (e.g. 6″ "
            "for Class 300, 2″ for Class 600, all sizes for Class 900+) "
            "because the seat load grows faster than the ball can resist.")


def _stem_construction_justify(valve_type: str) -> str:
    if valve_type in ("BL", "BS", "DB"):
        return ("Per API 6D §6.0 (Design): all soft-seated ball, plug and "
                "butterfly valves shall be supplied with anti-static devices "
                "(ground path between stem and body to prevent static buildup "
                "in flammable service). Anti-blowout stem is mandated by "
                "API 6D + API 615 — prevents the stem ejecting from the body "
                "if pressure builds inside the bonnet.")
    if valve_type in ("GA", "GL"):
        return ("Per API 615 §4.1.1 + API 600 — gate/globe valves use Outside "
                "Screw and Yoke (OS&Y) stems: the stem rises out of the body "
                "as the valve opens (visual indication of position) and the "
                "threads are kept out of the process fluid. Back-seat is "
                "mandated by API 6D §6.14 for in-service packing replacement.")
    return "Stem design per API/ASME standards for this valve type."


def _seat_justify(seat_char: str) -> str:
    if seat_char == "T":
        return ("Soft (PTFE) seat — per API 615 §6.3, virgin or glass-fibre-"
                "reinforced PTFE is the industry standard for tight shut-off "
                "in service up to ~205 °C / 400 °F. Above that limit, PTFE "
                "creeps and metal seat is required. The 'self-energised, self-"
                "relieving, emergency sealant' wording in the Value column is "
                "project-specific seat-construction detail per API 6D §6.1.")
    if seat_char == "P":
        return ("PEEK (polyetheretherketone) seat — engineered polymer, used "
                "where service temp exceeds PTFE's limit (~205 °C) but soft-"
                "seat behaviour is still desired. Per API 615 §6.3, PEEK seat "
                "P-T ratings are by agreement (not in the standard table).")
    if seat_char == "M":
        return ("Metal seat with hard-facing — per API 615 §6.2 + API 6D §6.1, "
                "Stellite-overlay or Tungsten-Carbide-Coated (TCC) seats give "
                "tight shut-off at high temp, in abrasive service, or where "
                "soft-seat polymers can't survive. Min hardness 250 BHN with "
                "50 BHN body-vs-disc differential prevents galling.")
    return "Seat per API/ASME standards for this seat type."


def _gasket_justify(pc_num: int, end_char: str) -> str:
    if end_char in ("J", "JT") or pc_num >= 600:
        return ("RTJ flange face — per ASME B16.20 + ASME B16.5, ring-type "
                "joint gaskets (oct/octagonal section) are mandatory for "
                "Class 600+ flanges. The ring is harder than the flange "
                "groove material so it deforms to seal. Carbon-steel bodies "
                "use soft-iron rings; stainless bodies use SS316L rings; "
                "duplex bodies use UNS S31803/32750 rings.")
    return ("Spiral-wound gasket per ASME B16.20 — alternating SS316/316L "
            "windings + flexible-graphite filler. Used for raised-face "
            "flanges in Class 150-300. Filler grade and winding alloy are "
            "project decisions (per project PMS bolting & gasket table).")


def _gland_packing_justify() -> str:
    return ("Stem packing must be asbestos-free per API 615 §6.4 + API 6D §6 "
            "(asbestos banned in industrial service since 1990s). Flexible "
            "graphite is the de-facto industry standard — handles temperatures "
            "from cryogenic to ~650 °C, compatible with hydrocarbons and NACE "
            "sour service. Yarn-reinforcement (often Inconel braiding) and "
            "corrosion-inhibitor in the Value column are project-specific "
            "elaborations from the project's PMS.")


def _fire_rating_justify(valve_type: str) -> str:
    if valve_type in ("BL", "BS", "DB"):
        return ("Per API 6D §6.10 — ball valves with non-metallic seats must be "
                "fire-tested. The test depends on construction: Trunnion-mounted "
                "balls go through API 6FA (rigorous, 30-min burn, certified by "
                "third party); Floating balls go through API 607 / ISO 10497 "
                "(similar but accounts for ball rotation under pressure).")
    if valve_type in ("GA", "GL"):
        return ("Per API 6D §6.10 + ISO 10497 — gate/globe with non-metallic "
                "seals must pass API 607 / API 6FA / BS EN ISO 10497 fire test. "
                "Test ensures the valve maintains its sealing function during a "
                "30-min hydrocarbon fire and remains operable after burn-out.")
    if valve_type == "BF":
        return ("Triple-offset butterfly fire test per ISO 10497 / API 6FA / "
                "API STD 607. Wafer butterflies typically have soft seats and "
                "cannot pass full fire-test — limited to non-flammable service.")
    return "Fire test by agreement per API 6D §6.10."


def _hydrotest_shell_justify(size_inches: float | None) -> str:
    base = ("Per API 6D §9.3, hydrostatic shell test pressure is 1.5 × the "
            "valve's pressure rating @ 38 °C. The duration depends on size:")
    if size_inches:
        if size_inches <= 4:    dur = "2 minutes (NPS ≤ 4)"
        elif size_inches <= 10: dur = "5 minutes (NPS 6 to 10)"
        elif size_inches <= 18: dur = "15 minutes (NPS 12 to 18)"
        else:                   dur = "30 minutes (NPS ≥ 20)"
        return f"{base} {dur} per Table 5. Each valve must pass before shipping."
    return f"{base} per API 6D Table 5. Each valve must pass before shipping."


def _hydrotest_seat_justify(size_inches: float | None) -> str:
    base = ("Per API 6D §9.4, hydrostatic seat test pressure is 1.1 × the "
            "valve's pressure rating @ 38 °C — slightly higher than rating "
            "to verify the seat seals reliably even with pressure surge. "
            "Acceptance per ISO 5208 leakage rate: A (zero) for soft seats, "
            "D for metal seats. Duration:")
    if size_inches:
        if size_inches <= 4:    dur = "2 minutes (NPS ≤ 4)"
        elif size_inches <= 18: dur = "5 minutes (NPS 6 to 18)"
        else:                   dur = "10 minutes (NPS ≥ 20)"
        return f"{base} {dur} per Table 6."
    return f"{base} duration per Table 6."


def _face_to_face_justify(valve_type: str, size_inches: float | None, pc_num: int) -> str:
    if valve_type in ("BL", "BS"):
        return ("Per API 6D §5.4 + Annex C Table C.3 — ball-valve face-to-face "
                "(F2F) dimensions are mandatory in API 6D. Ball valves use the "
                "long-pattern F2F (ASME B16.10) so that you can swap a ball "
                "valve with a gate valve of the same NPS+class without re-"
                "fitting the piping. The exact mm value comes from the table "
                "row matching this valve's NPS / class / face type.")
    if valve_type in ("GA", "GL"):
        return ("Per API 6D §5.4 + Annex C Table C.1 + ASME B16.10 — gate and "
                "globe face-to-face are standardized so any compliant valve can "
                "be installed in a fixed piping run. The mm value comes from "
                "the table row for this valve's NPS / class / face type.")
    if valve_type == "BF":
        return ("Per API 609 — butterfly valves use Category B (long-pattern) "
                "F2F. Wafer/lug butterflies sit between flanges (no separate "
                "F2F) but the disc must clear the bore.")
    return "F2F per API 6D Annex C / ASME B16.10."


def _marking_justify() -> str:
    return ("Per API 6D §11 + Table 7, every valve must carry permanent body + "
            "nameplate markings using MSS-SP-25 standardized symbology. The 16 "
            "required items include: manufacturer name, pressure class, P-T "
            "rating, body material grade, trim ID, nominal size, ring-joint "
            "groove number, melt-heat number (traceability), and flow direction "
            "(check valves only). Marking enables operator identification, "
            "maintenance, and traceability after the valve is installed.")


def _inspection_justify() -> str:
    return ("Per API 6D §9 — every valve must pass: (1) Hydrostatic Shell Test "
            "at 1.5× rating per §9.3, (2) Hydrostatic Seat Test at 1.1× rating "
            "per §9.4, (3) Pneumatic Seat Test at 5–7 barg per §9.4.4.6 "
            "(optional, per agreement). Acceptance criteria are defined in "
            "API 598 (the test-and-inspection standard referenced by API 6D). "
            "Soft-seated valves: zero leak (ISO 5208 Rate A). Metal-seated: "
            "Rate D (a few drops/min permitted).")


def _leakage_justify() -> str:
    return ("Per API 598 leakage acceptance criteria — applied during the "
            "hydrostatic and pneumatic seat tests. Rate A (zero detectable) "
            "for soft-seated valves; Rate D for metal-seated; Rate G for "
            "metal-seated check valves (slightly higher tolerance because of "
            "swing/disc back-flow physics).")


def _pneumatic_justify() -> str:
    return ("Per API 598 — low-pressure pneumatic seat test at 5–7 barg "
            "(typically 5.5 barg) verifies seat integrity at low pressure "
            "where soft seals might bypass under hydrostatic test. Mandatory "
            "in API 6D §9.4.4.6 by agreement; commonly required for pipeline "
            "valves carrying hydrocarbons.")


def _certification_justify() -> str:
    return ("Per BS EN 10204 — material certificates accompany every valve. "
            "Type 3.2 (independent inspection by manufacturer + buyer/agent) "
            "is for pressure-retaining parts (body, bonnet, closure, stem); "
            "Type 3.1 (manufacturer's certificate) is for non-pressure parts "
            "(handle, name-plate). API 6D §6.1 requires this allocation; the "
            "specific 3.2-vs-3.1 split is the project's traceability decision.")


def _finish_justify() -> str:
    return ("Per API 6D §10 — non-corrosion-resistant valves must be coated "
            "externally per the manufacturer's standards (which usually means "
            "the project's paint specification). Internal coatings, threaded "
            "ends, and gasket sealing surfaces are NOT painted (per API 6D "
            "§10 last paragraph). The actual paint-spec document number in "
            "the Value column is the project's reference.")


def _valve_standard_justify(valve_type: str) -> str:
    if valve_type in ("BL", "BS"):
        return ("Per API 6D §1 + 4.1.3 — pipeline ball valves are designed to "
                "API SPEC 6D (covers full range NPS ½″ to 60″, classes 150 "
                "through 2500). For smaller process valves up to 24″ at 600#, "
                "ISO 17292 also applies (drop-in replacement spec used in "
                "Europe). Both specs together cover the full ball-valve "
                "design + manufacturing + testing rules.")
    if valve_type == "GA":
        return ("Per API 615 §4.1.1 — gate valves follow one of three API "
                "standards: API 600 (heavy-wall, NPS 1″+, refinery service), "
                "API 602 (compact small-bore ≤ NPS 4, ≤ Class 1500), or "
                "API 603 (corrosion-resistant alternative for stainless body). "
                "The valve type and size determine which one applies.")
    if valve_type == "GL":
        return ("Per API 615 §4.3 — globe valves follow API 602 (small bore) "
                "or BS EN ISO 15761 (process service). BS 1873 is the "
                "traditional British equivalent for petroleum/chemical service.")
    if valve_type == "CH":
        return ("Per API 615 §4.2 — check valves follow API 594 (wafer / lug / "
                "dual-plate types), API 6D (pipeline check), or BS 1868 (UK "
                "petroleum spec). The body style picks the standard.")
    if valve_type == "BF":
        return ("Per API 615 §4.1.4 — butterfly valves follow API 609 with "
                "two categories: Category A (rubber-lined, Class 150, basic "
                "isolation) and Category B (high-performance, double-/triple-"
                "offset, classes 150-600).")
    if valve_type == "DB":
        return ("DBB valves combine the function of two block valves + bleed "
                "in one body — per API 6D §3.1.10 definition. Design follows "
                "ASME B16.34 for pressure-containing parts; EEMUA 182 covers "
                "the specific DBB testing + functional requirements.")
    if valve_type == "NE":
        return ("Needle valves for instrumentation — design per BS EN ISO 15761 "
                "(process valves DN 100 and smaller), supplemented by ASME "
                "B16.34 for pressure-rating and API 602 for compact-valve "
                "wall-thickness rules.")
    return f"Valve type {valve_type} — design per applicable API/ISO/BS specification."


def _pressure_class_justify(pc_letter: str, pc_num: int) -> str:
    return (f"Per API 6D §5.2 + ASME B16.34 — pressure-temperature ratings come "
            f"from ASME B16.34 Group I/II/III tables. The piping class letter "
            f"'{pc_letter}' maps to ASME Class {pc_num}. Class {pc_num} ratings "
            f"are tabulated in ASME B16.34 against the body material's group "
            f"(carbon steel = Group I, austenitic SS = Group II, etc.).")


def _end_connection_justify(end_char: str, pc_num: int) -> str:
    if end_char == "R":
        return ("Per API 6D §5.7.1.1 + ASME B16.5 — Raised Face (RF) flange. RF "
                "is the standard flange face for Classes 150 through 600 in "
                "non-critical service. The raised portion concentrates the "
                "bolt load on the gasket. Below NPS 24, ASME B16.5; NPS 26+, "
                "ASME B16.47 Series A.")
    if end_char == "J":
        return ("Per API 6D §5.7.1.1 + ASME B16.5 — Ring-Type Joint (RTJ) "
                "flange. RTJ is mandatory for Class 600 and above where high "
                "pressure / temperature would cause an RF gasket to creep. The "
                "metal ring deforms in the groove for a positive metal-to-"
                "metal seal. API 6D §11 requires the ring-joint groove number "
                "to be marked on the flange OD.")
    if end_char == "F":
        return ("Per ASME B16.5 — Flat Face (FF) flange. Used in Class 150 with "
                "soft (full-face) gaskets, typically for cast-iron mating "
                "flanges or low-pressure utility service. Cannot be used at "
                "Class 300+.")
    if end_char == "T":
        return ("Per API 6D §5.9 + ASME B1.20.1 — NPT (National Pipe Thread "
                "Tapered) Female threaded end. Used for instrument valves, "
                "drain/vent, and small-bore connections. Limited to "
                "low-pressure service per ASME B16.34 wall-thickness rules.")
    if end_char == "JT":
        return ("RTJ flange + NPT-Female bleed connection (used for DBB "
                "instrument valves). Per API 6D §5.7.1.1 + ASME B1.20.1.")
    if end_char == "W":
        return ("Wafer / lug type — for butterfly + dual-plate check valves "
                "per API 594/609. The valve sits between two adjacent flanges, "
                "no separate flange machining.")
    if end_char == "H":
        return ("Hub / Compact-Flange end per Norsok L-005. Saves weight and "
                "space compared to ASME flanges, common on offshore platforms.")
    return f"End connection per API 6D §5.7.1.1."


# ── Top-level dispatcher ──────────────────────────────────────────────────

def get_justification(field: str, decoded, material_category: str = "",
                      size_inches: float | None = None) -> str | None:
    vt = decoded.valve_type.value
    seat = decoded.seat_type.value if decoded.seat_type else "M"
    pc = decoded.piping_class
    pc_num = _pc_num(pc)
    pc_letter = (pc[:1] if pc else "A").upper()
    end = decoded.end_connection.value
    is_nace = decoded.is_nace

    if field == "valve_standard":         return _valve_standard_justify(vt)
    if field == "pressure_class":         return _pressure_class_justify(pc_letter, pc_num)
    if field == "end_connections":        return _end_connection_justify(end, pc_num)
    if field == "face_to_face":           return _face_to_face_justify(vt, size_inches, pc_num)
    if field == "ball_construction":      return _ball_construction_justify(size_inches, pc_num)
    if field == "stem_construction":      return _stem_construction_justify(vt)
    if field == "body_construction":      return _ball_construction_justify(size_inches, pc_num) if vt in ("BL","BS") else _stem_construction_justify(vt)
    if field == "operation":              return _operation_justify(vt, size_inches, pc_num)
    if field == "seat_construction":      return _seat_justify(seat)
    if field == "seat_material":          return _seat_justify(seat)
    if field == "body_material":          return _body_justify(material_category)
    if field in ("ball_material","stem_material","trim_material","wedge_material",
                 "disc_material","gland_material","needle_material","shaft_material"):
        return f"Trim material matched to body per API 615 §6.2 — corrosion resistance ≥ body. {_body_justify(material_category)}"
    if field == "gland_packing":          return _gland_packing_justify()
    if field == "gaskets":                return _gasket_justify(pc_num, end)
    if field == "bolts":                  return _bolt_justify(material_category, is_nace)
    if field == "nuts":                   return _nut_justify(material_category, is_nace)
    if field == "marking_manufacturer":   return _marking_justify()
    if field == "marking_purchaser":      return _marking_justify()
    if field == "inspection_testing":     return _inspection_justify()
    if field == "leakage_rate":           return _leakage_justify()
    if field == "hydrotest_shell":        return _hydrotest_shell_justify(size_inches)
    if field == "hydrotest_closure":      return _hydrotest_seat_justify(size_inches)
    if field == "pneumatic_test":         return _pneumatic_justify()
    if field == "material_certification": return _certification_justify()
    if field == "fire_rating":            return _fire_rating_justify(vt)
    if field == "finish":                 return _finish_justify()
    if field == "sour_service":
        return ("NACE MR0175 / ISO 15156 — mandates material hardness, heat-"
                "treatment and welding limits for any component exposed to "
                "wet H2S. The 'N' modifier in the piping class triggers this. "
                "Without compliance, valves will fail by sulfide stress "
                "cracking within months.") if is_nace else "Not required (non-sour service)."

    # ── Decoded-from-VDS-code fields ──
    if field == "vds_no":
        return ("The VDS (Valve Datasheet) number is the user input that drives the "
                "entire datasheet generation. It encodes valve type + design + seat + "
                "piping class + end-connection. Decoded by app/engine/vds_decoder.py "
                "per the project's vds_config.json prefix mapping.")
    if field == "valve_type":
        return (f"Decoded from the VDS code's first 2 characters. '{vt}' = "
                f"{'Ball Valve' if vt=='BL' else 'Ball Valve (SDSS)' if vt=='BS' else 'Butterfly Valve' if vt=='BF' else 'Gate Valve' if vt=='GA' else 'Globe Valve' if vt=='GL' else 'Check Valve' if vt=='CH' else 'Double Block & Bleed' if vt=='DB' else 'Needle Valve' if vt=='NE' else vt} "
                "per the project's VDS naming convention. The valve type drives which "
                "API/ASME standard applies (e.g. Ball→API 6D, Gate→API 600/602/603).")
    if field == "piping_class":
        return (f"Decoded from the middle of the VDS code: '{pc}'. Piping classes are "
                "defined in the project's PMS document — each class specifies pressure "
                "rating, material category, NACE/low-temp flags, service envelope, and "
                "size range. The class determines design pressure, materials, and which "
                "end-connection face types are valid (e.g., A1=Class 150 RF only).")

    # ── Project PMS class data ──
    if field == "service":
        return (f"Service description for piping class '{pc}' from the project's PMS "
                "document. Each piping class is defined for a specific service envelope "
                "(media, pressure, temperature). The PMS picks the class first, then "
                "the class's service text is shown verbatim on the datasheet so the "
                "buyer/installer knows what fluid this valve handles.")
    if field == "size_range":
        return (f"Size range for piping class '{pc}' from the project's PMS class table. "
                "Larger classes (Class 1500+) have a smaller max NPS because high-"
                "pressure flanges become impractical above certain sizes (e.g. ASME "
                "B16.34 limits Class 2500 to NPS 12).")
    if field == "design_pressure":
        return (f"Pressure-temperature rating for class '{pc}' from the PMS P-T table, "
                "per ASME B16.34. Format: 'pressure_max @ temp_min, pressure_min @ "
                "temp_max'. The two endpoints define the operating envelope; valves "
                "designed for this class can hold the lower pressure at the higher "
                "temperature, derated linearly between.")
    if field == "min_design_temp":
        return ("Minimum design temperature from the project's PMS class data — drives "
                "low-temperature material selection (LF2 / LCC for ferrous below "
                "−29 °C) and Charpy impact-testing requirements (per API 6D §7.3).")
    if field == "max_design_temp":
        return ("Maximum design temperature from the PMS class data — drives upper-"
                "temperature material limits (e.g. PTFE seat capped at ~205 °C) and "
                "P-T derating per ASME B16.34.")
    if field == "design_code":
        return ("ASME B31.3 — Process Piping Code. Governs the mechanical design + "
                "stress analysis of the piping system (and by extension the valves "
                "in it). API 6D §5.1 references B31.3 / B31.4 / B31.8 as recognized "
                "design codes for valve calculations.")
    if field == "corrosion_allowance":
        return ("Corrosion allowance per the project's pipe class service index. Added "
                "to the calculated wall thickness so the body still meets the minimum "
                "after corrosion over the design life. Stainless / nickel-alloy bodies "
                "typically use 0 mm (NIL); carbon steel typically 1.5-3 mm.")
    if field == "nace_compliant":
        return ("Set when the piping class includes 'N' modifier (e.g., A1N). NACE "
                "MR0175 / ISO 15156 compliance is then required throughout — body "
                "material hardness ≤ 22 HRC, bolts B7M / L7M (HRC ≤ 35), no copper "
                "alloy in stem, etc.")
    if field == "low_temperature":
        return ("Set when the piping class includes 'L' modifier (e.g., A1L, A1LN). "
                "Triggers low-temperature material rules: A350 LF2 (forged) / A352 LCC "
                "(cast) bodies, A320 L7M bolts, full Charpy impact testing per ASME "
                "B16.34.")

    # ── Engineering construction details (universal rules + project conv.) ──
    if field == "antistatic_device":
        return ("Per API 6D §6.0 — soft-seated quarter-turn valves (ball, plug, "
                "butterfly) shall be supplied with an antistatic device. This is a "
                "ground path (typically a spring contact) between the stem and body "
                "to drain static charge from the ball/disc, preventing ignition "
                "in flammable hydrocarbon service.")
    if field == "asbestos_free":
        return ("Per API 6D §6.1 + API 615 §6.4 — asbestos has been banned from "
                "valve packing, gaskets, and seals since the 1990s due to occupational "
                "health regulations. Replacement materials are flexible graphite, "
                "PTFE, RPTFE, and aramid-reinforced compounds.")
    if field == "auxiliary_connections":
        return ("Per API 6D §6.18 — drain, vent, and sealant lines on valves shall be "
                "flanged or welded (not socket-weld or threaded for primary pressure "
                "containment). Threaded ends are allowed only for terminating fittings "
                "(plugs, blanks).")
    if field == "ball_mounting_type":
        return ("Per API 6D §6.23 — Floating-ball vs Trunnion-mounted is decided by "
                "size + pressure class. 'Mixed' indicates a configuration where some "
                "sizes within the class fall on each side of the threshold; vendor "
                "supplies appropriate type per actual ordered NPS.")
    if field == "body_form":
        return ("Per API 6D §7.5 — Forged ASTM A105N or equivalent for valves NPS "
                "≤ 1.5\" because forging gives finer grain structure (better strength + "
                "Charpy impact). NPS ≥ 2\" can be cast (A216 WCB) for cost — casting is "
                "fast for large bodies but requires NDE per API 6D §8.6 / MSS SP-55.")
    if field == "bolt_plating":
        return ("Cadmium plating is BANNED on valve bolts in oil + gas service due "
                "to embrittlement risk in H2S environments and toxicity. XYLAN 1070 "
                "or equivalent fluoropolymer coating is the project's substitute "
                "(provides corrosion + galling protection without Cd hazards).")
    if field == "casting_quality_standard":
        return ("Per API 6D §8.6 — all cast bodies shall be visually inspected per "
                "MSS SP-55 (the industry standard for steel-casting acceptance "
                "criteria). Type 1 surface defects = none acceptable; Types 2-12 = "
                "A and B levels only.")
    if field == "design_life":
        return ("15-year design life is the project's specified service life per "
                "MY-K-20-PI-SP-0002 §6.8. Drives material corrosion-allowance "
                "calculations and packing/seal renewal intervals.")
    if field == "elastomer_requirement":
        return ("Per API 6D §6.0 — elastomers in hydrocarbon gas/liquid service with "
                "H2, CO2 or methane content must have proven resistance to explosive "
                "decompression. Max O-ring section ≤ 7 mm (0.275 in) per API 6D §6.0 "
                "to limit gas-trap volume. Vendor must demonstrate the squeeze + fill "
                "ratios meet ED-resistance.")
    if field == "extended_stem":
        return ("Cryogenic / low-temperature service: stem extension keeps the gland "
                "packing above the cold ice-formation zone (per MSS SP-134). Length "
                "scales with NPS — small valves get 75 mm extensions; larger get 100-"
                "150 mm to keep the gland accessible without disassembling the line.")
    if field == "fire_test":
        return ("Per API 6D §6.10 — every soft-seated valve in flammable HC service "
                "must pass a 30-minute fire-resistance test per API 607 / API 6FA / "
                "BS EN ISO 10497, witnessed by an approved third-party agency. The "
                "test certificate is supplied with the valve dossier.")
    if field == "flange_face_note":
        return ("Per API 6D §5.7.1.1 — Class 150 flanges use Raised Face (RF) per "
                "ASME B16.5; Class 600+ uses Ring-Type Joint (RTJ) for tighter sealing "
                "under high pressure. The project PMS specifies which face type "
                "applies per class.")
    if field == "flange_surface_finish":
        return ("Per ASME B46.1 / MSS SP-6 — RF gasket-bearing surfaces require "
                "125-250 µin Ra serrated finish (concentric or phonographic spiral) "
                "to grip the gasket. RTJ groove finish: 63 µin Ra max so the metal "
                "ring deforms cleanly into the groove.")
    if field == "fugitive_emissions_test":
        return ("Per ISO 15848-1 — measures stem-leak rate over thermal cycles. "
                "Tightness Class BH (≤ 50 ppmv methane) is required for hydrocarbon "
                "service. Endurance Class CC1/CO1 means 205 mechanical + 2 thermal "
                "cycles. Mandatory for hydrocarbon-service valves to control emissions.")
    if field == "functional_test":
        return ("Per API 6D §9.8 — every valve cycles 5 times at the manufacturer's "
                "shop, 5 at fabrication yard, 5 offshore at final installation, all "
                "at full rated pressure. Verifies smooth open/close operation under "
                "real differential pressure, not just shop conditions.")
    if field == "lever_handwheel":
        return ("Per API 615 §7.1 — lever / handwheel material must withstand "
                "the operator's force without bending. Solid-cast iron (ASTM A47 or "
                "A220) hot-dip galvanized OR SS316 — hot-dip galvanizing gives "
                "long-term atmospheric protection on offshore platforms.")
    if field == "lifting_lug":
        return ("Per API 6D §6.25 — valves ≥ 25 kg shall have welded/forged lifting "
                "lugs. Each lug designed for 2× the lifted weight, with up to 5° tilt "
                "off-vertical during a non-ideal lift. Required for safe handling "
                "during installation + maintenance.")
    if field == "locks":
        return ("Per API 6D §6.17 — lockable valves have a padlock provision in BOTH "
                "fully-open and fully-closed positions. Required for piping isolations "
                "as part of Lock-Out / Tag-Out (LOTO) procedures during maintenance.")
    if field == "max_handwheel_diameter":
        return ("Per API 6D §5.13 (Errata 9) — hand-wheel diameter shall not exceed "
                "1016 mm (40 in). The 750 mm in the value is the project's tighter "
                "limit per MY-K-20-PI-SP-0002 §6.11.2 to keep the operator station "
                "reasonable in size.")
    if field == "max_lever_length":
        return ("Project specifies max 500 mm each side of the stem axis per MY-K-20-"
                "PI-SP-0002 §6.11.2. Limits operator-applied torque to a safe value "
                "(per API 6D §5.13's 360 N max breakaway force).")
    if field == "max_torque":
        return ("Project torque limits: 150 Nm handwheel, 270 Nm lever per the project "
                "spec. Caps operator effort so a single person can open/close the "
                "valve. If breakaway exceeds these, gear operator is required.")
    if field == "nameplate":
        return ("Per API 6D §11 + MSS-SP-25 — every valve has a permanently attached "
                "SS316 nameplate, 3 mm thick, with 16 marking items: manufacturer + "
                "tag number + body material + trim + ratings. Stainless plate ensures "
                "the marking survives corrosion + paint coats over the design life.")
    if field == "ndt_extent":
        return ("Non-destructive examination scope per API 6D Annex G/J — alloy steels "
                "and NACE materials require 100% radiography (RT) of body welds + "
                "key transitions. Carbon steel below Class 1500 may use partial RT. "
                "ASME B16.34 Annex B governs the acceptance criteria.")
    if field == "operating_force":
        return ("Per API 6D §5.13 — max operating force at the handwheel periphery "
                "shall not exceed 360 N (80 lbf). Project tightens this to 45 kg "
                "(100 lbs) breakaway, 35 kg (75 lbs) running — ensures one operator "
                "can comfortably open + close without auxiliary tools.")
    if field == "position_indicator":
        return ("Per API 6D §5.16 — every valve fitted with a manual or powered "
                "actuator must have a visible indicator showing OPEN vs CLOSED. For "
                "ball/plug, the wrench itself doubles as the indicator: in-line = open, "
                "transverse = closed. Cannot be assembled to falsely indicate position.")
    if field == "pressure_test_sequence":
        return ("Per API 6D §9.1 — pressure tests in fixed sequence: (1) backseat "
                "(if present), (2) hydrostatic shell at 1.5×, (3) hydrostatic seat "
                "at 1.1×, (4) low-pressure pneumatic. Each test must pass before the "
                "next; results documented in the valve dossier.")
    if field == "pressure_test_standard":
        return ("Designed per ASME B16.34 (wall-thickness + pressure rating); pressure-"
                "tested per API STD 598 (the global valve inspection-and-testing "
                "standard). API 598 specifies test fluid, durations, and leakage "
                "acceptance criteria.")
    if field == "pressure_testing_standards":
        return ("Per API STD 598 (general valve testing), BS EN ISO 5208 (leakage "
                "rates A through G), and BS 6755 (production pressure-testing). "
                "Together they define the test method, durations, and pass/fail "
                "criteria — referenced by API 6D §9.")
    if field == "quality_system":
        return ("Per API 6D §1.3 + Section 8 — manufacturer must operate a documented "
                "quality management system meeting BS EN ISO 9001. Covers design "
                "control, procurement, NDE, traceability, and final inspection. "
                "Required for the valve to carry the API monogram.")
    if field == "resilient_seat_note":
        return ("Per API 615 §6.3 — preferred resilient seat materials are Nitrile "
                "(general HC), Viton (high-temp + chemical), or Reinforced PTFE "
                "(broadest range). Choice depends on service media + temperature; "
                "manufacturer confirms compatibility for the specific fluid.")
    if field == "seal_material":
        return ("Per API 615 §6.3 + API 6D §6 — body seal between halves typically "
                "uses PTFE (broadest chemical range) or Viton AED (Anti-Explosive-"
                "Decompression grade for gas service). Project may specify alternates "
                "(e.g., FFKM for methanol or amine service).")
    if field == "seal_material_note":
        return ("Per project PMS — FFKM (perfluoroelastomer) is recommended for "
                "methanol/glycol service per MY-K-20-PI-SP-0002 §6.0. Standard FKM "
                "(Viton) swells unacceptably in methanol; FFKM resists.")
    if field == "spring_material":
        return ("Per API 6D §6 + industry practice — springs use Inconel 718 / 750 "
                "(nickel-alloy precipitation-hardened steel). Resists stress relaxation "
                "at high temperature, sour service, and chloride attack — standard "
                "valve-trim material for over 50 years.")
    if field == "welding_procedure":
        return ("Per API 6D §7.2 — Welding Procedure Specification (WPS) qualified "
                "per BS EN 288-2 (or equivalent ASME IX); Procedure Qualification "
                "Record (PQR) per BS EN 287-1. All welding shall be performed in "
                "accordance with ASME B31.3.")
    if field == "datasheet_notes":
        return ("Standard footer notes block — combines: (1) data-sheet-completion "
                "instruction (vendor must return signed), (2) reference to PMS doc, "
                "(3) hydrotest pressure formulas (1.5× shell, 1.1× seat), (4) bolt + "
                "stem material rules, (5) coating spec. NACE classes add Note 6 "
                "(NACE MR0175 compliance).")

    # ── Valve-type-specific construction details ──
    if field == "back_seat_construction":
        return ("Per API 6D §6.14 — gate/globe valves shall have a renewable "
                "back-seat: when the stem is fully open, the back of the wedge/disc "
                "engages a hardened seating ring. This allows the gland packing to "
                "be repacked with the valve still in service (under pressure) — a "
                "major maintenance advantage over valves without back-seats.")
    if field == "backseat":
        return ("Per API 6D §6.14 — back-seat is a secondary stem seal that activates "
                "when the valve is fully open. Allows in-service packing replacement. "
                "Required for all gate / globe valves; optional but common for needle "
                "valves on critical lines.")
    if field == "bonnet_material":
        return ("Bonnet material per ASME B16.34 §6.1 — typically matches the body "
                "material since both are pressure-retaining. Project's PMS may "
                "specify a slightly different grade for cost (cast bonnet on a forged "
                "body etc.); both must be in the same Group (1/2/3).")
    if field == "disc_construction":
        return ("Per API 615 §4.3 — globe-valve disc options: (a) flat-disc "
                "(throttling but not bubble-tight), (b) plug-disc (better wear), "
                "(c) ball-disc (true bubble-tight). All hard-faced (Stellite overlay) "
                "for long life. Plug-disc is the industry default for process service.")
    if field == "hardness_requirement":
        return ("Per API 615 §6.2 — for metal-to-metal seats: body seat and "
                "disc/wedge shall be ≥ 250 BHN with a minimum 50 BHN differential "
                "(seat softer than disc). The differential prevents galling — without "
                "it, the seats weld themselves shut on first cycle.")
    if field == "hinge_pin_material":
        return ("Swing-check hinge pin: matches body trim grade per API 615 §6.2. "
                "Pin runs in a bushing in the body — both must be at least as "
                "corrosion-resistant as the body, OR overlay-hardened for wear "
                "resistance. Most common choices: A182 F316/F316L for SS service, "
                "Inconel 625 for high-corrosion service.")
    if field == "minimum_bore":
        return ("Per API 6D §6.4 — for needle valves used in instrument connections, "
                "minimum bore = 10 mm (3/8\"). Smaller bores get plugged by particulates "
                "in chemical-injection or hypochlorite service. Project's PMS may "
                "specify a larger bore for severe service.")
    if field == "packing_construction":
        return ("Per API 6D §6.16 + API 615 §6.4 — gate/globe stem seal uses "
                "live-load (spring-energized) gland follower with renewable packing "
                "rings. Live-load means the gland-bolt springs maintain compression "
                "as the packing wears, extending re-tightening intervals from weeks "
                "to years.")
    if field == "wedge_construction":
        return ("Per API 615 §4.1.1 + API 600 — gate-valve wedge type by NPS: solid "
                "wedge for ≤ 1.5\" (one piece, simple), flexible wedge for > 1.5\" (two "
                "halves with flex-in-the-middle to handle thermal misalignment between "
                "body and seats). Flexible wedge gives better long-term sealing in "
                "thermal-cycling service.")
    return None
