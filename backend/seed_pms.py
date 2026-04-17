"""Seed script — parse example PMS Excel files and store to both file + DB.

Usage:
    python seed_pms.py                          # seed demo-b1n from PMS_B1N_300.xlsx
    python seed_pms.py --all                    # seed from the full 94-sheet workbook too
    python seed_pms.py --file path/to/pms.xlsx --project my-project --name "My Project"

This populates:
  1. data/projects/{project_id}/pms.json + vds_index.json (file store)
  2. pms_sheets DB table (DB store)
"""
import argparse
import asyncio
import sys
from pathlib import Path

# Add the app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.pms.xlsx_parser import parse_xlsx
from app.pms.vds_builder import build_vds_index
from app.pms import store


async def seed_project(file_path: Path, project_id: str, project_name: str):
    print(f"\n{'='*60}")
    print(f"Seeding project: {project_id} ({project_name})")
    print(f"Source file: {file_path}")
    print(f"{'='*60}")

    # Parse Excel
    pms = parse_xlsx(file_path, project_id=project_id, project_name=project_name)
    print(f"Parsed {len(pms.piping_classes)} piping classes: {pms.class_codes()}")

    # Save to file store
    store.save_pms(pms)
    idx = build_vds_index(pms)
    store.save_vds_index(idx)
    print(f"File store: saved pms.json + vds_index.json ({len(idx.valid_codes())} VDS codes)")

    # Save raw upload
    content = file_path.read_bytes()
    store.save_raw_upload(project_id, file_path.name, content)
    print(f"Raw upload: saved {file_path.name}")

    # Save to DB
    try:
        saved = await store.save_pms_to_db(
            project_id=project_id,
            project_name=project_name,
            piping_classes=pms.piping_classes,
            source="xlsx_upload",
            source_file=file_path.name,
        )
        print(f"DB store: saved {len(saved)} classes to pms_sheets table")
    except Exception as e:
        print(f"DB store: skipped (DB not available: {e})")
        print("  -> File-based storage is still populated and will work fine.")

    print(f"\nProject '{project_id}' seeded successfully!")
    return pms


async def main():
    parser = argparse.ArgumentParser(description="Seed PMS data into the project store")
    parser.add_argument("--file", type=str, help="Path to PMS Excel file")
    parser.add_argument("--project", type=str, help="Project ID slug")
    parser.add_argument("--name", type=str, help="Project display name")
    parser.add_argument("--all", action="store_true", help="Also seed from the full 94-sheet workbook")
    args = parser.parse_args()

    base_dir = Path(__file__).parent.parent  # Valve_SPE root

    if args.file:
        # Custom file
        await seed_project(
            file_path=Path(args.file),
            project_id=args.project or "custom-project",
            project_name=args.name or args.project or "Custom Project",
        )
    else:
        # Default: seed demo-b1n from PMS_B1N_300.xlsx
        b1n_path = base_dir / "PMS_B1N_300.xlsx"
        if b1n_path.exists():
            await seed_project(
                file_path=b1n_path,
                project_id="demo-b1n",
                project_name="Demo B1N 300#",
            )
        else:
            print(f"Warning: {b1n_path} not found, skipping demo-b1n seed")

        if args.all:
            # Seed from the full workbook (rnd_sheet)
            full_path = base_dir / "rnd_sheet" / "Pipe Class Sheets-With Tubing(30-3).xlsx"
            if full_path.exists():
                await seed_project(
                    file_path=full_path,
                    project_id="fpso-albacora",
                    project_name="FPSO Albacora Full PMS",
                )
            else:
                print(f"Warning: {full_path} not found, skipping full PMS seed")

    # Summary
    print(f"\n{'='*60}")
    print("SEED COMPLETE — Available projects:")
    for meta in store.list_projects():
        pms = store.load_pms(meta.project_id)
        idx = store.load_vds_index(meta.project_id)
        print(f"  {meta.project_id}: {len(pms.piping_classes)} classes, "
              f"{len(idx.valid_codes()) if idx else 0} VDS codes "
              f"[{meta.status}]")


if __name__ == "__main__":
    asyncio.run(main())
