"""Datasheets endpoint — proxy to ML predict API + local VDS index fallback."""

import httpx
from fastapi import APIRouter, HTTPException

from ..config import settings
from ..models.schemas import DatasheetResponse
from ..engine.knowledge import get_knowledge_base
from ..engine.field_sources import get_field_sources
from ..engine.pms_resolver import get_pms_field_sources
from ..engine.card_filter import filter_card_data, filter_card_metadata


def _overlay_pdf_provenance(vds_code: str, sources: dict[str, str], project_id: str = "pttep-sabah") -> dict[str, str]:
    """Overlay rule-based citations from API standards onto the generic source
    labels. Citations point ONLY to API/ASME/BS standards — never to the
    project's appendix datasheet (which is just a pre-filled answer sheet).
    """
    try:
        from ..engine.vds_decoder import decode_vds as _decode
        from ..engine import rule_citations as _rc
        from ..engine.rule_engine import _get_material_category as _get_cat
        decoded = _decode(vds_code)
        cat = _get_cat(decoded.piping_class)
        for k in list(sources.keys()):
            cite = _rc.get_citation(k, decoded, material_category=cat)
            formatted = _rc.format_citation(cite, brief=True)
            if formatted and "Engineering rule" not in formatted:
                sources[k] = formatted
    except Exception:
        pass
    return sources
from ..engine.rule_engine import apply_bf_vms_construction_overrides, footer_notes_as_text
from ..engine.vds_decoder import decode_vds
from ..engine.validator import raw_vds_bs_ball_prefix_retired_error

router = APIRouter()


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


def _generate_live_datasheet(code: str) -> tuple[dict, dict, dict, dict, dict, dict]:
    """Generate live values from rules + current PMS, not cached index data."""
    from ..engine.rule_engine import generate_datasheet

    decoded = decode_vds(code)
    data, provenance = generate_datasheet(decoded, return_provenance=True)
    links = data.pop("_provenance_links", {}) if isinstance(data, dict) else {}
    quotes = data.pop("_provenance_quotes", {}) if isinstance(data, dict) else {}
    source_values = data.pop("_source_values", {}) if isinstance(data, dict) else {}
    justifications = data.pop("_justifications", {}) if isinstance(data, dict) else {}
    return data, provenance, links, quotes, source_values, justifications


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
            data, provenance, links, quotes, source_values, justifications = _generate_live_datasheet(code)
        except Exception:
            try:
                from ..engine.rule_engine import generate_datasheet

                decoded = decode_vds(code)
                data = generate_datasheet(decoded, return_provenance=False)
                provenance = {}
                links = data.pop("_provenance_links", {}) if isinstance(data, dict) else {}
                quotes = data.pop("_provenance_quotes", {}) if isinstance(data, dict) else {}
                source_values = data.pop("_source_values", {}) if isinstance(data, dict) else {}
                justifications = data.pop("_justifications", {}) if isinstance(data, dict) else {}
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Could not build datasheet from current rules and PMS data; "
                        "stale VDS index snapshots are not returned. "
                        "Fix the VDS / piping-class data or retry later."
                    ),
                ) from exc
        data = filter_card_data(
            _inject_footer_notes(code, data),
            for_chat_ui=chat_ui,
            vds_code_for_mask=code,
        )
        # Use PMS-aware field sources with granular provenance
        piping_class = data.get("piping_class", "")
        sources = get_pms_field_sources(piping_class, data) if piping_class else get_field_sources(data)
        sources.update(provenance)
        sources = _overlay_pdf_provenance(code, sources)
        sources = filter_card_metadata(sources, data)
        links = filter_card_metadata(links, data)
        quotes = filter_card_metadata(quotes, data)
        source_values = filter_card_metadata(source_values, data)
        justifications = filter_card_metadata(justifications, data)
        total = len(data)
        filled = sum(1 for v in data.values() if v and v != "-" and str(v).strip())
        completion = round((filled / total * 100) if total else 0, 1)
        response = DatasheetResponse(
            vds_code=code,
            datasheet=data,
            field_sources=sources,
            validation_status="complete" if completion > 90 else "partial",
            completion_pct=completion,
        ).model_dump()
        response.update({
            "field_sources_links": links,
            "field_sources_quotes": quotes,
            "field_source_values": source_values,
            "field_justifications": justifications,
        })
        return response

    # Not in index — still prefer rules + current PMS over ML/index field blobs.
    live_tuple = None
    try:
        live_tuple = _generate_live_datasheet(code)
    except Exception:
        try:
            from ..engine.rule_engine import generate_datasheet

            decoded = decode_vds(code)
            data = generate_datasheet(decoded, return_provenance=False)
            provenance = {}
            links = data.pop("_provenance_links", {}) if isinstance(data, dict) else {}
            quotes = data.pop("_provenance_quotes", {}) if isinstance(data, dict) else {}
            source_values = data.pop("_source_values", {}) if isinstance(data, dict) else {}
            justifications = data.pop("_justifications", {}) if isinstance(data, dict) else {}
            live_tuple = (data, provenance, links, quotes, source_values, justifications)
        except Exception:
            live_tuple = None

    if live_tuple is not None:
        data, provenance, links, quotes, source_values, justifications = live_tuple
        data = filter_card_data(
            _inject_footer_notes(code, data),
            for_chat_ui=chat_ui,
            vds_code_for_mask=code,
        )
        piping_class = data.get("piping_class", "")
        sources = get_pms_field_sources(piping_class, data) if piping_class else get_field_sources(data)
        sources.update(provenance)
        sources = _overlay_pdf_provenance(code, sources)
        sources = filter_card_metadata(sources, data)
        links = filter_card_metadata(links, data)
        quotes = filter_card_metadata(quotes, data)
        source_values = filter_card_metadata(source_values, data)
        justifications = filter_card_metadata(justifications, data)
        total = len(data)
        filled = sum(1 for v in data.values() if v and v != "-" and str(v).strip())
        completion = round((filled / total * 100) if total else 0, 1)
        response = DatasheetResponse(
            vds_code=code,
            datasheet=data,
            field_sources=sources,
            validation_status="complete" if completion > 90 else "partial",
            completion_pct=completion,
        ).model_dump()
        response.update({
            "field_sources_links": links,
            "field_sources_quotes": quotes,
            "field_source_values": source_values,
            "field_justifications": justifications,
        })
        return response

    # Last resort: legacy ML predict (butterfly construction rows are repaired).
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
                data, provenance, links, quotes, source_values, justifications = _generate_live_datasheet(code)
            except Exception:
                try:
                    from ..engine.rule_engine import generate_datasheet

                    decoded = decode_vds(code)
                    data = generate_datasheet(decoded, return_provenance=False)
                    provenance = {}
                    links = data.pop("_provenance_links", {}) if isinstance(data, dict) else {}
                    quotes = data.pop("_provenance_quotes", {}) if isinstance(data, dict) else {}
                    source_values = data.pop("_source_values", {}) if isinstance(data, dict) else {}
                    justifications = data.pop("_justifications", {}) if isinstance(data, dict) else {}
                except Exception as exc:
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
            piping_class = data.get("piping_class", "")
            sources = get_pms_field_sources(piping_class, data) if piping_class else get_field_sources(data)
            sources.update(provenance)
            sources = _overlay_pdf_provenance(code, sources)
            sources = filter_card_metadata(sources, data)
            links = filter_card_metadata(links, data)
            quotes = filter_card_metadata(quotes, data)
            source_values = filter_card_metadata(source_values, data)
            justifications = filter_card_metadata(justifications, data)
            total = len(data)
            filled = sum(1 for v in data.values() if v and v != "-" and str(v).strip())
            completion = round((filled / total * 100) if total else 0, 1)
            results.append({
                "vds_code": code,
                "data": data,
                "field_sources": sources,
                "field_sources_links": links,
                "field_sources_quotes": quotes,
                "field_source_values": source_values,
                "field_justifications": justifications,
                "completion_pct": completion,
                "status": "success",
                "source": "vds_index",
            })
        else:
            live_tuple = None
            try:
                live_tuple = _generate_live_datasheet(code)
            except Exception:
                try:
                    from ..engine.rule_engine import generate_datasheet

                    decoded = decode_vds(code)
                    data = generate_datasheet(decoded, return_provenance=False)
                    provenance = {}
                    links = data.pop("_provenance_links", {}) if isinstance(data, dict) else {}
                    quotes = data.pop("_provenance_quotes", {}) if isinstance(data, dict) else {}
                    source_values = data.pop("_source_values", {}) if isinstance(data, dict) else {}
                    justifications = data.pop("_justifications", {}) if isinstance(data, dict) else {}
                    live_tuple = (data, provenance, links, quotes, source_values, justifications)
                except Exception:
                    live_tuple = None
            if live_tuple is None:
                results.append({
                    "vds_code": code,
                    "error": (
                        f"Not in VDS index ({kb.total_specs} specs) and rule engine "
                        "could not build a datasheet for this code."
                    ),
                    "status": "error",
                })
                continue
            data, provenance, links, quotes, source_values, justifications = live_tuple
            data = filter_card_data(
                _inject_footer_notes(code, data),
                for_chat_ui=False,
                vds_code_for_mask=code,
            )
            piping_class = data.get("piping_class", "")
            sources = get_pms_field_sources(piping_class, data) if piping_class else get_field_sources(data)
            sources.update(provenance)
            sources = _overlay_pdf_provenance(code, sources)
            sources = filter_card_metadata(sources, data)
            links = filter_card_metadata(links, data)
            quotes = filter_card_metadata(quotes, data)
            source_values = filter_card_metadata(source_values, data)
            justifications = filter_card_metadata(justifications, data)
            total = len(data)
            filled = sum(1 for v in data.values() if v and v != "-" and str(v).strip())
            completion = round((filled / total * 100) if total else 0, 1)
            results.append({
                "vds_code": code,
                "data": data,
                "field_sources": sources,
                "field_sources_links": links,
                "field_sources_quotes": quotes,
                "field_source_values": source_values,
                "field_justifications": justifications,
                "completion_pct": completion,
                "status": "success",
                "source": "rule_engine",
            })

    return {"results": results, "total": len(results)}
