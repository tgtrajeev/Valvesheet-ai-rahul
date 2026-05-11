# PMS Sheet → VDS Datasheet Field Mapping & Test Matrix

**Purpose**: When a new PMS sheet is uploaded, this document tells you exactly which cells in the downloaded VDS Excel datasheet will change, and the rule / standard / calculation that produced each value. Use it as a verification checklist during real testing.

**Last updated**: 2026-05-10

---

## 1. End-to-End Data Flow

**Demo / client question**: “If we generate a **new** PMS in **your** PMS Generator and sync it, do the same datasheet rules still apply?” **Yes.** The backend stores the full JSON (header, P–T, pipe, flanges, bolting, **`valve_assignments`** when provided). On the first chatbot request that needs that class, `build_and_register` refreshes the spec from `GET /api/pms`, builds the VDS index from **`valve_assignments` in the payload** when that list is non-empty, and only **falls back** to header-derived assignments when the sync omitted valve rows (legacy Excel or old clients).

```
┌──────────────────┐
│ New PMS          │  In-app PMS Generator **or** client Excel
│ (Pipe Class)     │  → “Sync to Valvesheet” → POST /api/pms
└────────┬─────────┘     (includes valve_assignments from AI tables when synced from UI)
         │ POST /api/pms  (port 8000 backend)
         ▼
┌────────────────────────────────────────┐
│ SPE-Valvesheet-Backend-Staging         │
│  • parse_pms_excel.py → DB tables      │
│  • pms_extracted.json (full payload)   │
│  • Endpoints:                          │
│      GET /api/pms/classes              │
│      GET /api/pms?spec_code=X          │
└────────┬───────────────────────────────┘
         │ on first chatbot request for a new class
         ▼
┌────────────────────────────────────────┐
│ Valvesheet-ai-rahul (chatbot)          │
│  • refresh_spec_from_backend(X)        │
│    (full document; avoids stale empty  │
│     valve rows from class-list preload)│
│  • build_and_register(X)               │
│      → valve_assignments from API if   │
│        present; else derive from header  │
│      → generate_datasheet per VDS code │
│  • generate_datasheet:                 │
│      _resolve_from_pms(spec)           │
│         → flat dict of PMS-driven      │
│         + rule-derived values          │
└────────┬───────────────────────────────┘
         │ HTTP JSON response
         ▼
┌────────────────────────────────────────┐
│ SPE-Valvesheet-Frontend-Staging        │
│  • DatasheetCard renders UI preview    │
│  • excelBuilder.ts → buildDatasheet... │
│      • FIELD_NAMES (display labels)    │
│      • BASIC_FIELDS, CONSTRUCTION_KEYS,│
│        MATERIAL_KEYS, STANDALONE_KEYS  │
│      • *_note / *_notes → Notes section│
│      • Field-source citations linked   │
│  • ExcelJS → .xlsx blob → browser DL   │
└────────────────────────────────────────┘
```

**No template Excel exists** — the Excel is built from scratch row-by-row from the JSON. So a "field that's not in the existing template" is not a problem; the question is whether the field key is registered in `excelBuilder.ts`'s field lists. If yes, it gets a row; if no, it's silently dropped.

---

## 2. PMS Field Coverage in the Datasheet

### Direct passthrough fields (PMS string copied verbatim)

| PMS field | Datasheet cell | Verification |
|---|---|---|
| `header.service` | "Service" | string equality |
| `header.corrosion_allowance` | "Corrosion Allowance" | string equality (with NIL/NONE/- → "0 mm" normalization) |
| `header.design_code` | "Design Code" | string equality (e.g. "ASME B 31.3, NACE-MR-01-75/ISO-15156-1/2/3") |
| `header.material_description` | "Material Class" | string equality |
| `header.valve_rating_label` | "Pressure Class" | string equality (e.g. "300#, RF") |
| `bolting_gaskets.stud_bolt_spec` | "Bolts" | string equality |
| `bolting_gaskets.hex_nut_spec` | "Nuts" | string equality |
| `bolting_gaskets.gasket_spec` | "Gaskets" | string equality |
| `flanges[].flange_face` | embedded in "End Connections" | substring match |
| `flanges[].flange_type` | embedded in "End Connections" | substring match |
| `flanges[].flange_moc` | "Flange Material" | string equality |

### Calculated / derived fields

| PMS field | Datasheet cell | Calculation |
|---|---|---|
| `index_row.design_pressure_barg` + `min_temp_c` + `pt_breakpoints[-1]` | "Design Pressure" | formatted: `"{DP} @ {min_T}°C, {DP_max} @ {max_T}°C"` |
| `index_row.hydrotest_barg` (or `header.hydrotest_pressure_barg`) | "Hydrotest Shell" | `round(ht_barg, 2)` barg — verifies API SPEC 6D §9.3 (1.5× rating) |
| same | "Hydrotest Closure" | `round(shell / 1.5 × 1.1, 2)` barg — API SPEC 6D §9.4.2 (1.1× rating) |
| `index_row.min_temp_c` | "Min Design Temp" | `f"{int(min_temp_c)}°C"` |
| `nps_sizes[]` | "Size Range" | `f'{min(nps)}" - {max(nps)}"'` |
| `flanges[].nps_min/max` (split-NPS specs) | flange selection | size_inches falls within `[nps_min, nps_max]` of one of the segments |

### Cascade-driven fields (one PMS flag flips many cells)

| PMS flag | Cells affected | Logic source |
|---|---|---|
| `header.nace_flag = true` | "Sour Service" → "NACE MR0175 / ISO 15156 compliant" | `rule_engine.py` — sour_service block |
| | "Bolts" → A193 B7**M** (was B7) | `BOLT_MATERIAL["CS_NACE"]` |
| | "Nuts" → A194 2H**M** (was 2H) | `NUT_MATERIAL["CS_NACE"]` |
| | "Gaskets" (RTJ) → "OCT ring of Soft Iron, Max. Hardness 90 BHN" | `GASKET_MATERIAL[("CS_NACE", True)]` |
| | "Gland Material" → A350 LF2 (LTCS) or A182 F316L (SS) | NACE MR0175 §6.1 hardness limits |
| | "Body Material" → may add NACE-compatible grade | category re-derivation |
| | adds note "Hardness Requirement: max 22 HRC" | NACE MR0175 §6.1 |
| | adds "Fugitive Emissions Test: ISO 15848-1 BH" | rule_engine post-processing |
| `header.lt_flag = true` | "Low Temperature" → "Yes - Impact tested" | rule_engine |
| | "Min Design Temp" → -45°C (LTCS) or -46°C (DSS/SDSS) | rule_engine default; PMS override available |
| | "Bolts" → ASTM A 320 Gr. **L7M** (was B7M) | ASTM A320 — covers low-temp bolting |
| | "Body" → A350 LF2 (≤1.5") + A352 LCC (≥2") | ASME B31.3 §323.2.2 + LTCS material map |
| | adds "Impact Test: Charpy V-notch per ASME B31.3 / B16.34" | rule_engine NACE block |
| `header.material_description` change (e.g. "CS" → "316L") | "Body", "Ball", "Stem", "Gland", "Seat" all → SS316L grades | `_get_material_category` + `BODY_MATERIAL["SS316L"]` etc. |
| | "Bolts" → A320 Gr. L7M | per material map |
| | "Gaskets" (RF) → SS316/SS316L spiral wound | per material map |
| | "PMI Required: Positive Material Identification" added | rule_engine SS-only block |
| | "Chloride Restriction: 300-series SS not where Cl >5 ppm AND T >60°C" | MY-K-20-PI-SP-0002 §7.2 |
| `header.pressure_rating` change (e.g. "150#" → "600#") | **VDS code itself changes**: BLF**T**…**R** → BLF**P**…**J** | seat: 150/300→T(PTFE), 600+→P(PEEK), 2500→both P+M; end conn: 600≤→R(RF), 900+→J(RTJ) |
| | "Pressure Class" → "ASME B16.34 Class 600" | PRESSURE_CLASS lookup |
| | "Operation" — gear threshold lowers | `_GEARBOX[vt][pc_num]` lookup |
| | "Ball Construction" — floating/trunnion threshold tightens | `_BALL_MOUNTING[pc_num]` |
| | DBB fields appear (only ≥900#) | `has_dbb = pressure_num ≥ 900` |
| | NDT extent → 100% (CL ≥600) | `_NDT_EXTENT` |
| `header.service` mentions "Methanol" or "Glycol" | adds "Seal Material Note: FFKM recommended per MY-K-20-PI-SP-0002 §7.8" | string match `rule_engine.py:1186-1188` |

---

## 3. Verification Test Procedure

### Test setup

1. Pick a known-good spec from `app/data/pms_extracted.json` (e.g. `B1N`).
2. Clone its JSON, change the spec_code to `SYNCDEMO1` (uppercase letters/digits only — no underscores).
3. Mutate the seven PMS fields below to verify each chain.
4. POST to `http://localhost:8000/api/pms` with `{ "SYNCDEMO1": <cloned_obj> }`.
5. In the chatbot, ask: *"generate a 4-inch ball valve datasheet for SYNCDEMO1"*.
6. Download the Excel and verify the 19 cells listed in §4.

### Test mutations

| # | Field | Old value | New value |
|---|---|---|---|
| M1 | `header.pressure_rating` | "300#" | "600#" |
| M2 | `header.valve_rating_label` | "300#, RF" | "600#, RTJ" |
| M3 | `header.corrosion_allowance` | "3 mm" | "6 mm" |
| M4 | `header.design_code` | "ASME B 31.3, NACE-MR-01-75/ISO-15156-1/2/3" | "ASME B 31.4 (Pipeline)" |
| M5 | `header.design_pressure_barg` | 51.1 | 99.3 |
| M6 | `header.hydrotest_pressure_barg` | 76.65 | 148.95 |
| M7 | `header.service` | "Glycol, FG, Hydro Carbon service" | "Crude Oil Export" |
| M8 | `header.material_description` | "CS NACE" | "SDSS" |
| M9 | `header.nace_flag` | true | true (kept) |
| M10 | `header.lt_flag` | false | true |
| M11 | `flanges[0].flange_face` | "300# RF, Serrated Finish" | "600# RTJ" |
| M12 | `flanges[0].flange_moc` | "ASTM A 105N" | "ASTM A 182 Gr. F53 (SDSS)" |
| M13 | `flanges[0].flange_type` | "Weld Neck, ASME B 16.5, …" | "Weld Neck, ASME B 16.5, RTJ groove per B16.20" |
| M14 | `index_row.min_temp_c` | -29 | -46 |
| M15 | `index_row.hydrotest_barg` | 76.65 | 148.95 |
| M16 | `index_row.design_pressure_barg` | 51.1 | 99.3 |

---

## 4. Expected Excel Cell Values

After running the test mutations and downloading the datasheet for `BLFP SYNCDEMO1J` at 4 inches:

| Cell label | Expected value | From which mutation | Verified by |
|---|---|---|---|
| Piping Class | `SYNCDEMO1` | spec_code | direct |
| Material Class | `SDSS` | M8 | passthrough |
| Pressure Class | `600#, RTJ` | M2 | passthrough (`valve_rating_label`) |
| Design Pressure | `99.3 @ -46°C, …` | M5 + M14 (+ pt_breakpoints last row) | format string |
| Min Design Temp | `-46°C` | M14 | `f"{int(min_temp_c)}°C"` |
| Design Code | `ASME B 31.4 (Pipeline)` | M4 | passthrough |
| Corrosion Allowance | `6 mm` | M3 | passthrough |
| Sour Service | `NACE MR0175 / ISO 15156 compliant` | M9 | NACE flag → string |
| Low Temperature | `Yes - Impact tested` | M10 | LT flag → string |
| Service | `Crude Oil Export` | M7 | passthrough |
| End Connections | `Flanged (600# RTJ) - Weld Neck, ASME B 16.5, RTJ groove per B16.20` | M11 + M13 | concat |
| Flange Material | `ASTM A 182 Gr. F53 (SDSS)` | M12 | passthrough |
| Hydrotest Shell | `148.95 barg` | M6 / M15 | `round(ht, 2)` |
| Hydrotest Closure | `109.23 barg` | derived from M15 | `round(148.95/1.5 × 1.1, 2)` per API 6D §9.4.2 |
| Body Material | `SDSS - UNS S32750, Forged - ASTM A182 F53 (1.5" and below), Cast - ASTM A995 5A UNS J93404 (2" and above)` | M8 | `BODY_MATERIAL["SDSS"]` |
| Ball Material | `Forged - ASTM A182 F53` | M8 | `BALL_MATERIAL["SDSS"]` |
| Stem Material | `Forged - ASTM A182 F53` | M8 | `STEM_MATERIAL["SDSS"]` |
| Bolts | `ASTM A 453 Gr. 660` | M8 | `BOLT_MATERIAL["SDSS"]` (SDSS uses A453 660 instead of A320 L7M) |
| Nuts | `ASTM A 453 Gr. 660` | M8 | `NUT_MATERIAL["SDSS"]` |
| Gaskets | `ASME B 16.20, OCT ring of UNS S 32750 with Max. Hardness of 22 HRC` | M11 (RTJ) + M8 (SDSS) | `GASKET_MATERIAL[("SDSS", True)]` |
| Operation | `Gear operated c/w Handwheel (4" >= 4" threshold), …` | size + M1 | `_GEARBOX["BL"][600]` = 4 |
| Ball Construction | `Trunnion Mounted (4")` (or "Floating Ball") | size + M1 | `_BALL_MOUNTING[600]` thresholds (max_floating=1.5, min_trunnion=2) |
| Pressure Test Standard | `Designed and tested per API 6D (CL 600) and applicable valve type codes` | M1 | `pc_num > 150` branch |
| NDT Extent | `100% RT per ASME B16.34 Annexure B` | M1 | `_NDT_EXTENT[600]` = 100% always |
| Impact Test | `Charpy V-notch impact test per ASME B31.3 / ASME B16.34` | M10 | LT flag block |

---

## 5. Quick Sanity Checks

If a test fails, use this checklist:

1. **PMS not registered**: hit `GET http://localhost:8000/api/pms?spec_code=SYNCDEMO1` — does it return 200 with the full payload? If 404, the POST didn't land.
2. **Local cache stale**: chatbot caches `PmsLoader._specs`. Force `refresh_pms_loader()` or restart the chatbot.
3. **VDS code regex rejection**: spec codes are validated by `^[A-Z][A-Z0-9]{0,19}$`. No underscores, hyphens, or lowercase. Bad code → "Invalid piping class" 422.
4. **Material category mis-derivation**: for non-standard codes (e.g. `SYNCDEMO1` doesn't start with A1/B10), `_material_category()` parses `header.material_description` text. Make sure the description contains a recognizable token: "316L", "duplex", "super duplex / SDSS / S32750", "galv", "cuni", "GRE", "CPVC", or it falls back to CS.
5. **Field missing from Excel**: check `excelBuilder.ts:82-107` — if the key isn't in `BASIC_FIELDS`, `CONSTRUCTION_KEYS`, `MATERIAL_KEYS`, `STANDALONE_KEYS`, or doesn't end in `_note` / `_notes`, it gets silently dropped.
6. **Bolt/nut spec dropped**: confirm `bolting_gaskets` is present in the POSTed JSON — backend's `parse_pms_excel.py` only writes if the Excel had the bolting section.

---

## 6. Standards / Specs Referenced

- **ASME B16.34** — Valves, flanges, P-T tables, material groups (§6.1)
- **ASME B16.5** — Flanges ≤24" (§6.22.1)
- **ASME B16.47 Series A** — Flanges ≥26"
- **ASME B16.20** — Gaskets for ring-joint and spiral-wound
- **ASME B31.3** — Process piping; impact testing §323.2.2
- **API SPEC 6D** — Pipeline valves; hydrotest §9.3 (shell 1.5×) / §9.4.2 (seat 1.1×)
- **API 600 / 602 / 603** — Gate valves
- **API 609** — Butterfly valves
- **API 594** — Check valves
- **API 6FA / API 607 / ISO 10497** — Fire testing
- **NACE MR0175 / ISO 15156** — Sour service materials hardness
- **ASTM A193 / A194 / A320 / A453** — Bolting materials
- **MY-K-20-PI-SP-0002** — Project-specific Valve Material Specification (gear thresholds, NDT extent, extended stem, max torque, etc.)
