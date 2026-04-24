"""Metadata endpoint — serve valve types, specs, seats from vds_rules.yaml."""

import yaml
from functools import lru_cache
from fastapi import APIRouter

from ..config import settings
from ..models.schemas import MetadataResponse
from ..engine.validator import VALID_SPEC_CODES

router = APIRouter()


@lru_cache(maxsize=1)
def _load_rules() -> dict:
    rules_path = settings.data_dir / "vds_rules.yaml"
    with open(rules_path) as f:
        return yaml.safe_load(f)


@router.get("/metadata", response_model=MetadataResponse)
async def get_metadata():
    """Return all valid options for building VDS codes."""
    rules = _load_rules()

    valve_types = [
        {"code": code, "name": info["name"], "standard": info.get("primary_standard", "")}
        for code, info in rules.get("valve_types", {}).items()
    ]

    seat_types = [
        {"code": code, "name": info["name"], "description": info.get("description", "")}
        for code, info in rules.get("seat_types", {}).items()
    ]

    end_connections = [
        {"code": code, "name": info["name"], "full_name": info.get("full_name", "")}
        for code, info in rules.get("end_connections", {}).items()
    ]

    design_codes = [
        {"code": code, "name": info["name"], "applicable_to": info.get("applicable_to", [])}
        for code, info in rules.get("valve_designs", {}).items()
    ]

    piping_specs = sorted(VALID_SPEC_CODES)

    return MetadataResponse(
        valve_types=valve_types,
        seat_types=seat_types,
        end_connections=end_connections,
        design_codes=design_codes,
        piping_specs=piping_specs,
    )
