"""Datasheets endpoint — proxy to ML predict API + local VDS index fallback."""

import httpx
from fastapi import APIRouter, HTTPException

from ..config import settings
from ..models.schemas import DatasheetResponse
from ..engine.knowledge import get_knowledge_base
from ..engine.field_sources import get_field_sources
from ..engine.pms_resolver import get_pms_field_sources
from ..engine.card_filter import filter_card_data, filter_card_metadata
from ..engine.rule_engine import apply_bf_vms_construction_overrides, footer_notes_as_text
from ..engine.vds_decoder import decode_vds
from ..engine.validator import raw_vds_bs_ball_prefix_retired_error

router = APIRouter()


def _generate_live_datasheet(code: str) -> dict:
    """Build datasheet from rules + current PMS — never use cached index field values."""
    from ..engine.rule_engine import generate_datasheet

    decoded = decode_vds(code)
    return generate_datasheet(decoded)


def _inject_footer_notes(code: str, data: dict) -> dict:
    """Add standard datasheet_notes field if the record doesn't already carry one."""
    if data.get("datasheet_notes"):
        return data
    try:
        decoded = decode_vds(code)
        data = dict(data)
        data["datasheet_notes"] = footer_notes_as_text(
            decoded.valve_type.value, decoded.is_nace
        )
    except Exception:
        pass
    return data


@router.get("/datasheets/{vds_code}")
async def get_datasheet(
    vds_code: str,
    include_empty: bool = False,
    chat_ui: bool = False,
):
    """Fetch a datasheet — rule engine + PMS first; ML predict only as last resort."""
    code = vds_code.upper().strip()
    _bs_err = raw_vds_bs_ball_prefix_retired_error(code)
    if _bs_err:
        raise HTTPException(status_code=400, detail=_bs_err)

    # Try local VDS index first (instant, 100% accurate)
    kb = get_knowledge_base()
    spec = kb.get(code)
    if spec:
        try:
            data = _generate_live_datasheet(code)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Could not build datasheet from current rules and PMS data; "
                    "stale VDS index snapshots are not returned."
                ),
            ) from exc
        data = filter_card_data(
            _inject_footer_notes(code, data),
            for_chat_ui=chat_ui,
            vds_code_for_mask=code,
        )
        total = len(data)
        filled = sum(1 for v in data.values() if v and v != "-" and str(v).strip())
        completion = round((filled / total * 100) if total else 0, 1)
        # Use PMS-aware field sources with granular provenance
        piping_class = data.get("piping_class", "")
        sources = get_pms_field_sources(piping_class, data) if piping_class else get_field_sources(data)
        sources = filter_card_metadata(sources, data)
        return DatasheetResponse(
            vds_code=code,
            datasheet=data,
            field_sources=sources,
            validation_status="complete" if completion > 90 else "partial",
            completion_pct=completion,
        )

    # Prefer rule engine + PMS for any decodable VDS (do not trust ML/index snapshots).
    try:
        data = _generate_live_datasheet(code)
    except Exception:
        data = None
    if data is not None:
        data = filter_card_data(
            _inject_footer_notes(code, data),
            for_chat_ui=chat_ui,
            vds_code_for_mask=code,
        )
        total = len(data)
        filled = sum(1 for v in data.values() if v and v != "-" and str(v).strip())
        completion = round((filled / total * 100) if total else 0, 1)
        piping_class = data.get("piping_class", "")
        sources = get_pms_field_sources(piping_class, data) if piping_class else get_field_sources(data)
        sources = filter_card_metadata(sources, data)
        return DatasheetResponse(
            vds_code=code,
            datasheet=data,
            field_sources=sources,
            validation_status="complete" if completion > 90 else "partial",
            completion_pct=completion,
        )

    # Last resort: legacy ML predict (may carry stale construction text; butterfly is repaired below).
    if not settings.ml_api_base_url or settings.ml_api_base_url == "http://localhost:8080/api":
        raise HTTPException(
            status_code=404,
            detail=(
                f"VDS code '{code}' not in index ({kb.total_specs} specs) and "
                "could not be generated from rules / PMS."
            ),
        )

    url = f"{settings.ml_api_base_url}/ml/predict/{code}/flat"
    params = {"include_empty": str(include_empty).lower()}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text[:500])
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="ML API service unavailable")

    payload = data.get("data", {})
    if isinstance(payload, dict):
        try:
            if decode_vds(code).valve_type.value == "BF":
                apply_bf_vms_construction_overrides(payload)
        except Exception:
            pass

    flat_data = filter_card_data(
        payload,
        for_chat_ui=chat_ui,
        vds_code_for_mask=code,
    )
    total = len(flat_data)
    filled = sum(1 for v in flat_data.values() if v and v != "-")
    completion = round((filled / total * 100) if total else 0, 1)

    return DatasheetResponse(
        vds_code=code,
        datasheet=flat_data,
        field_sources=filter_card_metadata(get_field_sources(flat_data), flat_data),
        validation_status="complete" if completion > 90 else "partial",
        completion_pct=completion,
    )


@router.post("/datasheets/batch")
async def generate_batch(vds_codes: list[str]):
    """Generate datasheets for multiple VDS codes."""
    kb = get_knowledge_base()
    results = []

    for code in vds_codes[:20]:  # cap at 20
        code = code.upper().strip()
        _bs_err = raw_vds_bs_ball_prefix_retired_error(code)
        if _bs_err:
            results.append({"vds_code": code, "error": _bs_err, "status": "error"})
            continue
        spec = kb.get(code)
        if spec:
            try:
                data = _generate_live_datasheet(code)
            except Exception:
                results.append({
                    "vds_code": code,
                    "error": (
                        "Could not build datasheet from current rules and PMS data; "
                        "stale index snapshots are not used."
                    ),
                    "status": "error",
                })
                continue
            data = filter_card_data(
                _inject_footer_notes(code, data),
                for_chat_ui=False,
                vds_code_for_mask=code,
            )
            total = len(data)
            filled = sum(1 for v in data.values() if v and v != "-" and str(v).strip())
            completion = round((filled / total * 100) if total else 0, 1)
            piping_class = data.get("piping_class", "")
            sources = get_pms_field_sources(piping_class, data) if piping_class else get_field_sources(data)
            sources = filter_card_metadata(sources, data)
            results.append({
                "vds_code": code,
                "data": data,
                "field_sources": sources,
                "completion_pct": completion,
                "status": "success",
                "source": "vds_index",
            })
        else:
            try:
                data = _generate_live_datasheet(code)
            except Exception:
                results.append({
                    "vds_code": code,
                    "error": (
                        f"Not in VDS index ({kb.total_specs} specs) and rule engine "
                        "could not build a datasheet for this code."
                    ),
                    "status": "error",
                })
                continue
            data = filter_card_data(
                _inject_footer_notes(code, data),
                for_chat_ui=False,
                vds_code_for_mask=code,
            )
            total = len(data)
            filled = sum(1 for v in data.values() if v and v != "-" and str(v).strip())
            completion = round((filled / total * 100) if total else 0, 1)
            piping_class = data.get("piping_class", "")
            sources = get_pms_field_sources(piping_class, data) if piping_class else get_field_sources(data)
            sources = filter_card_metadata(sources, data)
            results.append({
                "vds_code": code,
                "data": data,
                "field_sources": sources,
                "completion_pct": completion,
                "status": "success",
                "source": "rule_engine",
            })

    return {"results": results, "total": len(results)}
