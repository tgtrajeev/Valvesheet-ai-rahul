# Issue / Fix Log

Use this file to capture every issue we fix (or decide to fix later), so a daily manager report can be generated at 6:00 PM.

## How to add a new entry

Copy/paste this template and fill it in:

```text
### YYYY-MM-DD — <short title>
- Area: app / backend / agent / PMS sync / validation / datasheet / other
- Problem: <what was broken / confusing>
- Impact: <who was affected / what user saw>
- Root cause: <why it happened>
- Fix: <what we changed>
- Files touched:
  - <path>
  - <path>
- Verification: <how we proved it’s fixed>
```

---

## 2026-05-11 — BS-prefixed ball VDS must not generate

- Area: validation + agent tool flow
- Problem: `BSFPF25J` could still be treated as valid and could generate a datasheet.
- Impact: Chat UI showed a filled datasheet even when the VDS prefix policy required `BL…`.
- Root cause:
  - Decoder mapped the `BS` prefix to engine type `BL`, so `validate_combination(vt == "BS")` never triggered.
  - Index-hit path demoted Phase-1 errors to warnings.
- Fix:
  - Added raw-VDS retired-prefix detection (`BS` + bore + seat) and enforced it as a Phase-1 error using the *raw* VDS string.
  - Passed `vds_code` through validation calls and kept this specific policy error fatal even for index hits.
  - Blocked/stripped datasheet payload when validation errors exist.
  - API datasheet endpoints reject `BS…` ball codes with HTTP 400.
- Files touched:
  - `app/engine/validator.py`
  - `app/agent/tools.py`
  - `app/agent/orchestrator.py`
  - `app/routes/datasheets.py`
  - `app/routes/validate.py`
  - `app/models/schemas.py`
  - `backend/app/engine/validator.py`
  - `backend/app/agent/tools.py`
  - `backend/app/agent/orchestrator.py`
  - `backend/app/routes/datasheets.py`
  - `backend/app/routes/validate.py`
  - `backend/app/models/schemas.py`
- Verification:
  - `app.agent.tools._handle_generate({'vds_code': 'BSFPF25J'})` returns `blocked=True`, `draft=True`, and empty `data`.
  - `GET /datasheets/BSFPF25J` returns 400 with “BS prefix not permitted”.

## 2026-05-11 — Backend BF datasheet prune matches app (no stem_material row)

- Area: backend / datasheet
- Problem: `backend/app/engine/datasheet_prune.py` still allowed `stem_material` for butterfly (`BF`) via `_stem_trim_pack_lever`, while the app copy used gland/packing/lever only and `rule_engine` maps PMS `stem_material` → `shaft_material` and drops `stem_material`.
- Impact: Backend-generated BF datasheets could still expose a duplicate stem trim row or diverge from the FastAPI app output.
- Root cause: Backend prune helper was not updated when BF trim semantics were changed to a single shaft row.
- Fix: Introduced `_gland_pack_lever` in the backend prune module and switched the BF allowed-key set to use it (mirror of `app/engine/datasheet_prune.py`).
- Files touched:
  - `backend/app/engine/datasheet_prune.py`
- Verification: BF allowlist contains `shaft_material` + `_gland_pack_lever` keys only; `stem_material` is not in the BF frozen set (grep / code review).

## 2026-05-11 — Remove stale VDS index value fallback

- Area: app / backend / agent / datasheet
- Problem: Known VDS codes could still return field values from cached `all_valve_vds_index.json` snapshots when live rule generation failed, and some backend paths used `spec.data` directly.
- Impact: Old hard-coded-looking values such as `Forged - ASTM B124 UNS NO C 37700` could appear in datasheets even when the current PMS/rule path should resolve a different material.
- Root cause: The VDS index was being used both as a validity registry and as a value fallback; stale snapshot rows survived after PMS/rule corrections.
- Fix:
  - Treat the VDS index as registration/validity only.
  - Regenerate datasheet values from the rule engine and current PMS for app/backend agent and API paths.
  - Return a clear error instead of falling back to `spec.data` when regeneration fails.
  - Updated compare output to use live regenerated values and report `regeneration_failed` separately from missing codes.
- Files touched:
  - `app/agent/tools.py`
  - `app/routes/datasheets.py`
  - `backend/app/agent/tools.py`
  - `backend/app/routes/datasheets.py`
- Verification:
  - `python -m py_compile app/agent/tools.py app/routes/datasheets.py backend/app/agent/tools.py backend/app/routes/datasheets.py`
  - Grep confirms no datasheet generation path still reads `spec.data`; remaining `spec.data` references were removed from compare value output.

## 2026-05-11 — PMS-driven material category for A40 copper classes

- Area: app / backend / PMS sync / datasheet
- Problem: `BLRTA40F` and other `A40` VDS codes still showed `NAB UNS C95800` for material-section fields such as ball, stem, and gland.
- Impact: Copper-class valve datasheets could show GRE/NAB trim material values even though the project PMS class header says `A40` is `Copper`.
- Root cause:
  - `_get_material_category()` used legacy numeric mappings (`40 -> GRE`) before consulting the project PMS material description.
  - `generate_datasheet()` in the app calculated material category before refreshing the PMS row, so current project data could not override the stale category map.
- Fix:
  - Added PMS-header material-description resolution before the legacy numeric fallback.
  - Mapped descriptions such as `Copper`, `GRE`, `CPVC`, `Cu-Ni`, duplex, SDSS, SS316L, galvanized, LTCS, and CS into material categories.
  - Moved app material-category resolution after PMS refresh; added the same PMS-refresh/category behavior to backend.
- Files touched:
  - `app/engine/rule_engine.py`
  - `backend/app/engine/rule_engine.py`
- Verification:
  - `python -m py_compile app/engine/rule_engine.py backend/app/engine/rule_engine.py`
  - Asserted app/backend `_get_material_category("A40") == "COPPER"`.
  - Asserted `BLRTA40F` no longer returns `NAB UNS C95800` for `ball_material`, `stem_material`, or `gland_material`.
  - Asserted the `A40` VDS family (`BLRTA40F`, `BLFTA40F`, `GAYMA40F`, `GLYMA40F`, `CHPMA40F`, `CHSMA40F`, `CHDMA40F`, `BFWTA40F`) no longer emits `NAB UNS C95800` in ball/stem/gland/shaft material fields.

## 2026-05-11 — Remove PMS_PDF references and Others card section

- Area: app / backend / agent / datasheet card
- Problem: Datasheet card payloads could include `field_pms_pdf_sources` / `field_pms_pdf_links`, and unmapped datasheet keys were rendered by the UI under an `Others` section.
- Impact: The card showed PMS_PDF verification references/links in the source-derived area and displayed a whole extra section with internal or non-card fields.
- Root cause:
  - PMS_PDF verification maps were still being attached to app datasheet responses even though card sources should only cite rule/PMS/VMS provenance used to generate the value.
  - API/agent payloads returned every generated field, including keys not configured in `field_mappings.yaml`; the card grouped those leftovers as `Others`.
- Fix:
  - Added app/backend `card_filter` helpers that keep only fields explicitly configured in non-Other `field_mappings.yaml` sections.
  - Filtered card data and all per-field metadata (`field_sources`, links, quotes, source-derived values, justifications) before returning app/backend agent and datasheet API responses.
  - Removed PMS_PDF verification source/link fields from app datasheet and agent responses.
- Files touched:
  - `app/engine/card_filter.py`
  - `backend/app/engine/card_filter.py`
  - `app/agent/tools.py`
  - `backend/app/agent/tools.py`
  - `app/routes/datasheets.py`
  - `backend/app/routes/datasheets.py`
- Verification:
  - `python -m py_compile app/engine/card_filter.py backend/app/engine/card_filter.py app/routes/datasheets.py backend/app/routes/datasheets.py app/agent/tools.py backend/app/agent/tools.py`
  - Asserted `BLRTA40F` app/backend agent responses contain no keys outside configured card fields.
  - Asserted `BLRTA40F` app datasheet route response contains no keys outside configured card fields.
  - Asserted generated card responses contain no `PMS_PDF`, `field_pms_pdf_sources`, or `field_pms_pdf_links`.

## 2026-05-11 — Dev PMS JSON sync route and VDS normalization

- Area: app / backend / PMS sync / datasheet
- Problem: The Dev/Test PMS JSON panel is meant to prove that changed PMS data affects generated valvesheets, but the direct `/api/pms` compatibility routes were missing in the current app/backend route files, and comma-separated VDS strings inside `vds_codes` were not normalized everywhere.
- Impact: New/edited PMS classes could be hard to verify end-to-end, and VDS index entries could be built as one combined string such as `BLRPF2LNJ, BLFPF2LNJ` instead of two usable VDS codes.
- Root cause:
  - Only project-scoped PMS routes existed (`/api/pms/projects/...`), while the dev/test UI and test script target `/api/pms`, `/api/pms/classes`, and `/api/pms?spec_code=...`.
  - VDS assignment handling assumed `vds_codes` was already split into individual strings.
  - Datasheet `size_range` intentionally resolves from the matching `valve_assignments` row before `pipe_schedule`; changing only `pipe_schedule` to add NPS 26 will not expand a VDS whose assignment still has `nps_max: 24`.
- Fix:
  - Added app/backend direct Dev/Test routes:
    - `POST /api/pms` to upsert PMS JSON keyed by valid piping class code.
    - `GET /api/pms/classes` to list synced classes.
    - `GET /api/pms?spec_code=...` to inspect the saved full PMS class JSON.
  - Rebuild project VDS index, warm PMS cache, and refresh PMS loader after direct JSON sync.
  - Normalize comma-separated VDS values when building VDS index and when matching assignments in rule generation.
  - Added `range_diagnostics` to the sync response so pipe schedule max and valve-assignment ranges can be compared immediately.
- Files touched:
  - `app/routes/pms.py`
  - `backend/app/routes/pms.py`
  - `app/pms/vds_builder.py`
  - `backend/app/pms/vds_builder.py`
  - `app/engine/rule_engine.py`
  - `backend/app/engine/rule_engine.py`
- Verification:
  - `python -m py_compile app/routes/pms.py backend/app/routes/pms.py app/pms/vds_builder.py backend/app/pms/vds_builder.py app/engine/rule_engine.py backend/app/engine/rule_engine.py`
  - Asserted comma-separated `vds_codes` normalize to separate VDS index entries.
  - Asserted range diagnostics show `pipe_schedule_max: 26` while the `DBB_INST` valve assignment remains `nps_max: 24`, explaining why `DBRPF2LNJT` still shows `1" - 24"` unless the assignment range is also changed.

