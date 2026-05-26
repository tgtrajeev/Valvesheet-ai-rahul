"""v2 Datasheets — PMS Generator pipeline (separate from frozen v1).

Endpoints:
  POST /api/v2/pms-context       — Ingest PMS Generator JSON, store, return context_id
  GET  /api/v2/pms-context       — List all stored PMS contexts
  GET  /api/v2/pms-context/{id}  — Get a specific stored context
  GET  /api/v2/datasheets/{code} — Generate datasheet from PMS context

These endpoints are COMPLETELY INDEPENDENT of the v1 pipeline. They never
read from pms_extracted.json, pms_vds_datasheets.json, or the global
PmsLoader singleton. All data flows through PmsContext.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import settings
from ..pms.context_schema import PmsGeneratorInput
from ..engine.pms_context import PmsContext
from ..engine.vds_decoder import decode_vds
from ..engine.generate_v2 import generate_datasheet_v2
from ..engine.card_filter import filter_card_data, filter_card_metadata
from ..models.schemas import DatasheetResponse
from ..engine.field_sources import get_field_sources

router = APIRouter()

# ── Class-code normalisation ─────────────────────────────────────────────
# PMS Generator produces "New-spec-[A1]" for custom classes derived from A1.
# Until the PMS Generator stabilises its naming, we map these to the Y-letter
# class codes the VDS decoder understands.

import re as _re

_NEW_SPEC_RE = _re.compile(r"^New-spec-\[([A-Z])(\d+)\]$", _re.IGNORECASE)

# Map: base-class letter → custom letter.  Extend as needed.
_CUSTOM_LETTER_MAP: dict[str, str] = {
    "A": "Y",   # New-spec-[A1] → Y1
}


def _normalise_class_code(raw_code: str) -> str:
    """Turn 'New-spec-[A1]' into 'Y1' (or whatever the mapping says).

    If the code is already a normal class code (e.g. 'Y1', 'A1'), it passes
    through unchanged.
    """
    m = _NEW_SPEC_RE.match(raw_code.strip())
    if not m:
        return raw_code
    base_letter, digit = m.group(1).upper(), m.group(2)
    new_letter = _CUSTOM_LETTER_MAP.get(base_letter, base_letter)
    return f"{new_letter}{digit}"


# ── Storage path ──────────────────────────────────────────────────────────

def _contexts_dir() -> Path:
    d = settings.data_dir / "pms_contexts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_context(context_id: str) -> PmsContext:
    """Load a stored PMS context by ID."""
    path = _contexts_dir() / f"{context_id}.json"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"PMS context '{context_id}' not found. Ingest first via POST /api/v2/pms-context.",
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    pms_input = PmsGeneratorInput(**raw["pms"])
    return PmsContext(pms_input)


def _load_context_by_class(class_code: str) -> PmsContext | None:
    """Find and load a context by piping class code (e.g. 'Y1').

    Normalises both the query and stored codes so 'New-spec-[A1]' matches 'Y1'.
    """
    normalised = _normalise_class_code(class_code).upper()
    for path in _contexts_dir().glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            stored = _normalise_class_code(raw.get("class_code", "")).upper()
            if stored == normalised:
                pms_input = PmsGeneratorInput(**raw["pms"])
                return PmsContext(pms_input)
        except Exception:
            continue
    return None


# Reverse of _CUSTOM_LETTER_MAP: custom letter → base letter
_REVERSE_LETTER_MAP: dict[str, str] = {v: k for k, v in _CUSTOM_LETTER_MAP.items()}


def auto_sync_from_generator(class_code: str) -> PmsContext | None:
    """Auto-pull a class from the PMS Generator DB and store as v2 PmsContext.

    Called by the agent tools when a user asks about a class that isn't in
    either the v1 pipeline OR the v2 context store. This is the "zero-button"
    sync — the ValveSheet agent fetches the PMS data on first request.

    Tries multiple name variants because the PMS Generator may store the class
    as 'New-spec-[A1]', 'Y1', or the original code like 'A1'.

    Returns the newly created PmsContext, or None if the class isn't in the
    PMS Generator DB.
    """
    import logging
    _log = logging.getLogger(__name__)

    normalised = _normalise_class_code(class_code).upper()

    # ── Build list of names to try against pms_cache ──
    names_to_try = [normalised, class_code.upper()]

    # If normalised is "Y1", also try "New-spec-[A1]" (reverse mapping)
    if len(normalised) >= 2:
        letter = normalised[0]
        digit_part = normalised[1:]
        if letter in _REVERSE_LETTER_MAP:
            base_letter = _REVERSE_LETTER_MAP[letter]
            names_to_try.append(f"New-spec-[{base_letter}{digit_part}]")
            names_to_try.append(f"{base_letter}{digit_part}")  # also try base code

    names_to_try = list(dict.fromkeys(names_to_try))  # dedupe, preserve order

    # ── Fetch from PMS Generator DB ──
    # Strategy: try saved_pms FIRST (has custom new specs with full payload),
    # then fall back to pms_cache (has standard classes in old format).
    try:
        from ..pms.render_sync import fetch_one_from_generator, fetch_one_from_saved_pms
    except Exception as exc:
        _log.debug("auto_sync: render_sync not available: %s", exc)
        return None

    raw_json = None
    source_table = None

    # 1) Try saved_pms first — custom specs like "New-spec-[A1]" live here
    for name in names_to_try:
        try:
            raw_json = fetch_one_from_saved_pms(name)
            if raw_json:
                source_table = "saved_pms"
                _log.info("auto_sync: found '%s' in saved_pms (queried as '%s')", class_code, name)
                break
        except Exception:
            continue

    # 2) Fall back to pms_cache (old-format response_json)
    if not raw_json:
        for name in names_to_try:
            try:
                raw_json = fetch_one_from_generator(name)
                if raw_json:
                    source_table = "pms_cache"
                    _log.info("auto_sync: found '%s' in pms_cache (queried as '%s')", class_code, name)
                    break
            except Exception:
                continue

    if not raw_json:
        _log.debug("auto_sync: '%s' not found in PMS Generator DB (tried: %s)", class_code, names_to_try)
        return None

    # ── Transform to PmsGeneratorInput ──
    try:
        from ..pms.response_to_v2 import try_parse_native, transform_to_v2

        pms_input = try_parse_native(raw_json)
        if pms_input is None:
            # saved_pms payload is already in PmsGeneratorInput format but
            # try_parse_native may fail if class_code key is missing — use
            # transform_to_v2 as fallback (handles old pms_cache format)
            pms_input = transform_to_v2(normalised, raw_json)
    except Exception as exc:
        _log.warning("auto_sync: transform failed for '%s': %s", class_code, exc)
        return None

    # ── Normalise class_code & set base_class_code for VDS rewriting ──
    # The saved_pms payload may have class_code="New-spec-[A1]" which we
    # normalise to "Y1". The base_class_code (A1) is what the VDS codes
    # in the PMS JSON reference, so get_vds_codes() can rewrite A1→Y1.
    raw_cc = (pms_input.class_code or "").strip()
    norm_cc = _normalise_class_code(raw_cc).upper()
    if norm_cc != raw_cc.upper():
        # class_code was "New-spec-[A1]" → normalised to "Y1"
        if pms_input.base_class_code is None:
            pms_input.base_class_code = raw_cc.upper()  # preserve original
        pms_input.class_code = norm_cc
        _log.info("auto_sync: normalised class_code '%s' -> '%s'", raw_cc, norm_cc)
    # Also handle case where class_code is already "Y1" but base not set
    if len(norm_cc) >= 2:
        _custom_letter = norm_cc[0]
        _digit = norm_cc[1:]
        if _custom_letter in _REVERSE_LETTER_MAP:
            _base_letter = _REVERSE_LETTER_MAP[_custom_letter]
            _base_code = f"{_base_letter}{_digit}"
            if pms_input.base_class_code is None:
                pms_input.base_class_code = _base_code
                _log.info("auto_sync: set base_class_code='%s' for class '%s'", _base_code, normalised)

    ctx = PmsContext(pms_input)
    v2_class = _normalise_class_code(ctx.get_class_code())

    # ── Store v2 context ──
    try:
        context_id = None
        for p in _contexts_dir().glob("*.json"):
            try:
                existing = json.loads(p.read_text(encoding="utf-8"))
                if _normalise_class_code(existing.get("class_code", "")).upper() == v2_class.upper():
                    context_id = p.stem
                    break
            except Exception:
                continue

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        payload = {
            "context_id": context_id,
            "class_code": v2_class,
            "label": f"PMS {v2_class} (auto-synced from PMS Generator)",
            "pms": pms_input.model_dump(),
        }
        ctx_path = _contexts_dir() / f"{context_id}.json"
        ctx_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        _log.info("auto_sync: stored v2 PmsContext for '%s' (context_id=%s)", v2_class, context_id)
    except Exception as exc:
        _log.warning("auto_sync: context storage failed for '%s': %s", v2_class, exc)
        # Still return the context even if storage fails — it's usable for this request
        pass

    return ctx


# ── Request / response models ─────────────────────────────────────────────

class IngestPmsContextRequest(BaseModel):
    """Request body for POST /api/v2/pms-context.

    The `pms` field contains the full PMS Generator JSON output.
    """
    pms: dict[str, Any] = Field(
        ..., description="Full PMS Generator JSON output for one piping class"
    )
    label: str = Field(
        default="", description="Optional human-readable label for this context"
    )


class IngestPmsContextResponse(BaseModel):
    context_id: str
    class_code: str
    vds_codes: list[str]
    label: str
    message: str


class PmsContextSummary(BaseModel):
    context_id: str
    class_code: str
    base_class_code: str | None
    material_category: str
    pressure_class: str
    service: str
    vds_codes: list[str]
    label: str


# ── POST /api/v2/pms-context — Ingest PMS Generator JSON ─────────────────

@router.post("/v2/pms-context", response_model=IngestPmsContextResponse)
async def ingest_pms_context(req: IngestPmsContextRequest):
    """Validate and store PMS Generator JSON.

    Returns a context_id that can be used with GET /api/v2/datasheets/{code}.
    If a context for this class_code already exists, it is overwritten.
    """
    # Validate the PMS JSON
    try:
        pms_input = PmsGeneratorInput(**req.pms)
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid PMS Generator JSON: {str(e)[:500]}",
        )

    # If the class code normalises to a custom letter (e.g. New-spec-[A1]→Y1),
    # set base_class_code so VDS codes get rewritten (BLRTA1R→BLRTY1R)
    raw_class = pms_input.class_code or ""
    norm_class = _normalise_class_code(raw_class).upper()
    if norm_class != raw_class.upper() and pms_input.base_class_code is None:
        # The normalised code differs — store the original as base
        pms_input.base_class_code = raw_class.upper()
        pms_input.class_code = norm_class
    elif len(norm_class) >= 2 and norm_class[0] in _REVERSE_LETTER_MAP:
        if pms_input.base_class_code is None:
            _base_l = _REVERSE_LETTER_MAP[norm_class[0]]
            pms_input.base_class_code = f"{_base_l}{norm_class[1:]}"

    ctx = PmsContext(pms_input)
    class_code = _normalise_class_code(ctx.get_class_code())
    vds_codes = ctx.get_vds_codes()

    # Check if a context for this class already exists
    context_id = None
    for path in _contexts_dir().glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("class_code", "").upper() == class_code.upper():
                context_id = path.stem
                break
        except Exception:
            continue

    if context_id is None:
        context_id = str(uuid.uuid4())[:8]

    # Store
    payload = {
        "context_id": context_id,
        "class_code": class_code,
        "label": req.label or f"PMS {class_code}",
        "pms": req.pms,
    }
    path = _contexts_dir() / f"{context_id}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return IngestPmsContextResponse(
        context_id=context_id,
        class_code=class_code,
        vds_codes=vds_codes,
        label=req.label or f"PMS {class_code}",
        message=f"PMS context for {class_code} stored. "
                f"Generate datasheets via GET /api/v2/datasheets/{{vds_code}}?pms_context={context_id}",
    )


# ── GET /api/v2/pms-context — List all stored contexts ────────────────────

@router.get("/v2/pms-context")
async def list_pms_contexts():
    """List all stored PMS contexts."""
    contexts: list[dict] = []
    for path in sorted(_contexts_dir().glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            pms_input = PmsGeneratorInput(**raw["pms"])
            ctx = PmsContext(pms_input)
            contexts.append(PmsContextSummary(
                context_id=path.stem,
                class_code=ctx.get_class_code(),
                base_class_code=ctx.get_base_class_code(),
                material_category=ctx.get_material_category(),
                pressure_class=ctx.get_pressure_class_display(),
                service=ctx.get_service(),
                vds_codes=ctx.get_vds_codes(),
                label=raw.get("label", ""),
            ).model_dump())
        except Exception:
            continue
    return {"contexts": contexts, "total": len(contexts)}


# ── GET /api/v2/pms-context/{id} — Get specific context ──────────────────

@router.get("/v2/pms-context/{context_id}")
async def get_pms_context(context_id: str):
    """Get details of a stored PMS context."""
    ctx = _load_context(context_id)
    path = _contexts_dir() / f"{context_id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))

    return {
        "context_id": context_id,
        "class_code": ctx.get_class_code(),
        "base_class_code": ctx.get_base_class_code(),
        "material_category": ctx.get_material_category(),
        "pressure_class": ctx.get_pressure_class_display(),
        "pressure_class_num": ctx.get_pressure_class_num(),
        "design_pressure": ctx.get_design_pressure_display(),
        "hydrotest": ctx.get_hydrotest_display(),
        "service": ctx.get_service(),
        "is_nace": ctx.is_nace(),
        "is_low_temp": ctx.is_low_temp(),
        "bolts": ctx.get_bolts(),
        "nuts": ctx.get_nuts(),
        "gaskets": ctx.get_gaskets(),
        "body_material": ctx.get_body_material_pms(),
        "flange_face": ctx.get_flange_face_code(),
        "vds_codes": ctx.get_vds_codes(),
        "label": raw.get("label", ""),
    }


# ── GET /api/v2/datasheets/{vds_code} — Generate datasheet ───────────────

@router.get("/v2/datasheets/{vds_code}")
async def get_datasheet_v2(
    vds_code: str,
    pms_context: Optional[str] = Query(
        default=None,
        description="Context ID from POST /api/v2/pms-context. "
                    "If omitted, tries to resolve from the piping class in the VDS code.",
    ),
    include_empty: bool = False,
    chat_ui: bool = False,
):
    """Generate a valve datasheet using the v2 pipeline (PMS Generator data).

    This endpoint is COMPLETELY SEPARATE from GET /api/datasheets/{code}.
    It reads PMS data exclusively from the stored PmsContext — no global
    singletons, no pms_extracted.json, no pms_vds_datasheets.json.

    Resolution:
      1. If pms_context query param is given, load that specific context.
      2. Otherwise, decode the VDS code to get the piping class, then look
         for a stored context matching that class.
      3. If no context found, return 404.
    """
    code = vds_code.upper().strip()

    # ── Decode VDS ──
    try:
        decoded = decode_vds(code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid VDS code: {e}")

    # ── Resolve PMS context ──
    ctx: PmsContext | None = None

    if pms_context:
        ctx = _load_context(pms_context)
    else:
        # Try to find context by piping class from decoded VDS
        ctx = _load_context_by_class(decoded.piping_class)

    if ctx is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No PMS context found for VDS '{code}' "
                f"(piping class '{decoded.piping_class}'). "
                f"Ingest PMS Generator JSON first via POST /api/v2/pms-context."
            ),
        )

    # ── Verify VDS code belongs to this PMS context ──
    ctx_vds_codes = ctx.get_vds_codes()
    if ctx_vds_codes and code not in ctx_vds_codes:
        # Not a hard error — allow generation for any VDS code in the
        # class, even if not explicitly listed in the PMS valves section.
        pass

    # ── Generate datasheet ──
    try:
        data, provenance = generate_datasheet_v2(
            decoded, ctx, return_provenance=True,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Datasheet generation failed: {str(exc)[:500]}",
        )

    # ── Filter to card fields (same as v1 — strips ~73 fields down to ~40) ──
    data = filter_card_data(data, for_chat_ui=chat_ui, vds_code_for_mask=code)

    # ── Compute completeness (after filtering) ──
    total = len(data)
    filled = sum(
        1 for v in data.values()
        if v and v != "-" and str(v).strip()
    )
    completion = round((filled / total * 100) if total else 0, 1)

    # ── Build response ──
    sources = get_field_sources(data)
    sources.update(provenance)
    sources = filter_card_metadata(sources, data)

    response = DatasheetResponse(
        vds_code=code,
        datasheet=data,
        field_sources=sources,
        validation_status="complete" if completion > 90 else "partial",
        completion_pct=completion,
    ).model_dump()

    # Add v2-specific metadata
    response["pipeline"] = "v2"
    response["pms_context"] = {
        "class_code": ctx.get_class_code(),
        "base_class_code": ctx.get_base_class_code(),
        "material_category": ctx.get_material_category(),
    }

    return response


# ── POST /api/v2/datasheets/batch — Batch generate ───────────────────────

@router.post("/v2/datasheets/batch")
async def generate_batch_v2(
    vds_codes: list[str],
    pms_context: Optional[str] = Query(
        default=None,
        description="Context ID to use for all codes in the batch",
    ),
):
    """Generate datasheets for multiple VDS codes using v2 pipeline."""
    results: list[dict] = []

    for vds_code in vds_codes[:20]:  # cap at 20
        code = vds_code.upper().strip()
        try:
            decoded = decode_vds(code)
        except ValueError as e:
            results.append({
                "vds_code": code,
                "error": f"Invalid VDS code: {e}",
                "status": "error",
            })
            continue

        # Resolve context
        ctx: PmsContext | None = None
        if pms_context:
            try:
                ctx = _load_context(pms_context)
            except HTTPException:
                results.append({
                    "vds_code": code,
                    "error": f"PMS context '{pms_context}' not found",
                    "status": "error",
                })
                continue
        else:
            ctx = _load_context_by_class(decoded.piping_class)

        if ctx is None:
            results.append({
                "vds_code": code,
                "error": f"No PMS context for piping class '{decoded.piping_class}'",
                "status": "error",
            })
            continue

        try:
            data, provenance = generate_datasheet_v2(
                decoded, ctx, return_provenance=True,
            )
            # Filter to card fields (same as v1)
            data = filter_card_data(data, for_chat_ui=False, vds_code_for_mask=code)
            provenance = filter_card_metadata(provenance, data)

            total = len(data)
            filled = sum(
                1 for v in data.values()
                if v and v != "-" and str(v).strip()
            )
            completion = round((filled / total * 100) if total else 0, 1)

            results.append({
                "vds_code": code,
                "data": data,
                "field_sources": provenance,
                "completion_pct": completion,
                "status": "success",
                "source": "v2_pms_generator",
                "pms_context": {
                    "class_code": ctx.get_class_code(),
                    "material_category": ctx.get_material_category(),
                },
            })
        except Exception as exc:
            results.append({
                "vds_code": code,
                "error": str(exc)[:300],
                "status": "error",
            })

    return {"results": results, "total": len(results)}
