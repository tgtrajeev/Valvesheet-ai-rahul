"""standards_tables.py — API SPEC 6D tables transcribed verbatim with citations.

Every table here was transcribed from the API SPEC 6D PDF (24th Edition, 2014,
including Errata 1-9). Each lookup returns the value AND its source citation
so the engine can produce datasheets whose dimensional values are demonstrably
sourced from the standard, not hand-coded.

Page numbering convention
-------------------------
    "printed_page" = the number printed on the PDF page (used in citations)
    "pdf_page"     = 1-based PDF page index (so the user can Ctrl+G to it)

Tables transcribed
------------------
    Table 1   — Minimum Bore for Full-opening Valves (printed p.11, PDF p.25)
    Table 2   — Thread/Pipe Sizes for Drains          (printed p.17, PDF p.31)
    Table 5   — Min Duration of Hydrostatic Shell Tests (printed p.31, PDF p.45)
    Table 6   — Min Duration of Seat Tests             (printed p.31, PDF p.45)
    Table 7   — Valve Marking Requirements             (printed p.34, PDF p.48)
    Table C.1 — Gate Valves face-to-face / end-to-end  (printed pp.59-62, PDF pp.73-76)
    Table C.3 — Ball Valves face-to-face / end-to-end  (printed pp.69-73, PDF pp.83-87)
"""
from __future__ import annotations

# ── Citation helper ────────────────────────────────────────────────────────

def cite(table: str, printed_page: int, pdf_page: int) -> str:
    return f"API SPEC 6D Table {table} (printed p.{printed_page} / PDF p.{pdf_page})"


# ── Table 1 — Minimum Bore for Full-opening Valves ────────────────────────
#  Bore = (inches, millimeters); — entries omitted (not specified in std).

TABLE_1_MIN_BORE_FULL_OPENING = {
    # NPS: { class_label : (inch, mm) }
    "1/2":  {"150_to_600": (0.50, 13),  "900": (0.50, 13),  "1500": (0.50, 13),  "2500": (0.50, 13)},
    "3/4":  {"150_to_600": (0.75, 19),  "900": (0.75, 19),  "1500": (0.75, 19),  "2500": (0.75, 19)},
    "1":    {"150_to_600": (1.00, 25),  "900": (1.00, 25),  "1500": (1.00, 25),  "2500": (1.00, 25)},
    "1-1/4":{"150_to_600": (1.25, 32),  "900": (1.25, 32),  "1500": (1.25, 32),  "2500": (1.25, 32)},
    "1-1/2":{"150_to_600": (1.50, 38),  "900": (1.50, 38),  "1500": (1.50, 38),  "2500": (1.50, 38)},
    "2":    {"150_to_600": (1.94, 49),  "900": (1.94, 49),  "1500": (1.94, 49),  "2500": (1.69, 42)},
    "2-1/2":{"150_to_600": (2.44, 62),  "900": (2.44, 62),  "1500": (2.44, 62),  "2500": (2.06, 52)},
    "3":    {"150_to_600": (2.94, 74),  "900": (2.94, 74),  "1500": (2.94, 74),  "2500": (2.44, 62)},
    "4":    {"150_to_600": (3.94, 100), "900": (3.94, 100), "1500": (3.94, 100), "2500": (3.44, 87)},
    "6":    {"150_to_600": (5.94, 150), "900": (5.94, 150), "1500": (5.69, 144), "2500": (5.19, 131)},
    "8":    {"150_to_600": (7.94, 201), "900": (7.94, 201), "1500": (7.56, 192), "2500": (7.06, 179)},
    "10":   {"150_to_600": (9.94, 252), "900": (9.94, 252), "1500": (9.44, 239), "2500": (8.81, 223)},
    "12":   {"150_to_600": (11.94, 303),"900": (11.94, 303),"1500": (11.31, 287),"2500": (10.44, 265)},
    "14":   {"150_to_600": (13.19, 334),"900": (12.69, 322),"1500": (12.44, 315),"2500": (11.50, 292)},
    "16":   {"150_to_600": (15.19, 385),"900": (14.69, 373),"1500": (14.19, 360),"2500": (13.13, 333)},
    "18":   {"150_to_600": (17.19, 436),"900": (16.69, 423),"1500": (16.00, 406),"2500": (14.75, 374)},
    "20":   {"150_to_600": (19.19, 487),"900": (18.56, 471),"1500": (17.88, 454),"2500": (16.50, 419)},
    "22":   {"150_to_600": (21.19, 538),"900": (20.56, 522),"1500": (19.69, 500),"2500": None},
    "24":   {"150_to_600": (23.19, 589),"900": (22.44, 570),"1500": (21.50, 546),"2500": None},
    "26":   {"150_to_600": (24.94, 633),"900": (24.31, 617),"1500": (23.38, 594),"2500": None},
    "28":   {"150_to_600": (26.94, 684),"900": (26.19, 665),"1500": (25.25, 641),"2500": None},
    "30":   {"150_to_600": (28.94, 735),"900": (28.06, 712),"1500": (27.00, 686),"2500": None},
    "32":   {"150_to_600": (30.69, 779),"900": (29.94, 760),"1500": (28.75, 730),"2500": None},
    "34":   {"150_to_600": (32.69, 830),"900": (31.81, 808),"1500": (30.50, 775),"2500": None},
    "36":   {"150_to_600": (34.44, 874),"900": (33.69, 855),"1500": (32.25, 819),"2500": None},
    "38":   {"150_to_600": (36.44, 925),"900": (35.63, 904),"1500": None,        "2500": None},
    "40":   {"150_to_600": (38.44, 976),"900": (37.63, 956),"1500": None,        "2500": None},
    "42":   {"150_to_600": (40.19, 1020),"900":(39.63, 1006),"1500": None,        "2500": None},
    "48":   {"150_to_600": (45.94, 1166),"900":(45.25, 1149),"1500": None,        "2500": None},
}


def _class_bucket(pressure_class: int) -> str:
    if pressure_class <= 600:  return "150_to_600"
    if pressure_class == 900:  return "900"
    if pressure_class == 1500: return "1500"
    if pressure_class == 2500: return "2500"
    return "150_to_600"


def lookup_min_bore(nps: str, pressure_class: int) -> tuple[str, str] | None:
    """Returns ('1.94 in (49 mm)', citation) or None if not in table.
    Per API 6D §4.2.2, reduced-opening valves take one (or two) sizes below
    nominal — but this lookup is for FULL-opening valves only.
    """
    row = TABLE_1_MIN_BORE_FULL_OPENING.get(str(nps))
    if not row:
        return None
    cell = row.get(_class_bucket(pressure_class))
    if cell is None:
        return None
    inch, mm = cell
    return (f"{inch:.2f} in. ({mm} mm)", cite("1", 11, 25))


# ── Table 2 — Thread/Pipe Sizes for Drains ─────────────────────────────────

def lookup_drain_thread_size(nps_value: float) -> tuple[str, str]:
    """Drain thread/pipe size per API 6D Table 2. nps_value is decimal NPS (0.5, 4, 8, 12)."""
    if nps_value <= 1.5:
        return ('1/4" (8 mm)', cite("2", 17, 31))
    if nps_value <= 8:
        return ('1/2" (15 mm)', cite("2", 17, 31))
    return ('1" (25 mm)', cite("2", 17, 31))


# ── Table 5 — Minimum Duration of Hydrostatic Shell Tests ──────────────────

def lookup_hydrotest_shell_duration(nps_value: float) -> tuple[str, str]:
    """Returns ('5 min', citation)."""
    if nps_value <= 4:                        minutes = 2
    elif nps_value <= 10:                     minutes = 5
    elif nps_value <= 18:                     minutes = 15
    else:                                     minutes = 30
    return (f"{minutes} min", cite("5", 31, 45))


# ── Table 6 — Minimum Duration of Seat Tests ───────────────────────────────

def lookup_seat_test_duration(nps_value: float) -> tuple[str, str]:
    if nps_value <= 4:                        minutes = 2
    elif nps_value <= 18:                     minutes = 5
    else:                                     minutes = 10
    return (f"{minutes} min", cite("6", 31, 45))


# ── Table 7 — Valve Marking Requirements ───────────────────────────────────

TABLE_7_MARKING = [
    {"item": "1a", "marking": "Manufacturer's name",                        "location": "On body and/or nameplate"},
    {"item": "1b", "marking": "Trademark or mark (optional)",               "location": "On body and/or nameplate"},
    {"item": "2a", "marking": "Pressure class",                             "location": "On both body and nameplate"},
    {"item": "2b", "marking": "Intermediate pressure rating (upon agreement)", "location": "On body and nameplate"},
    {"item": "3",  "marking": "Pressure-temperature rating (max P at max T; max P at min T)", "location": "On nameplate"},
    {"item": "4",  "marking": "Face-to-face / end-to-end dimensions if not in Table C.1-C.5", "location": "On nameplate"},
    {"item": "5a", "marking": "Body / closure / end connection material grade", "location": "On body, closure, end connection AND nameplate"},
    {"item": "5b", "marking": "Body / closure / end connection melt identification (heat number)", "location": "On body / closure / end connection only"},
    {"item": "6a", "marking": "Bonnet/cover material grade",                "location": "On bonnet/cover"},
    {"item": "6b", "marking": "Bonnet/cover melt identification (heat number)", "location": "On bonnet/cover"},
    {"item": "7",  "marking": "Trim identification (stem and sealing-face material if different from body)", "location": "On nameplate"},
    {"item": "8",  "marking": "Nominal valve size (full-bore or reduced-bore designation per §5.3)", "location": "On both body and nameplate"},
    {"item": "9",  "marking": "Ring joint groove number",                   "location": "On valve flange OD"},
    {"item": "10", "marking": "SMYS units of valve ends (where applicable)", "location": "On body weld ends"},
    {"item": "11", "marking": "Flow direction (for check valves only)",     "location": "On body"},
    {"item": "12", "marking": "Seat sealing direction (only when one seat is unidirectional)", "location": "On separate identification plate"},
]


def get_marking_checklist() -> tuple[list[dict], str]:
    """Returns (full-table-as-list, citation) — used to render the Marking section."""
    return (TABLE_7_MARKING, cite("7", 34, 48))


# ── Table C.1 — Gate Valves face-to-face dimensions ────────────────────────
# Layout: TABLE_C[valve_type][pressure_class][nps] = {"RF": (A_in, A_mm), "BW": (B_in, B_mm), "RTJ": (C_in, C_mm)}

TABLE_C1_GATE = {
    150: {
        "2":    {"RF": (7.00, 178), "BW": (8.50, 216), "RTJ": (7.50, 191)},
        "2-1/2":{"RF": (7.50, 191), "BW": (9.50, 241), "RTJ": (8.00, 203)},
        "3":    {"RF": (8.00, 203), "BW": (11.13, 283),"RTJ": (8.50, 216)},
        "4":    {"RF": (9.00, 229), "BW": (12.00, 305),"RTJ": (9.50, 241)},
        "6":    {"RF": (10.50, 267),"BW": (15.88, 403),"RTJ": (11.00, 279)},
        "8":    {"RF": (11.50, 292),"BW": (16.50, 419),"RTJ": (12.00, 305)},
        "10":   {"RF": (13.00, 330),"BW": (18.00, 457),"RTJ": (13.50, 343)},
        "12":   {"RF": (14.00, 356),"BW": (19.75, 502),"RTJ": (14.50, 368)},
        "14":   {"RF": (15.00, 381),"BW": (22.50, 572),"RTJ": (15.50, 394)},
        "16":   {"RF": (16.00, 406),"BW": (24.00, 610),"RTJ": (16.50, 419)},
        "18":   {"RF": (17.00, 432),"BW": (26.00, 660),"RTJ": (17.50, 445)},
        "20":   {"RF": (18.00, 457),"BW": (28.00, 711),"RTJ": (18.50, 470)},
        "24":   {"RF": (20.00, 508),"BW": (32.00, 813),"RTJ": (20.50, 521)},
    },
    300: {
        "2":    {"RF": (8.50, 216), "BW": (8.50, 216), "RTJ": (9.13, 232)},
        "2-1/2":{"RF": (9.50, 241), "BW": (9.50, 241), "RTJ": (10.13, 257)},
        "3":    {"RF": (11.13, 283),"BW": (11.13, 283),"RTJ": (11.75, 298)},
        "4":    {"RF": (12.00, 305),"BW": (12.00, 305),"RTJ": (12.63, 321)},
        "6":    {"RF": (15.88, 403),"BW": (15.88, 403),"RTJ": (16.50, 419)},
        "8":    {"RF": (16.50, 419),"BW": (16.50, 419),"RTJ": (17.13, 435)},
        "10":   {"RF": (18.00, 457),"BW": (18.00, 457),"RTJ": (18.63, 473)},
        "12":   {"RF": (19.75, 502),"BW": (19.75, 502),"RTJ": (20.38, 518)},
        "14":   {"RF": (30.00, 762),"BW": (30.00, 762),"RTJ": (30.63, 778)},
        "16":   {"RF": (33.00, 838),"BW": (33.00, 838),"RTJ": (33.63, 854)},
        "18":   {"RF": (36.00, 914),"BW": (36.00, 914),"RTJ": (36.63, 930)},
        "20":   {"RF": (39.00, 991),"BW": (39.00, 991),"RTJ": (39.75, 1010)},
        "24":   {"RF": (45.00, 1143),"BW": (45.00, 1143),"RTJ": (45.88, 1165)},
    },
    600: {
        "2":    {"RF": (11.50, 292),"BW": (11.50, 292),"RTJ": (11.63, 295)},
        "3":    {"RF": (14.00, 356),"BW": (14.00, 356),"RTJ": (14.13, 359)},
        "4":    {"RF": (17.00, 432),"BW": (17.00, 432),"RTJ": (17.13, 435)},
        "6":    {"RF": (22.00, 559),"BW": (22.00, 559),"RTJ": (22.13, 562)},
        "8":    {"RF": (26.00, 660),"BW": (26.00, 660),"RTJ": (26.13, 664)},
        "10":   {"RF": (31.00, 787),"BW": (31.00, 787),"RTJ": (31.13, 791)},
        "12":   {"RF": (33.00, 838),"BW": (33.00, 838),"RTJ": (33.13, 841)},
        "16":   {"RF": (39.00, 991),"BW": (39.00, 991),"RTJ": (39.13, 994)},
        "20":   {"RF": (47.00, 1194),"BW": (47.00, 1194),"RTJ": (47.25, 1200)},
        "24":   {"RF": (55.00, 1397),"BW": (55.00, 1397),"RTJ": (55.38, 1407)},
    },
    900: {
        "2":    {"RF": (14.50, 368),"BW": (14.50, 368),"RTJ": (14.63, 371)},
        "3":    {"RF": (15.00, 381),"BW": (15.00, 381),"RTJ": (15.13, 384)},
        "4":    {"RF": (18.00, 457),"BW": (18.00, 457),"RTJ": (18.13, 460)},
        "6":    {"RF": (24.00, 610),"BW": (24.00, 610),"RTJ": (24.13, 613)},
        "8":    {"RF": (29.00, 737),"BW": (29.00, 737),"RTJ": (29.13, 740)},
        "10":   {"RF": (33.00, 838),"BW": (33.00, 838),"RTJ": (33.13, 841)},
        "12":   {"RF": (38.00, 965),"BW": (38.00, 965),"RTJ": (38.13, 968)},
        "16":   {"RF": (44.50, 1130),"BW": (44.50, 1130),"RTJ": (44.88, 1140)},
        "20":   {"RF": (52.00, 1321),"BW": (52.00, 1321),"RTJ": (52.50, 1334)},
        "24":   {"RF": (61.00, 1549),"BW": (61.00, 1549),"RTJ": (61.75, 1568)},
    },
    1500: {
        "2":    {"RF": (14.50, 368),"BW": (14.50, 368),"RTJ": (14.63, 371)},
        "3":    {"RF": (18.50, 470),"BW": (18.50, 470),"RTJ": (18.63, 473)},
        "4":    {"RF": (21.50, 546),"BW": (21.50, 546),"RTJ": (21.63, 549)},
        "6":    {"RF": (27.75, 705),"BW": (27.75, 705),"RTJ": (28.00, 711)},
        "8":    {"RF": (32.75, 832),"BW": (32.75, 832),"RTJ": (33.13, 841)},
        "10":   {"RF": (39.00, 991),"BW": (39.00, 991),"RTJ": (39.38, 1000)},
        "12":   {"RF": (44.50, 1130),"BW": (44.50, 1130),"RTJ": (45.13, 1146)},
        "16":   {"RF": (54.50, 1384),"BW": (54.50, 1384),"RTJ": (55.38, 1407)},
        "20":   {"RF": (65.50, 1664),"BW": (65.50, 1664),"RTJ": (66.38, 1686)},
        "24":   {"RF": (76.50, 1943),"BW": (76.50, 1943),"RTJ": (77.63, 1972)},
    },
    2500: {
        "2":    {"RF": (17.75, 451),"BW": (17.75, 451),"RTJ": (17.88, 454)},
        "3":    {"RF": (22.75, 578),"BW": (22.75, 578),"RTJ": (23.00, 584)},
        "4":    {"RF": (26.50, 673),"BW": (26.50, 673),"RTJ": (26.88, 683)},
        "6":    {"RF": (36.00, 914),"BW": (36.00, 914),"RTJ": (36.50, 927)},
        "8":    {"RF": (40.25, 1022),"BW": (40.25, 1022),"RTJ": (40.88, 1038)},
        "10":   {"RF": (50.00, 1270),"BW": (50.00, 1270),"RTJ": (50.88, 1292)},
        "12":   {"RF": (56.00, 1422),"BW": (56.00, 1422),"RTJ": (56.88, 1445)},
    },
}


# ── Table C.3 — Ball Valves face-to-face dimensions ────────────────────────

TABLE_C3_BALL = {
    150: {
        "2":    {"RF": (7.00, 178), "BW": (8.50, 216), "RTJ": (7.50, 191)},
        "2-1/2":{"RF": (7.50, 191), "BW": (9.50, 241), "RTJ": (8.00, 203)},
        "3":    {"RF": (8.00, 203), "BW": (11.13, 283),"RTJ": (8.50, 216)},
        "4":    {"RF": (9.00, 229), "BW": (12.00, 305),"RTJ": (9.50, 241)},
        "6":    {"RF": (15.50, 394),"BW": (18.00, 457),"RTJ": (16.00, 406)},
        "8":    {"RF": (18.00, 457),"BW": (20.50, 521),"RTJ": (18.50, 470)},
        "10":   {"RF": (21.00, 533),"BW": (22.00, 559),"RTJ": (21.50, 546)},
        "12":   {"RF": (24.00, 610),"BW": (25.00, 635),"RTJ": (24.50, 622)},
        "14":   {"RF": (27.00, 686),"BW": (30.00, 762),"RTJ": (27.50, 699)},
        "16":   {"RF": (30.00, 762),"BW": (33.00, 838),"RTJ": (30.50, 775)},
        "18":   {"RF": (34.00, 864),"BW": (36.00, 914),"RTJ": (34.50, 876)},
        "20":   {"RF": (36.00, 914),"BW": (39.00, 991),"RTJ": (36.50, 927)},
        "24":   {"RF": (42.00, 1067),"BW": (45.00, 1143),"RTJ": (42.50, 1080)},
    },
    300: {
        "2":    {"RF": (8.50, 216), "BW": (8.50, 216), "RTJ": (9.13, 232)},
        "3":    {"RF": (11.13, 283),"BW": (11.13, 283),"RTJ": (11.75, 298)},
        "4":    {"RF": (12.00, 305),"BW": (12.00, 305),"RTJ": (12.63, 321)},
        "6":    {"RF": (15.88, 403),"BW": (18.00, 457),"RTJ": (16.50, 419)},
        "8":    {"RF": (19.75, 502),"BW": (20.50, 521),"RTJ": (20.38, 518)},
        "10":   {"RF": (22.38, 568),"BW": (22.00, 559),"RTJ": (23.00, 584)},
        "12":   {"RF": (25.50, 648),"BW": (25.00, 635),"RTJ": (26.13, 664)},
        "14":   {"RF": (30.00, 762),"BW": (30.00, 762),"RTJ": (30.63, 778)},
        "16":   {"RF": (33.00, 838),"BW": (33.00, 838),"RTJ": (33.63, 854)},
        "20":   {"RF": (39.00, 991),"BW": (39.00, 991),"RTJ": (39.75, 1010)},
        "24":   {"RF": (45.00, 1143),"BW": (45.00, 1143),"RTJ": (45.88, 1165)},
    },
    600: {
        "2":    {"RF": (11.50, 292),"BW": (11.50, 292),"RTJ": (11.63, 295)},
        "3":    {"RF": (14.00, 356),"BW": (14.00, 356),"RTJ": (14.13, 359)},
        "4":    {"RF": (17.00, 432),"BW": (17.00, 432),"RTJ": (17.13, 435)},
        "6":    {"RF": (22.00, 559),"BW": (22.00, 559),"RTJ": (22.13, 562)},
        "8":    {"RF": (26.00, 660),"BW": (26.00, 660),"RTJ": (26.13, 664)},
        "10":   {"RF": (31.00, 787),"BW": (31.00, 787),"RTJ": (31.13, 791)},
        "12":   {"RF": (33.00, 838),"BW": (33.00, 838),"RTJ": (33.13, 841)},
        "16":   {"RF": (39.00, 991),"BW": (39.00, 991),"RTJ": (39.13, 994)},
        "20":   {"RF": (47.00, 1194),"BW": (47.00, 1194),"RTJ": (47.25, 1200)},
        "24":   {"RF": (55.00, 1397),"BW": (55.00, 1397),"RTJ": (55.38, 1407)},
    },
    900: {
        "2":    {"RF": (14.50, 368),"BW": (14.50, 368),"RTJ": (14.63, 371)},
        "3":    {"RF": (15.00, 381),"BW": (15.00, 381),"RTJ": (15.13, 384)},
        "4":    {"RF": (18.00, 457),"BW": (18.00, 457),"RTJ": (18.13, 460)},
        "6":    {"RF": (24.00, 610),"BW": (24.00, 610),"RTJ": (24.13, 613)},
        "8":    {"RF": (29.00, 737),"BW": (29.00, 737),"RTJ": (29.13, 740)},
        "10":   {"RF": (33.00, 838),"BW": (33.00, 838),"RTJ": (33.13, 841)},
        "12":   {"RF": (38.00, 965),"BW": (38.00, 965),"RTJ": (38.13, 968)},
        "16":   {"RF": (44.50, 1130),"BW": (44.50, 1130),"RTJ": (44.88, 1140)},
        "20":   {"RF": (52.00, 1321),"BW": (52.00, 1321),"RTJ": (52.50, 1334)},
        "24":   {"RF": (61.00, 1549),"BW": (61.00, 1549),"RTJ": (61.75, 1568)},
    },
    1500: {
        "2":    {"RF": (14.50, 368),"BW": (14.50, 368),"RTJ": (14.63, 371)},
        "3":    {"RF": (18.50, 470),"BW": (18.50, 470),"RTJ": (18.63, 473)},
        "4":    {"RF": (21.50, 546),"BW": (21.50, 546),"RTJ": (21.63, 549)},
        "6":    {"RF": (27.75, 705),"BW": (27.75, 705),"RTJ": (28.00, 711)},
        "8":    {"RF": (32.75, 832),"BW": (32.75, 832),"RTJ": (33.13, 841)},
        "10":   {"RF": (39.00, 991),"BW": (39.00, 991),"RTJ": (39.38, 1000)},
        "12":   {"RF": (44.50, 1130),"BW": (44.50, 1130),"RTJ": (45.13, 1146)},
        "16":   {"RF": (54.50, 1384),"BW": (54.50, 1384),"RTJ": (55.38, 1407)},
    },
    2500: {
        "2":    {"RF": (17.75, 451),"BW": (17.75, 451),"RTJ": (17.88, 454)},
        "3":    {"RF": (22.75, 578),"BW": (22.75, 578),"RTJ": (23.00, 584)},
        "4":    {"RF": (26.50, 673),"BW": (26.50, 673),"RTJ": (26.88, 683)},
        "6":    {"RF": (36.00, 914),"BW": (36.00, 914),"RTJ": (36.50, 927)},
        "8":    {"RF": (40.25, 1022),"BW": (40.25, 1022),"RTJ": (40.88, 1038)},
        "10":   {"RF": (50.00, 1270),"BW": (50.00, 1270),"RTJ": (50.88, 1292)},
        "12":   {"RF": (56.00, 1422),"BW": (56.00, 1422),"RTJ": (56.88, 1445)},
    },
}


_FACE_END_TO_KEY = {"R": "RF", "RF": "RF", "J": "RTJ", "RTJ": "RTJ", "BW": "BW", "W": "BW"}
_TABLE_BY_VALVE_TYPE = {
    "GA": ("C.1", 59, 73, TABLE_C1_GATE),
    "GL": ("C.1", 59, 73, TABLE_C1_GATE),  # Globe valves use Table C.1 (same convention as gate per API 6D §5.4)
    "BL": ("C.3", 69, 83, TABLE_C3_BALL),
    "BS": ("C.3", 69, 83, TABLE_C3_BALL),
}


def lookup_face_to_face(valve_type: str, nps: str, pressure_class: int, end_face: str) -> tuple[str, str] | None:
    """Returns ('15.50 in. (394 mm)', citation) or None if outside the table."""
    key = _FACE_END_TO_KEY.get(end_face.upper())
    if not key:
        return None
    spec = _TABLE_BY_VALVE_TYPE.get(valve_type)
    if not spec:
        return None
    table_label, printed_p, pdf_p, table = spec
    cls = table.get(pressure_class)
    if not cls:
        return None
    row = cls.get(str(nps))
    if not row:
        return None
    cell = row.get(key)
    if not cell:
        return None
    inch, mm = cell
    return (f"{inch:.2f} in. ({mm} mm)", cite(table_label, printed_p, pdf_p))
