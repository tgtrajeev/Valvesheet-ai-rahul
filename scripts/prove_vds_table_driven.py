"""prove_vds_table_driven.py — for a given VDS code + size, show:

    1. The engine's output value
    2. The citation pointing to API 6D Table X / page N
    3. The exact PDF text excerpt showing that same value on that page

The client can then open API 6D (1).pdf, jump to the cited page, and
visually confirm.

Run:
    python -m scripts.prove_vds_table_driven BLFTA1R 6
    python -m scripts.prove_vds_table_driven GAYMD2NR 8
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
SPE_ROOT = REPO_ROOT.parent
API_6D_PDF = SPE_ROOT / "API 6D (1).pdf"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("vds")
    p.add_argument("nps", type=float)
    args = p.parse_args()
    sys.path.insert(0, str(REPO_ROOT))

    from app.engine.vds_decoder import decode_vds
    from app.engine.rule_engine import generate_datasheet
    import pypdf

    decoded = decode_vds(args.vds)
    data, prov = generate_datasheet(decoded, size_inches=args.nps, return_provenance=True)

    print("=" * 100)
    print(f" PER-VDS TABLE-DRIVEN PROOF — VDS: {args.vds}    NPS: {args.nps}\"")
    print("=" * 100)

    table_fields = ("face_to_face", "hydrotest_shell", "hydrotest_closure", "ball_construction")
    pdf_pages: list[str] = []

    print(f"\n  Source standard: API 6D (1).pdf  (loaded {API_6D_PDF})")
    if API_6D_PDF.exists():
        r = pypdf.PdfReader(str(API_6D_PDF))
        pdf_pages = [(pg.extract_text() or "") for pg in r.pages]
        print(f"  Extracted {len(pdf_pages)} pages\n")

    for fld in table_fields:
        if fld not in data:
            continue
        value = data[fld]
        source = prov.get(fld, "<no source>")
        print("─" * 100)
        print(f"  FIELD : {fld}")
        print(f"  VALUE : {value}")
        print(f"  CITED : {source}")

        # Try to find the cited PDF page number from the source string
        m = re.search(r"PDF p\.(\d+)", source)
        if m and pdf_pages:
            pdf_p = int(m.group(1))
            page_text = pdf_pages[pdf_p - 1] if 0 < pdf_p <= len(pdf_pages) else ""
            # Try to match on a value substring like "15.50 (394)"
            v_match = re.search(r"(\d+\.\d{2})\s*\((\d+)\)", value)
            if v_match:
                in_v, mm_v = v_match.group(1), v_match.group(2)
                # Find a few lines around this match
                normalized = re.sub(r"[ \t]+", " ", page_text)
                idx = normalized.find(f"{in_v} ({mm_v})")
                if idx >= 0:
                    excerpt = normalized[max(0, idx - 80) : idx + 100]
                    print(f"  PDF EXCERPT (page {pdf_p}, found at character {idx}):")
                    for line in excerpt.splitlines():
                        if line.strip():
                            print(f"     {line.strip()}")
                else:
                    print(f"  ⚠ Value '{in_v} ({mm_v})' not found on PDF p.{pdf_p}")
            else:
                # Show the first 6 non-empty lines of the cited page as evidence
                lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()][:8]
                print(f"  PDF EXCERPT (page {pdf_p}):")
                for ln in lines:
                    print(f"     {ln}")
        print()

    print("=" * 100)
    print(" To independently verify: open API 6D (1).pdf, jump to the cited PDF page,")
    print(" find the matching row — the value MUST match what the engine emitted.")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
