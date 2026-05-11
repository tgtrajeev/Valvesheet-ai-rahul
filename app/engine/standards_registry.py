"""standards_registry.py — maps standard names to their on-disk PDF filenames
and page-offsets, so citations can become clickable links.

For each standard we know:
  - the canonical name we cite (e.g., "API SPEC 6D")
  - the filename on disk (e.g., "API 6D (1).pdf")
  - whether the PDF page index matches the standard's printed page numbers,
    or if there's a constant offset (printed_page + offset = pdf_page)

Citations served by the API include a URL of the form:
    /api/standards/{slug}?page={pdf_page}
The frontend renders that as <a href> opening the PDF anchored at #page=N
which most browsers honor.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class StandardDoc:
    canonical_name: str       # how we cite it (e.g., "API SPEC 6D")
    slug: str                 # URL slug (e.g., "api-6d")
    filename: str             # actual file in the reference folders
    page_offset: int          # printed page X = pdf page (X + offset)
    description: str = ""

    def pdf_page_for(self, printed_page: int) -> int:
        """Convert a printed page number into a 1-based PDF page index."""
        return max(1, printed_page + self.page_offset)


# Where the PDFs live on disk (search order)
SEARCH_DIRS = [
    Path(r"C:\Users\lenovo\Desktop\SPE\Reference Code and Standards"),
    Path(r"C:\Users\lenovo\Desktop\SPE"),
]


_REGISTRY: list[StandardDoc] = [
    # API standards
    StandardDoc("API SPEC 6D",   "api-6d",       "API 6D (1).pdf",  14, "Pipeline and Piping Valves (24th ed., 2014 + Errata 9)"),
    StandardDoc("API RP 615",    "api-615",      "API 615.pdf",      7, "Valve Selection Guide (2nd ed., 2016)"),
    # ASME standards (in Reference Code and Standards)
    StandardDoc("ASME B16.5",    "asme-b16-5",   "ASME B16.5.pdf",   0, "Pipe Flanges & Flanged Fittings NPS 1/2 to 24 (2017)"),
    StandardDoc("ASME B16.5-2020","asme-b16-5-2020","ASME B16.5_2020.pdf", 0, "Pipe Flanges & Flanged Fittings NPS 1/2 to 24 (2020)"),
    StandardDoc("ASME B16.9",    "asme-b16-9",   "ASME B16.9.pdf",   0, "Factory-Made Wrought Buttwelding Fittings (2018)"),
    StandardDoc("ASME B16.11",   "asme-b16-11",  "ASME B16.11.pdf",  0, "Forged Fittings, Socket-Welding and Threaded (2016)"),
    StandardDoc("ASME B16.20",   "asme-b16-20",  "ASME B16.20.pdf",  0, "Metallic Gaskets for Pipe Flanges (2017)"),
    StandardDoc("ASME B16.25",   "asme-b16-25",  "ASME B16.25.pdf",  0, "Buttwelding Ends (2017)"),
    StandardDoc("ASME B16.47",   "asme-b16-47",  "ASME B16.47.pdf",  0, "Large Diameter Steel Flanges NPS 26-60 (2017)"),
    StandardDoc("ASME B16.48",   "asme-b16-48",  "ASME B16.48.pdf",  0, "Line Blanks (2015)"),
    StandardDoc("ASME B31.3",    "asme-b31-3",   "ASME B31.3_2020.pdf", 0, "Process Piping Code (2020)"),
    StandardDoc("ASME B36.10M",  "asme-b36-10m", "ASME B36.10M.pdf", 0, "Welded and Seamless Wrought Steel Pipe (2018)"),
    StandardDoc("ASME B36.19M",  "asme-b36-19m", "ASME B36.19M.pdf", 0, "Stainless Steel Pipe (2018)"),
    # Project PMS document
    StandardDoc("PMS_PDF",       "pms-pdf",      "PMS_PDF.pdf",      0, "Project PMS / Valve Material Specification"),
]


def find_pdf(slug: str) -> Path | None:
    """Return the absolute path to the PDF for a given slug, or None if not on disk."""
    for d in _REGISTRY:
        if d.slug == slug:
            for base in SEARCH_DIRS:
                p = base / d.filename
                if p.exists():
                    return p
            return None
    return None


def get_doc(canonical_or_slug: str) -> StandardDoc | None:
    """Look up a doc by canonical name or slug (case-insensitive)."""
    s = canonical_or_slug.lower()
    for d in _REGISTRY:
        if d.canonical_name.lower() == s or d.slug.lower() == s:
            return d
    # Fuzzy: prefix
    for d in _REGISTRY:
        if d.canonical_name.lower().startswith(s):
            return d
    return None


def list_docs() -> list[dict]:
    """Return the registry as a JSON-serialisable list (used by /api/standards)."""
    return [
        {
            "canonical_name": d.canonical_name,
            "slug": d.slug,
            "filename": d.filename,
            "available": find_pdf(d.slug) is not None,
            "description": d.description,
        }
        for d in _REGISTRY
    ]


def build_citation_url(canonical_name: str, printed_page: int | None = None,
                       pdf_page: int | None = None,
                       base: str = "/api/standards") -> str | None:
    """Produce a URL the frontend can use as <a href>.
    `pdf_page` (1-based PDF index) takes precedence over `printed_page`.
    """
    doc = get_doc(canonical_name)
    if not doc:
        return None
    pg = pdf_page if pdf_page else (doc.pdf_page_for(printed_page) if printed_page else None)
    url = f"{base}/{doc.slug}"
    if pg:
        url += f"#page={pg}"
    return url
