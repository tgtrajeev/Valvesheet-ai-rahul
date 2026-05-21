"""
Diagnostic: connect to Render DB and check whether datasheet_notes
is present in stored session events.
"""

import json
import psycopg2

RENDER_DB = (
    "postgresql://valve_agent_user:INquMELfIzyzNijYhaZrGjAHDwNhf3Bh"
    "@dpg-d7b4toqa214c73clbsig-a.oregon-postgres.render.com/valve_agent"
)

conn = psycopg2.connect(RENDER_DB)
cur = conn.cursor()

# ── 1. Recent sessions ──────────────────────────────────────────────────────
print("=" * 60)
print("RECENT SESSIONS (last 10)")
print("=" * 60)
cur.execute("""
    SELECT id, title, created_at, updated_at
    FROM agent_sessions
    ORDER BY updated_at DESC
    LIMIT 10
""")
sessions = cur.fetchall()
for s in sessions:
    print(f"  {s[0][:8]}...  '{s[1]}'  updated={s[3]}")

# ── 2. Check stored datasheet events for datasheet_notes ───────────────────
print()
print("=" * 60)
print("CHECKING STORED DATASHEET EVENTS FOR NOTES")
print("=" * 60)

cur.execute("""
    SELECT id, title, metadata_
    FROM agent_sessions
    ORDER BY updated_at DESC
    LIMIT 20
""")
rows = cur.fetchall()

sessions_with_notes    = 0
sessions_without_notes = 0
sessions_no_datasheet  = 0

for sid, title, meta in rows:
    if not meta:
        continue
    ui_events = meta.get("ui_events", [])
    ds_events = [e for e in ui_events if e.get("type") == "datasheet"]
    if not ds_events:
        sessions_no_datasheet += 1
        continue
    for evt in ds_events:
        data = (evt.get("data") or {}).get("data") or {}
        vds = (evt.get("data") or {}).get("vds_code", "?")
        has_notes = bool(data.get("datasheet_notes"))
        if has_notes:
            sessions_with_notes += 1
            print(f"  ✓ {sid[:8]}... '{title}' VDS={vds}  notes PRESENT")
        else:
            sessions_without_notes += 1
            print(f"  ✗ {sid[:8]}... '{title}' VDS={vds}  notes MISSING")
            print(f"    data keys: {list(data.keys())[:10]}")

print()
print(f"Sessions with notes:      {sessions_with_notes}")
print(f"Sessions without notes:   {sessions_without_notes}")
print(f"Sessions no DS event:     {sessions_no_datasheet}")

# ── 3. Live test: call the datasheets endpoint logic directly ──────────────
print()
print("=" * 60)
print("LIVE NOTES INJECTION TEST (first VDS from a missing-notes session)")
print("=" * 60)

# Find a VDS code that has missing notes
test_vds = None
for sid, title, meta in rows:
    if not meta:
        continue
    for evt in (meta.get("ui_events") or []):
        if evt.get("type") == "datasheet":
            data = (evt.get("data") or {}).get("data") or {}
            if not data.get("datasheet_notes"):
                test_vds = (evt.get("data") or {}).get("vds_code")
                break
    if test_vds:
        break

if test_vds:
    print(f"Testing VDS: {test_vds}")
    import sys
    sys.path.insert(0, ".")
    try:
        from app.engine.vds_decoder import decode_vds
        decoded = decode_vds(test_vds)
        print(f"  decode_vds OK → valve_type={decoded.valve_type.value}, is_nace={decoded.is_nace}")
        from app.engine.rule_engine import footer_notes_as_text
        notes = footer_notes_as_text(decoded.valve_type.value, decoded.is_nace)
        print(f"  footer_notes_as_text OK → {len(notes)} chars")
        print(f"  First 100 chars: {notes[:100]}")
    except Exception as e:
        print(f"  ERROR: {e}")
else:
    print("No VDS with missing notes found in recent sessions.")

cur.close()
conn.close()
print()
print("Done.")
