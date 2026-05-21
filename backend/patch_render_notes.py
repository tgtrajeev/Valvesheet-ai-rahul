"""
Patch script: backfill datasheet_notes into stored Render DB sessions.

For every stored session event of type "datasheet" that is missing
datasheet_notes in its data dict, this script:
  1. Reads the VDS code from the event
  2. Generates the footer notes locally using footer_notes_as_text
  3. Injects the notes into event.data.data.datasheet_notes
  4. Writes the updated metadata back to the DB

Run from the backend directory:
    python patch_render_notes.py
    python patch_render_notes.py --dry-run
"""

import json
import sys
import psycopg2
import psycopg2.extras

RENDER_DB = (
    "postgresql://valve_agent_user:INquMELfIzyzNijYhaZrGjAHDwNhf3Bh"
    "@dpg-d7b4toqa214c73clbsig-a.oregon-postgres.render.com/valve_agent"
)

sys.path.insert(0, ".")

# Import local engine modules
try:
    from app.engine.vds_decoder import decode_vds
    from app.engine.rule_engine import footer_notes_as_text
    print("OK: Local engine modules loaded")
except Exception as e:
    print(f"ERR: Cannot load engine modules: {e}")
    sys.exit(1)


def get_notes_for_vds(vds_code):
    """Generate footer notes for a VDS code, return None on failure."""
    try:
        decoded = decode_vds(vds_code)
        return footer_notes_as_text(decoded.valve_type.value, decoded.is_nace)
    except Exception as e:
        print(f"    WARN: Cannot generate notes for {vds_code}: {e}")
        return None


def patch_sessions(dry_run=False):
    conn = psycopg2.connect(RENDER_DB)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Fetch all sessions that have metadata with ui_events
    cur.execute("""
        SELECT id, title, metadata
        FROM sessions
        WHERE metadata IS NOT NULL
          AND metadata::text != '{}'
        ORDER BY updated_at DESC
    """)
    rows = cur.fetchall()

    print(f"\nFetched {len(rows)} sessions with metadata")
    print("=" * 60)

    patched_sessions = 0
    patched_events = 0
    skipped_no_vds = 0
    skipped_already_has_notes = 0

    for row in rows:
        sid = row["id"]
        title = row["title"] or "?"
        meta = row["metadata"]

        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                continue

        ui_events = meta.get("ui_events", [])
        if not ui_events:
            continue

        session_dirty = False
        for evt in ui_events:
            if evt.get("type") != "datasheet":
                continue

            event_data = evt.get("data") or {}
            data_dict = event_data.get("data") or {}

            # Already has notes -- skip
            if data_dict.get("datasheet_notes"):
                skipped_already_has_notes += 1
                continue

            # Get VDS code
            vds_code = (
                event_data.get("vds_code")
                or data_dict.get("vds_no")
                or data_dict.get("vds_code")
            )
            if not vds_code:
                print(f"  WARN: {sid[:8]}... '{title}' -- no VDS code found in event, skipping")
                skipped_no_vds += 1
                continue

            # Generate notes
            notes = get_notes_for_vds(vds_code)
            if notes is None:
                continue

            # Inject notes into the nested data dict
            evt["data"]["data"]["datasheet_notes"] = notes
            session_dirty = True
            patched_events += 1
            print(f"  PATCH: {sid[:8]}... '{title}' VDS={vds_code}  -> injected {len(notes)} chars")

        if session_dirty:
            if not dry_run:
                cur.execute(
                    "UPDATE sessions SET metadata = %s::jsonb WHERE id = %s",
                    (json.dumps(meta), sid),
                )
            patched_sessions += 1

    print()
    print("=" * 60)
    print(f"Sessions patched:           {patched_sessions}")
    print(f"Events patched:             {patched_events}")
    print(f"Events already had notes:   {skipped_already_has_notes}")
    print(f"Events skipped (no VDS):    {skipped_no_vds}")

    if dry_run:
        print("\nDRY RUN -- no changes written to DB")
        conn.rollback()
    else:
        conn.commit()
        print(f"\nCommitted {patched_sessions} session updates to Render DB")

    cur.close()
    conn.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    if dry:
        print("DRY RUN mode -- will not write to DB")
    patch_sessions(dry_run=dry)
