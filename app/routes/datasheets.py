"""Datasheets endpoint — proxy to ML predict API + local VDS index fallback."""

import httpx
from fastapi import APIRouter, HTTPException

from ..config import settings
from ..models.schemas import DatasheetResponse
from ..engine.knowledge import get_knowledge_base
from ..engine.field_sources import get_field_sources
from ..engine.pms_resolver import get_pms_field_sources

router = APIRouter()


@router.get("/datasheets/{vds_code}")
async def get_datasheet(vds_code: str, include_empty: bool = False):
    """Fetch a datasheet — tries VDS index first, then ML API."""
    code = vds_code.upper().strip()

    # Try local VDS index first (instant, 100% accurate)
    kb = get_knowledge_base()
    spec = kb.get(code)
    if spec:
        data = spec.data
        total = len(data)
        filled = sum(1 for v in data.values() if v and v != "-" and str(v).strip())
        completion = round((filled / total * 100) if total else 0, 1)
        # Use PMS-aware field sources with granular provenance
        piping_class = data.get("piping_class", "")
        sources = get_pms_field_sources(piping_class, data) if piping_class else get_field_sources(data)
        return DatasheetResponse(
            vds_code=code,
            datasheet=data,
            field_sources=sources,
            validation_status="complete" if completion > 90 else "partial",
            completion_pct=completion,
        )

    # Fall back to ML API if configured
    if not settings.ml_api_base_url or settings.ml_api_base_url == "http://localhost:8080/api":
        raise HTTPException(status_code=404, detail=f"VDS code '{code}' not found in index ({kb.total_specs} specs)")

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

    flat_data = data.get("data", {})
    total = len(flat_data)
    filled = sum(1 for v in flat_data.values() if v and v != "-")
    completion = round((filled / total * 100) if total else 0, 1)

    return DatasheetResponse(
        vds_code=code,
        datasheet=flat_data,
        field_sources=get_field_sources(flat_data),
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
        spec = kb.get(code)
        if spec:
            data = spec.data
            total = len(data)
            filled = sum(1 for v in data.values() if v and v != "-" and str(v).strip())
            completion = round((filled / total * 100) if total else 0, 1)
            piping_class = data.get("piping_class", "")
            sources = get_pms_field_sources(piping_class, data) if piping_class else get_field_sources(data)
            results.append({
                "vds_code": code,
                "data": data,
                "field_sources": sources,
                "completion_pct": completion,
                "status": "success",
                "source": "vds_index",
            })
        else:
            results.append({
                "vds_code": code,
                "error": f"Not found in VDS index ({kb.total_specs} specs)",
                "status": "error",
            })

    return {"results": results, "total": len(results)}
