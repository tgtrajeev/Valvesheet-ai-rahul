"""PMS Resolver — Runtime field resolution from PMS extracted data.

Pure-function resolver that replaces hardcoded dictionary lookups with actual
PMS data. Each function tries PMS data first, with graceful fallback.
"""

import re
from .pms_loader import get_pms_loader, PmsSpec


def resolve_hydrotest(spec_code: str) -> tuple[str, str]:
    """Resolve hydrotest shell and closure from PMS INDEX col 33 (AG).

    Returns:
        (shell_str, closure_str) e.g. ("29.4 barg", "21.56 barg")
        Falls back to ("-", "-") if PMS data unavailable.
    """
    loader = get_pms_loader()
    shell, closure = loader.get_hydrotest(spec_code)
    if shell is not None and closure is not None:
        return f"{shell} barg", f"{closure} barg"
    return "-", "-"


def resolve_gaskets(spec_code: str) -> str | None:
    """Resolve gasket specification from PMS bolting_gaskets table."""
    loader = get_pms_loader()
    return loader.get_gaskets(spec_code)


def resolve_bolts(spec_code: str) -> str | None:
    """Resolve stud bolt specification from PMS bolting_gaskets table."""
    loader = get_pms_loader()
    return loader.get_bolts(spec_code)


def resolve_nuts(spec_code: str) -> str | None:
    """Resolve hex nut specification from PMS bolting_gaskets table."""
    loader = get_pms_loader()
    return loader.get_nuts(spec_code)


def resolve_design_pressure(spec_code: str) -> float | None:
    """Resolve design pressure (barg) from PMS INDEX PT data."""
    loader = get_pms_loader()
    return loader.get_design_pressure(spec_code)


def resolve_flange_face(spec_code: str, nps: float | None = None) -> str | None:
    """Resolve flange face type from PMS flange data."""
    loader = get_pms_loader()
    return loader.get_flange_face(spec_code, nps)


# ── 3-tier piping-class resolver ──────────────────────────────────────────────
#
# Domain rule (verified against pms_extracted.json, 92 spec codes):
#   - (pressure, material) alone is unique for ~79% of classes (73 / 92).
#   - Adding corrosion_allowance (CA) covers ~93% (86 / 92).
#   - The remaining 6 codes (GRE A50/A51/A52, SS-316 tubing T80x, 6MO tubing T90x)
#     need service to disambiguate.
# So: ask pressure+material first, then CA only if needed, then service only
# if still ambiguous. No point asking everything up front.

def _norm_pressure(value: str | int | None) -> str | None:
    """Normalize pressure rating to canonical PMS form (e.g. '150#').

    Accepts: 150, '150', '150#', 'Class 150', 'ASME 150', '#150'.
    Returns None if no number found (used for tubing classes with rating=None).
    """
    if value is None or value == "":
        return None
    s = str(value).strip().upper()
    m = re.search(r"\d+", s)
    if not m:
        return None
    return f"{m.group(0)}#"


def _material_tokens(value: str | None) -> set[str]:
    """Tokenize a material string for matching.

    Strips parenthetical asides like '(Valve: SS)' or '(Tubing)' first — those
    describe valve/pipe-type metadata that engineers don't include when naming
    the line material. Then collapses common aliases and splits on punctuation.

    'CS NACE' -> {'cs', 'nace'}
    'CS GALV (Valve: SS)' -> {'cs', 'galv'}
    'carbon steel sour' -> {'cs', 'nace'}  (via aliases)
    """
    if not value:
        return set()
    s = value.lower()
    # strip parenthetical metadata (e.g. '(Valve: NAB)', '(Tubing)')
    s = re.sub(r"\(.*?\)", " ", s)
    # collapse common aliases before tokenizing
    aliases = [
        ("low temperature carbon steel", "ltcs"),
        ("low-temp carbon steel", "ltcs"),
        ("low temp carbon steel", "ltcs"),
        ("carbon steel", "cs"),
        ("super duplex", "sdss"),
        ("stainless steel", "ss"),
        ("stainless", "ss"),
        ("sour service", "nace"),
        ("sour", "nace"),
        ("h2s", "nace"),
        ("galvanised", "galv"),
        ("galvanized", "galv"),
    ]
    for src, dst in aliases:
        s = s.replace(src, dst)
    # split letter<->digit boundaries so 'SS316L' tokenizes the same as 'SS 316L'
    s = re.sub(r"([a-z])(\d)", r"\1 \2", s)
    s = re.sub(r"(\d)([a-z])", r"\1 \2", s)
    # strip punctuation, split
    return {t for t in re.split(r"[^a-z0-9]+", s) if t}


def _material_matches(query_tokens: set[str], spec_material: str | None) -> bool:
    """A spec matches when its material tokens equal the query tokens.

    Exact-set semantics (not subset): 'CS' must match only plain CS, not
    'CS NACE' or 'CS GALV'. If the user wants NACE they say so. This is the
    behavior an engineer expects when naming a line material.
    """
    if not query_tokens:
        return True
    spec_tokens = _material_tokens(spec_material)
    return query_tokens == spec_tokens


def _ca_equal(query_ca: str | None, spec_ca: str | None) -> bool:
    """Compare CA strings tolerantly: '3', '3 mm', '3mm' all equal '3 mm'.

    'NIL' matches 'NIL' / 'nil' / '0' / '0 mm'.
    """
    if query_ca is None:
        return True
    q = str(query_ca).strip().lower()
    s = (spec_ca or "").strip().lower()
    if q in ("nil", "0", "0 mm", "none"):
        return s in ("nil", "0", "0 mm", "")
    qm = re.search(r"\d+(?:\.\d+)?", q)
    sm = re.search(r"\d+(?:\.\d+)?", s)
    if qm and sm:
        return float(qm.group(0)) == float(sm.group(0))
    return q == s


def _service_matches(query: str | None, spec_service: str | None) -> bool:
    """A spec matches if any query token appears in the spec's service text."""
    if not query:
        return True
    if not spec_service:
        return False
    q_tokens = {t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) >= 3}
    s_lower = spec_service.lower()
    return any(t in s_lower for t in q_tokens)


def _spec_summary(spec: PmsSpec) -> dict:
    """Compact dict for returning candidate specs to the caller / agent."""
    h = spec.header
    return {
        "spec_code": spec.spec_code,
        "pressure_rating": h.pressure_rating,
        "material_description": h.material_description,
        "corrosion_allowance": h.corrosion_allowance,
        "service": (h.service[:120] + "...") if h.service and len(h.service) > 120 else h.service,
        "nace": h.nace_flag,
        "low_temp": h.lt_flag,
    }


def resolve_piping_class(
    pressure_rating: str | int | None,
    material: str | None,
    corrosion_allowance: str | None = None,
    service: str | None = None,
) -> dict:
    """3-tier deterministic piping-class resolver.

    Returns one of:
      {"status": "unique", "spec_code": "A1", "spec": {...}}
      {"status": "needs_ca", "candidates": [...], "ca_options": ["3 mm", "6 mm"], ...}
      {"status": "needs_service", "candidates": [...], "service_options": [...], ...}
      {"status": "no_match", "hint": "...", "available_pressures": [...], ...}
      {"status": "needs_input", "hint": "..."}  (when pressure+material both missing)
    """
    if not pressure_rating and not material:
        return {
            "status": "needs_input",
            "hint": "Provide at least pressure rating (e.g. 150, 300) and material (e.g. CS, SS 316, CS NACE).",
        }

    loader = get_pms_loader()
    norm_pressure = _norm_pressure(pressure_rating)
    mat_tokens = _material_tokens(material)

    # Tier 1: filter by pressure + material
    candidates: list[PmsSpec] = []
    for code in loader.spec_codes:
        spec = loader.get_spec(code)
        if not spec:
            continue
        if norm_pressure is not None and spec.header.pressure_rating != norm_pressure:
            continue
        if mat_tokens and not _material_matches(mat_tokens, spec.header.material_description):
            continue
        candidates.append(spec)

    if not candidates:
        # Help the agent recover: list what *is* available for the given pressure
        if norm_pressure:
            mats_at_pressure = sorted({
                loader.get_spec(c).header.material_description
                for c in loader.spec_codes
                if loader.get_spec(c).header.pressure_rating == norm_pressure
                and loader.get_spec(c).header.material_description
            })
            return {
                "status": "no_match",
                "hint": f"No piping class matches pressure={norm_pressure} + material='{material}'. "
                        f"Materials available at {norm_pressure}: {mats_at_pressure}",
                "available_materials": mats_at_pressure,
            }
        return {
            "status": "no_match",
            "hint": f"No piping class matches material='{material}'. Try a different material name.",
        }

    if len(candidates) == 1:
        return {
            "status": "unique",
            "spec_code": candidates[0].spec_code,
            "spec": _spec_summary(candidates[0]),
        }

    # Tier 2: try CA filter
    if corrosion_allowance is not None:
        ca_matches = [c for c in candidates if _ca_equal(corrosion_allowance, c.header.corrosion_allowance)]
        if not ca_matches:
            ca_options = sorted({c.header.corrosion_allowance or "NIL" for c in candidates})
            return {
                "status": "needs_ca",
                "hint": f"CA '{corrosion_allowance}' doesn't match any candidate. Available: {ca_options}",
                "candidates": [_spec_summary(c) for c in candidates],
                "ca_options": ca_options,
            }
        candidates = ca_matches

    if len(candidates) == 1:
        return {
            "status": "unique",
            "spec_code": candidates[0].spec_code,
            "spec": _spec_summary(candidates[0]),
        }

    # Still ambiguous: do all candidates have the same CA? If not, ask CA.
    ca_set = {c.header.corrosion_allowance or "NIL" for c in candidates}
    if len(ca_set) > 1 and corrosion_allowance is None:
        return {
            "status": "needs_ca",
            "hint": f"Multiple piping classes match. Specify corrosion allowance to narrow down.",
            "candidates": [_spec_summary(c) for c in candidates],
            "ca_options": sorted(ca_set),
        }

    # Tier 3: service disambiguation (GRE / tubing case)
    if service is not None:
        svc_matches = [c for c in candidates if _service_matches(service, c.header.service)]
        if len(svc_matches) == 1:
            return {
                "status": "unique",
                "spec_code": svc_matches[0].spec_code,
                "spec": _spec_summary(svc_matches[0]),
            }
        if svc_matches:
            candidates = svc_matches

    if len(candidates) == 1:
        return {
            "status": "unique",
            "spec_code": candidates[0].spec_code,
            "spec": _spec_summary(candidates[0]),
        }

    # Need service input — surface the service descriptions so the agent can ask intelligently
    return {
        "status": "needs_service",
        "hint": "Multiple piping classes share the same pressure/material/CA. Pick by service.",
        "candidates": [_spec_summary(c) for c in candidates],
        "service_options": [
            {"spec_code": c.spec_code, "service": c.header.service or ""}
            for c in candidates
        ],
    }


def get_pms_field_sources(spec_code: str, data: dict[str, str]) -> dict[str, str]:
    """Generate granular PMS-aware field source descriptions.

    Instead of generic "As per PMS Base material and Valve Standard",
    returns specific sources like "PMS A1 -- bolting_gaskets table".

    Args:
        spec_code: The piping class (e.g., "A1", "B1N")
        data: Flat datasheet dict

    Returns:
        Dict mapping field_name -> granular source description
    """
    from .field_sources import FIELD_SOURCE_MAP, SRC_VALVE_STD

    sources: dict[str, str] = {}
    loader = get_pms_loader()
    pms_spec = loader.get_spec(spec_code)

    for key in data:
        base_source = FIELD_SOURCE_MAP.get(key, SRC_VALVE_STD)

        # Override with granular PMS source where applicable
        _PMS_REF = "40801-SPE-80000-PP-SP-0001"
        if pms_spec:
            if key in ("hydrotest_shell", "hydrotest_closure"):
                if pms_spec.index_row and pms_spec.index_row.hydrotest_barg:
                    base_source = f"PMS {spec_code} — {_PMS_REF} (Hydrotest P-T table)"
            elif key == "design_pressure":
                if pms_spec.index_row and pms_spec.index_row.design_pressure_barg:
                    base_source = f"PMS {spec_code} — {_PMS_REF} (P-T ratings)"
            elif key == "gaskets":
                if pms_spec.bolting_gaskets and pms_spec.bolting_gaskets.gasket_spec:
                    base_source = f"PMS {spec_code} — {_PMS_REF} (bolting & gasket table)"
            elif key == "bolts":
                if pms_spec.bolting_gaskets and pms_spec.bolting_gaskets.stud_bolt_spec:
                    base_source = f"PMS {spec_code} — {_PMS_REF} (bolting & gasket table)"
            elif key == "nuts":
                if pms_spec.bolting_gaskets and pms_spec.bolting_gaskets.hex_nut_spec:
                    base_source = f"PMS {spec_code} — {_PMS_REF} (bolting & gasket table)"
            elif key == "body_material":
                base_source = f"PMS {spec_code} — {_PMS_REF} + VMS 40801-SPE-80000-PP-SP-0002"
            elif key in ("size_range", "service", "pressure_class", "sour_service"):
                base_source = f"PMS {spec_code} — {_PMS_REF}"

        sources[key] = base_source

    return sources


# ── User-override validation helpers ─────────────────────────────────────

_BARG_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*bar", re.IGNORECASE)
_CELSIUS_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:deg\s*)?°?\s*c\b", re.IGNORECASE)
_MM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mm", re.IGNORECASE)
_RATING_RE = re.compile(r"(\d+)")


def _parse_barg(value) -> float | None:
    """Extract a single barg numeric value from a user string.
    Returns None if the string looks like a P-T curve (multiple temps) or is empty.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.count("@") >= 1 or s.count(",") >= 1:
        return None
    m = _BARG_RE.search(s)
    if m:
        return float(m.group(1))
    try:
        return float(s)
    except ValueError:
        return None


def _parse_celsius(value) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = _CELSIUS_RE.search(s)
    if m:
        return float(m.group(1))
    try:
        return float(s)
    except ValueError:
        return None


def _parse_mm(value) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.upper() == "NIL":
        return 0.0
    m = _MM_RE.search(s)
    if m:
        return float(m.group(1))
    try:
        return float(s)
    except ValueError:
        return None


def _rating_to_int(pressure_rating: str | None) -> int | None:
    """Extract integer class from a rating label, e.g. '150#' / '300#, RF' → 150."""
    if not pressure_rating:
        return None
    m = _RATING_RE.search(str(pressure_rating))
    return int(m.group(1)) if m else None


def _interpolate_pressure(pt_breakpoints: list[dict], temperature_c: float) -> float | None:
    """Linearly interpolate the allowable barg at temperature_c from PMS P-T breakpoints.

    Breakpoint schema (app PmsIndexRow): list of {"temp_c": float, "press_barg": float}.
    Returns the endpoint value if temperature_c is outside the tabulated range.
    """
    if not pt_breakpoints:
        return None
    pts = sorted(
        ((r.get("temp_c"), r.get("press_barg")) for r in pt_breakpoints),
        key=lambda x: (x[0] if x[0] is not None else -1e9),
    )
    pts = [(t, p) for t, p in pts if t is not None and p is not None]
    if not pts:
        return None
    if temperature_c <= pts[0][0]:
        return pts[0][1]
    if temperature_c >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        t1, p1 = pts[i]
        t2, p2 = pts[i + 1]
        if t1 <= temperature_c <= t2:
            if t2 == t1:
                return p1
            ratio = (temperature_c - t1) / (t2 - t1)
            return p1 + ratio * (p2 - p1)
    return None


def _service_covered(user_service: str, allowed_service: str) -> bool:
    """Check if every non-trivial token in user_service appears in allowed_service."""
    if not user_service or not allowed_service:
        return True
    stop = {"service", "and", "or", "the", "a", "for", "of", "with", "low", "high"}
    u_tokens = {t for t in re.findall(r"[a-z0-9]+", user_service.lower()) if t not in stop and len(t) > 2}
    a_text = allowed_service.lower()
    return all(t in a_text for t in u_tokens) if u_tokens else True
