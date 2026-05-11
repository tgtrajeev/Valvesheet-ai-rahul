"""
PMS Sync Verification Test
==========================
Tests that a brand-new PMS class POSTed to the backend is immediately usable
by the Valvesheet chatbot -- with the EXACT same values (design pressure, bolts,
gaskets, service) flowing through to the generated datasheet.

Run:
    python test_pms_sync.py

Expected output: all checks PASS.  Show this report to the client.
"""

import json
import time
import sys
import httpx

# Force UTF-8 output on Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BACKEND  = "http://localhost:8000"   # SPE-Valvesheet-Backend-Staging
CHATBOT  = "http://localhost:8002"   # Valvesheet-ai-rahul

# Unique test spec code (timestamp keeps runs independent)
#
# IMPORTANT: the backend ingest validates that spec_code looks like a real
# piping class (A1, B1N, G1LN, T50A, ...). Demo/free-form ids like DEMO47823
# are rejected by design, so we generate a T-series code here.
TS       = int(time.time()) % 100000          # 5-digit suffix
SPEC     = f"T{TS}A"                          # e.g. T47823A
SESSION  = f"sync-test-{TS}"

# Test PMS payload -- values are intentionally unusual so we know they came
# from THIS PMS and not from any hardcoded fallback
DESIGN_PRESSURE_BARG  = 47.3          # unusual number (not 19.6 / 51.1 / 102.1)
HYDROTEST_BARG        = 70.95         # 47.3 x 1.5 = 70.95
BOLTING               = "ASTM A193 B7M / Demo Project"
NUTS                  = "ASTM A194 2HM / Demo Project"
GASKET                = f"Spiral Wound SS316L + Graphite, Demo Spec {TS}"
SERVICE               = f"Sour Gas -- Demo Project {TS}"

TEST_PMS = {
    SPEC: {
        "header": {
            "pressure_rating":       "300#",
            "material_description":  "Carbon Steel A106 Gr B",
            "corrosion_allowance":   "3 mm",
            "design_code":           "ASME B31.3",
            "service":               SERVICE,
            "nace_flag":             False,
            "lt_flag":               False,
            "design_pressure_barg":  DESIGN_PRESSURE_BARG,
            "hydrotest_pressure_barg": HYDROTEST_BARG,
        },
        "pt_ratings": [
            {"temperature_c": -29,  "max_pressure_barg": DESIGN_PRESSURE_BARG},
            {"temperature_c":  50,  "max_pressure_barg": DESIGN_PRESSURE_BARG},
            {"temperature_c": 100,  "max_pressure_barg": DESIGN_PRESSURE_BARG},
            {"temperature_c": 200,  "max_pressure_barg": 43.1},
            {"temperature_c": 300,  "max_pressure_barg": 39.4},
        ],
        "flanges": [
            {
                "size_range": "ALL",
                "nps_min": 0.5,
                "nps_max": 24.0,
                "flange_moc":  "ASTM A105",
                "flange_face": "RF",
                "flange_type": "WN/SO",
            }
        ],
        "bolting_gaskets": {
            "stud_bolt_spec": BOLTING,
            "hex_nut_spec":   NUTS,
            "gasket_spec":    GASKET,
        },
        "pipe_schedule": [
            {"nps_inch": 0.5,  "schedule_val": "SCH 80"},
            {"nps_inch": 1.0,  "schedule_val": "SCH 80"},
            {"nps_inch": 2.0,  "schedule_val": "SCH 40"},
            {"nps_inch": 4.0,  "schedule_val": "STD"},
            {"nps_inch": 6.0,  "schedule_val": "STD"},
        ],
    }
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SEP  = "=" * 62
DASH = "-" * 62

_results: list[tuple[str, bool]] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = "[PASS]" if condition else "[FAIL]"
    print(f"  {status}  {label}")
    if detail:
        print(f"         {detail}")
    _results.append((label, condition))
    return condition


def section(title: str) -> None:
    print(f"\n{DASH}")
    print(f"  {title}")
    print(DASH)


# ---------------------------------------------------------------------------
# STEP 0 -- Services reachable
# ---------------------------------------------------------------------------

section("STEP 0 -- Services reachable")

try:
    r = httpx.get(f"{BACKEND}/api/pms/classes", timeout=5)
    check("Backend reachable", r.status_code == 200, f"{BACKEND}/api/pms/classes -> {r.status_code}")
except Exception as e:
    check("Backend reachable", False, str(e))
    print("\n[ERROR] Cannot reach backend. Start it: cd SPE-Valvesheet-Backend-Staging && python run_api.py")
    sys.exit(1)

try:
    r = httpx.get(f"{CHATBOT}/health", timeout=5)
    check("Chatbot reachable", r.status_code == 200, f"{CHATBOT}/health -> {r.status_code}")
except Exception as e:
    check("Chatbot reachable", False, str(e))
    print("\n[ERROR] Cannot reach chatbot. Start it: cd Valvesheet-ai-rahul && python run.py")
    sys.exit(1)

print(f"\n  Spec code for this run  : {SPEC}")
print(f"  Design pressure (barg)  : {DESIGN_PRESSURE_BARG}  <-- unusual value proves data came from PMS")
print(f"  Hydrotest (barg)        : {HYDROTEST_BARG}")
print(f"  Bolting                 : {BOLTING}")
print(f"  Gasket                  : {GASKET}")

# ---------------------------------------------------------------------------
# STEP 1 -- POST new PMS to backend
# ---------------------------------------------------------------------------

section("STEP 1 -- Sync new PMS class to backend")

try:
    r = httpx.post(f"{BACKEND}/api/pms", json=TEST_PMS, timeout=15)
    body = r.json()
    check("POST /api/pms accepted (200)", r.status_code == 200, f"HTTP {r.status_code}")
    check(
        "Backend confirmed file write",
        body.get("sheets_total", 0) >= 1,
        f"sheets_total={body.get('sheets_total')}",
    )
    db_failed = body.get("db_failed", [])
    check(
        "Backend DB write succeeded",
        len(db_failed) == 0,
        f"db_failed={db_failed}" if db_failed else "db_failed=[]",
    )
except Exception as e:
    check("POST /api/pms accepted (200)", False, str(e))
    sys.exit(1)

# ---------------------------------------------------------------------------
# STEP 2 -- Backend immediately lists the new spec
# ---------------------------------------------------------------------------

section("STEP 2 -- Backend lists the new class immediately (no restart needed)")

r = httpx.get(f"{BACKEND}/api/pms/classes", timeout=10)
classes = {c["spec_code"]: c for c in r.json().get("classes", [])}
check(
    f"GET /api/pms/classes contains {SPEC}",
    SPEC in classes,
    f"Total classes in DB: {len(classes)}",
)
if SPEC in classes:
    cls = classes[SPEC]
    check(
        "Pressure rating stored correctly",
        cls.get("pressure_rating") == "300#",
        f"stored='{cls.get('pressure_rating')}'",
    )
    check(
        "Design pressure stored correctly",
        abs(float(cls.get("design_pressure_barg") or 0) - DESIGN_PRESSURE_BARG) < 0.1,
        f"stored={cls.get('design_pressure_barg')}  expected={DESIGN_PRESSURE_BARG}",
    )

r2 = httpx.get(f"{BACKEND}/api/pms", params={"spec_code": SPEC}, timeout=10)
check(
    f"GET /api/pms?spec_code={SPEC} returns full JSON",
    r2.status_code == 200,
    f"HTTP {r2.status_code}",
)
if r2.status_code == 200:
    sheet = r2.json().get("data", {})
    stored_bolt = sheet.get("bolting_gaskets", {}).get("stud_bolt_spec", "")
    check(
        "Bolting spec stored verbatim",
        stored_bolt == BOLTING,
        f"stored='{stored_bolt}'",
    )
    stored_gasket = sheet.get("bolting_gaskets", {}).get("gasket_spec", "")
    check(
        "Gasket spec stored verbatim",
        stored_gasket == GASKET,
        f"stored='{stored_gasket}'",
    )

# ---------------------------------------------------------------------------
# STEP 3 -- Chatbot generates datasheet using the new class
# ---------------------------------------------------------------------------

section(f"STEP 3 -- Chatbot generates datasheet for {SPEC} (no restart needed)")

VDS_EXPECTED = f"BLFT{SPEC}R"      # Ball Valve + Full Bore + PTFE + SPEC + RF
print(f"  Expected VDS code: {VDS_EXPECTED}")

message = (
    f"Generate a ball valve datasheet for piping class {SPEC}, "
    f"full bore, PTFE seat."
)

chat_text = ""

try:
    with httpx.stream(
        "POST",
        f"{CHATBOT}/api/chat",
        json={"messages": [{"role": "user", "content": message}], "session_id": SESSION},
        timeout=120,
    ) as resp:
        check("Chat request accepted (200)", resp.status_code == 200, f"HTTP {resp.status_code}")
        for chunk in resp.iter_text():
            if "event: text" in chunk:
                for line in chunk.strip().splitlines():
                    if line.startswith("data:"):
                        try:
                            chat_text += json.loads(line[5:]).get("text", "")
                        except Exception:
                            pass
except Exception as e:
    check("Chat request accepted (200)", False, str(e))
    sys.exit(1)

safe_reply = chat_text[:400].encode("ascii", "replace").decode()
print(f"\n  Agent reply (first 400 chars):")
for ln in safe_reply.splitlines():
    print(f"    {ln}")

check(
    f"Agent mentions VDS code {VDS_EXPECTED}",
    VDS_EXPECTED in chat_text.upper(),
)
check(
    f"Agent mentions piping class {SPEC}",
    SPEC in chat_text.upper(),
)

# ---------------------------------------------------------------------------
# STEP 4 -- VDS index was auto-built for this class
# ---------------------------------------------------------------------------

section("STEP 4 -- VDS index auto-built from PMS data (lazy, on first request)")

time.sleep(1)   # let any async index flush complete
INDEX_PATH = "app/data/all_valve_vds_index.json"
try:
    with open(INDEX_PATH, encoding="utf-8") as f:
        idx = json.load(f)
except FileNotFoundError:
    idx = {}

check(
    f"VDS index contains {VDS_EXPECTED}",
    VDS_EXPECTED in idx,
    f"Total index size: {len(idx)}",
)

vds_codes_for_spec = [k for k in idx if SPEC in k]
check(
    f"Multiple valve types indexed for {SPEC}",
    len(vds_codes_for_spec) >= 5,
    f"VDS codes built: {vds_codes_for_spec}",
)

# ---------------------------------------------------------------------------
# STEP 5 -- Datasheet values come FROM the PMS, not from hardcoded fallbacks
# ---------------------------------------------------------------------------

section("STEP 5 -- Datasheet values trace back to PMS input (data integrity)")

entry = idx.get(VDS_EXPECTED, {})

dp = entry.get("design_pressure", "")
check(
    f"design_pressure contains PMS value ({DESIGN_PRESSURE_BARG} barg)",
    str(DESIGN_PRESSURE_BARG) in str(dp) or "47.3" in str(dp),
    f"actual='{dp}'",
)

ht = entry.get("hydrotest_shell", "")
check(
    f"hydrotest_shell contains PMS value ({HYDROTEST_BARG} barg)",
    "70.95" in str(ht),
    f"actual='{ht}'",
)

bolts = entry.get("bolts", "")
check(
    "bolts came from PMS ('Demo Project' substring present)",
    "Demo Project" in bolts,
    f"actual='{bolts}'",
)

gasket = entry.get("gaskets", "")
check(
    f"gaskets came from PMS (timestamp {TS} present -- proves this exact POST)",
    str(TS) in gasket,
    f"actual='{gasket}'",
)

service_val = entry.get("service", "")
check(
    "service came from PMS ('Demo Project' substring present)",
    "Demo Project" in service_val,
    f"actual='{service_val}'",
)

pclass = entry.get("pressure_class", "")
check(
    "pressure_class correctly derived as Class 300 (from PMS pressure_rating)",
    "300" in pclass,
    f"actual='{pclass}'",
)

# ---------------------------------------------------------------------------
# STEP 6 -- Same PMS data flows to ALL valve types
# ---------------------------------------------------------------------------

section("STEP 6 -- All valve types share the same PMS data")

for vds in [f"GAYM{SPEC}R", f"GLYM{SPEC}R", f"CHPM{SPEC}R", f"CHSM{SPEC}R"]:
    e = idx.get(vds, {})
    if e:
        ok = "Demo Project" in e.get("bolts", "") and str(TS) in e.get("gaskets", "")
        check(f"{vds} -- bolts+gaskets from PMS", ok)
    else:
        check(f"{vds} present in index", False, "not found")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

passed = sum(1 for _, ok in _results if ok)
total  = len(_results)
failed = total - passed

print(f"\n{SEP}")
print(f"  RESULT: {passed}/{total} checks passed", end="")
if failed == 0:
    print("  -- ALL PASS")
    print()
    print("  PMS sync is working end-to-end:")
    print(f"    * New class '{SPEC}' synced to backend in real-time")
    print(f"    * Chatbot generated VDS code {VDS_EXPECTED} WITHOUT restart")
    print(f"    * Datasheet contains EXACT values from the PMS payload:")
    print(f"        design_pressure = {DESIGN_PRESSURE_BARG} barg  (from PMS header)")
    print(f"        hydrotest       = {HYDROTEST_BARG} barg  (from PMS header)")
    print(f"        bolts           = '{BOLTING}'")
    print(f"        gasket          = '{GASKET}'")
    print(f"    * {len(vds_codes_for_spec)} valve-type VDS codes auto-built for {SPEC}")
else:
    print(f"  -- {failed} FAILED")
    print()
    print("  Failed checks:")
    for label, ok in _results:
        if not ok:
            print(f"    [FAIL] {label}")
print(f"{SEP}\n")

sys.exit(0 if failed == 0 else 1)
