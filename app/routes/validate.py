"""Validation endpoint — quick synchronous VDS combination check."""

from fastapi import APIRouter
from ..models.schemas import ValidateRequest, ValidationResult
from ..engine.validator import validate_combination

router = APIRouter()


@router.post("/validate", response_model=ValidationResult)
async def validate(request: ValidateRequest):
    """Validate a VDS combination and return errors/warnings/suggestions."""
    return validate_combination(
        valve_type=request.valve_type,
        seat=request.seat,
        spec=request.spec,
        end_conn=request.end_conn,
        bore=request.bore,
    )
