"""Override validator — checks user-requested field edits before applying.

When the agent receives an instruction like "change temperature to 180°C" on
an already-generated datasheet, it re-calls generate_datasheet with the same
vds_code and an `overrides` dict. Without validation, those overrides get
merged straight into the data dict regardless of whether the new value is
safe for the current VDS.

This module provides a single entry point — validate_overrides() — that
classifies each proposed override as:

  - safe:      apply directly
  - warning:   apply, but surface a caution
  - rejected:  do NOT apply; return reason + suggestion for the agent to
               relay to the user (e.g. "that change would require a class
               upgrade — start a new VDS if you want that")

The classification is deterministic and draws on existing validators
(validate_combination, check_seat_design_temperature) plus the PMS P-T
curves for duty checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .vds_decoder import DecodedVDS
from .pms_loader import get_pms_loader
from .pms_resolver import _interpolate_pressure, _rating_to_int
from .validator import (
    check_seat_design_temperature,
    parse_size_inches,
    validate_combination,
)


# Fields baked into the VDS code — cannot be changed via override.
# Changing any of these means the user wants a different spec; they should
# start a new conversation (or the agent should generate a new VDS code).
STRUCTURAL_FIELDS: set[str] = {
    "valve_type",
    "piping_class",
    "pressure_class",
    "seat_material",
    "body_material",
    "material",
    "design",
    "bore",
    "end_connections",
    "vds_code",
}

# Fields that require an engineering check before applying.
DUTY_FIELDS: set[str] = {"design_pressure", "design_temperature"}

# Size triggers a size-vs-valve-type re-validation.
SIZE_FIELDS: set[str] = {"size_range"}

# PMS-governed fields — validated against the class's PMS entry.
CA_FIELDS: set[str] = {"corrosion_allowance"}
SOUR_FIELDS: set[str] = {"sour_service"}
HYDROTEST_FIELDS: set[str] = {"hydrotest_shell", "hydrotest_closure"}
BOLTING_FIELDS: set[str] = {"gaskets", "bolts", "nuts"}
FIRE_FIELDS: set[str] = {"fire_rating"}
OPERATION_FIELDS: set[str] = {"operation"}


@dataclass
class OverrideDecision:
    field: str
    proposed_value: str
    current_value: str
    status: str  # "safe" | "warning" | "rejected"
    reason: str = ""
    suggestion: str = ""


@dataclass
class OverrideValidation:
    safe: dict[str, str] = field(default_factory=dict)
    decisions: list[OverrideDecision] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)


def _is_pt_envelope_string(s: str) -> bool:
    """True if the string looks like a multi-point P-T envelope rather than a
    single scalar duty.

    Index-hit datasheets store design_pressure as e.g. '51.1 @ -29°C, 39.8 @ 300°C' —
    that's the class's P-T curve, not a duty point. We detect that shape so the
    P-T duty check doesn't mistake the curve's first breakpoint for 'the duty'.
    """
    if not s:
        return False
    txt = str(s)
    has_at = "@" in txt
    comma_pts = txt.count(",")
    temp_tokens = len(re.findall(r"°?\s*[cC]\b", txt))
    return has_at and (comma_pts >= 1 or temp_tokens >= 2)


def _extract_scalar_barg(s: str | None) -> float | None:
    """Pull a single scalar duty pressure in barg out of a string.

    Returns None if the string looks like a P-T envelope (multi-point) — those
    aren't a duty point. Accepts '25', '25 barg', '25barg', '25.0 BAR'.
    """
    if not s:
        return None
    if _is_pt_envelope_string(s):
        return None
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:barg|bar)?", str(s), re.IGNORECASE)
    return float(m.group(1)) if m else None


def _extract_temp_c(s: str | None) -> float | None:
    """Pull the first temperature-in-°C number out of a string.

    Accepts '150', '150C', '150 C', '150°C', '150 deg C'. Returns None
    if no number is found. Does NOT handle °F — the UI and prompts use °C.
    """
    if not s:
        return None
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:°|deg)?\s*c", str(s), re.IGNORECASE)
    if m:
        return float(m.group(1))
    # fall back: bare number
    m = re.search(r"(-?\d+(?:\.\d+)?)", str(s))
    return float(m.group(1)) if m else None


def _pt_allowable(spec_code: str, temperature_c: float) -> float | None:
    """Allowable pressure (barg) for a piping class at temperature_c."""
    loader = get_pms_loader()
    spec = loader.get_spec(spec_code)
    if not spec or not spec.index_row:
        return None
    return _interpolate_pressure(spec.index_row.pt_breakpoints, temperature_c)


def _class_rating_int(spec_code: str) -> int | None:
    loader = get_pms_loader()
    spec = loader.get_spec(spec_code)
    if not spec:
        return None
    return _rating_to_int(spec.header.pressure_rating)


def _check_duty(
    decoded: DecodedVDS,
    data: dict,
    new_pressure: str | None,
    new_temperature: str | None,
) -> tuple[str, str]:
    """Verify the (possibly updated) duty point still fits the class's P-T curve.

    Combines the new value(s) with whatever the current datasheet already has,
    so that changing only one of {pressure, temperature} still lets us validate
    against the other. Returns ("safe"|"warning"|"rejected", reason).
    """
    # Scalar duty pressure lookup:
    #   1. from the proposed override (new_pressure arg), if present
    #   2. from the hidden _duty_pressure_barg field (preserved across edits)
    #   3. from design_pressure directly, if it's a scalar (not an envelope)
    cur_p_barg = _extract_scalar_barg(data.get("_duty_pressure_barg", ""))
    if cur_p_barg is None:
        cur_p_barg = _extract_scalar_barg(data.get("design_pressure", ""))
    cur_t_c = _extract_temp_c(data.get("design_temperature", ""))

    p_barg = _extract_scalar_barg(new_pressure) if new_pressure is not None else cur_p_barg
    t_c = _extract_temp_c(new_temperature) if new_temperature is not None else cur_t_c

    if p_barg is None or t_c is None:
        # No scalar duty point on file AND none in this edit — the class
        # envelope alone is the constraint, and the index already enforced
        # it at generation time. Nothing to check here.
        return ("safe", "")

    allowable = _pt_allowable(decoded.piping_class, t_c)
    if allowable is None:
        return (
            "warning",
            f"Temperature {t_c:g}°C is outside {decoded.piping_class}'s rated curve — "
            "cannot verify P-T envelope.",
        )

    if p_barg > allowable:
        return (
            "rejected",
            f"{p_barg:g} barg at {t_c:g}°C exceeds the {decoded.piping_class} envelope "
            f"(allowable {allowable:g} barg at {t_c:g}°C). This duty needs a higher-rated "
            f"piping class — the VDS code itself would change. Ask for a new VDS "
            f"(call resolve_class_from_duty with the new duty point).",
        )

    return ("safe", "")


def _check_seat_vs_temperature(
    decoded: DecodedVDS,
    data: dict,
    new_temperature: str,
) -> tuple[str, str]:
    """Reuse existing seat-temperature rule against the proposed new temperature."""
    seat_code = decoded.seat_type.value if decoded.seat_type else None
    if not seat_code:
        return ("safe", "")
    # check_seat_design_temperature scans for '°C' tokens in a string
    synthetic = f"{new_temperature} °C"
    errs = check_seat_design_temperature(synthetic, seat_code)
    if errs:
        return ("rejected", errs[0])
    return ("safe", "")


def _normalize_ca(s: str) -> str:
    """Normalize '3 mm' / '3mm' / '3' / '3.0 mm' to a compact form for comparison."""
    if not s:
        return ""
    m = re.search(r"(\d+(?:\.\d+)?)", str(s))
    if not m:
        return str(s).strip().lower()
    # Strip trailing zero decimal so "3.0" == "3"
    n = float(m.group(1))
    return f"{n:g}mm"


def _is_truthy(s: str) -> bool:
    return str(s).strip().lower() in {"yes", "true", "y", "1", "nace", "sour"}


def _check_corrosion_allowance(
    decoded: DecodedVDS,
    proposed: str,
) -> tuple[str, str]:
    """User can only set a CA that matches the class's PMS entry — PMS defines
    one CA per class. Changing the CA means a different piping class."""
    loader = get_pms_loader()
    spec = loader.get_spec(decoded.piping_class)
    if not spec or not spec.header or not spec.header.corrosion_allowance:
        return ("safe", "")
    want = _normalize_ca(proposed)
    have = _normalize_ca(spec.header.corrosion_allowance)
    if not want or not have:
        return ("safe", "")
    if want == have:
        return ("safe", "")
    return (
        "rejected",
        f"Corrosion allowance '{proposed}' does not match class {decoded.piping_class} "
        f"({spec.header.corrosion_allowance}). CA is fixed per class — changing it "
        f"requires a different piping class (e.g. a CA-variant spec). Start a new VDS.",
    )


def _check_sour_service(
    decoded: DecodedVDS,
    proposed: str,
) -> tuple[str, str]:
    """Setting sour_service=true requires a NACE-variant piping class
    (codes with 'N' in them: B1N, D1N, F1N, ...)."""
    if not _is_truthy(proposed):
        return ("safe", "")  # turning sour off is always fine
    if decoded.is_nace:
        return ("safe", "")
    return (
        "rejected",
        f"Sour service requires a NACE piping class (e.g. {decoded.piping_class}N). "
        f"Class {decoded.piping_class} is not NACE-qualified — generate a new VDS "
        f"with the N-variant class.",
    )


def _check_hydrotest(
    decoded: DecodedVDS,
    field_name: str,
    proposed: str,
) -> tuple[str, str]:
    """Hydrotest must be ≥ the PMS-defined value for the class (per API 598,
    typically 1.5× cold rated pressure). Editing below the code minimum is
    unsafe."""
    loader = get_pms_loader()
    spec = loader.get_spec(decoded.piping_class)
    if not spec:
        return ("safe", "")
    required = None
    if spec.index_row and spec.index_row.hydrotest_barg:
        required = float(spec.index_row.hydrotest_barg)
    elif spec.header and spec.header.hydrotest_pressure_barg:
        required = float(spec.header.hydrotest_pressure_barg)
    if required is None:
        return ("safe", "")

    proposed_barg = _extract_scalar_barg(proposed)
    if proposed_barg is None:
        return ("warning", f"Could not parse hydrotest value '{proposed}' — skipping code check.")

    if proposed_barg + 1e-6 < required:
        return (
            "rejected",
            f"{field_name}: {proposed_barg:g} barg is below the code minimum "
            f"{required:g} barg for {decoded.piping_class} (API 598: 1.5× rated). "
            f"Use ≥ {required:g} barg.",
        )
    return ("safe", "")


def _check_bolting(
    decoded: DecodedVDS,
    field_name: str,
    proposed: str,
) -> tuple[str, str]:
    """Gaskets / bolts / nuts must match the PMS spec for the class."""
    loader = get_pms_loader()
    spec = loader.get_spec(decoded.piping_class)
    if not spec or not spec.bolting_gaskets:
        return ("safe", "")
    pms_value = None
    if field_name == "gaskets":
        pms_value = spec.bolting_gaskets.gasket_spec
    elif field_name == "bolts":
        pms_value = spec.bolting_gaskets.stud_bolt_spec
    elif field_name == "nuts":
        pms_value = spec.bolting_gaskets.hex_nut_spec
    if not pms_value:
        return ("safe", "")

    if str(proposed).strip().lower() == str(pms_value).strip().lower():
        return ("safe", "")
    return (
        "rejected",
        f"{field_name.title()} '{proposed}' does not match the PMS spec for "
        f"{decoded.piping_class} ('{pms_value}'). Bolting/gasket selections are "
        f"governed by the piping class.",
    )


def _check_fire_rating(
    decoded: DecodedVDS,
    proposed: str,
) -> tuple[str, str]:
    """Soft-seated ball/gate valves require fire test certification (API 607 /
    BS EN ISO 10497). Removing fire rating on a soft seat is a warning."""
    seat_code = decoded.seat_type.value if decoded.seat_type else None
    # Soft seats: T (PTFE), L (low-friction polymer), P (polyamide/nylon variants)
    soft_seats = {"T", "L", "P"}
    if seat_code not in soft_seats:
        return ("safe", "")
    prop = str(proposed).strip().lower()
    if prop in {"", "-", "none", "no", "nr", "not required", "n/a"}:
        return (
            "warning",
            f"Seat '{seat_code}' is soft — API 607 / BS EN ISO 10497 fire test "
            f"certification is required. Removing fire rating may fail client acceptance.",
        )
    return ("safe", "")


def _check_operation(
    decoded: DecodedVDS,
    data: dict,
    proposed: str,
    concurrent_size: str | None = None,
) -> tuple[str, str]:
    """Per MY-K-20-PI-SP-0002 Clause 9: ball/gate/globe ≥ 6" at class ≥ 300
    require gear operation. Manual/lever on such valves is a warning.

    If size is being changed in the same overrides batch, use that value
    instead of the stale data size_range (which is often a full range like
    '1/2" - 24"' on index-hit sheets)."""
    prop = str(proposed).strip().lower()
    if "gear" in prop or "actuator" in prop or "motor" in prop:
        return ("safe", "")
    size_str = concurrent_size if concurrent_size else data.get("size_range", "")
    size_val = parse_size_inches(size_str)
    rating_int = _class_rating_int(decoded.piping_class)
    if size_val is None or rating_int is None:
        return ("safe", "")
    if size_val >= 6 and rating_int >= 300 and decoded.valve_type.value in ("BL", "GT", "GL"):
        return (
            "warning",
            f"Size {size_val:g}\" at class {rating_int}#: gear operation is required "
            f"per MY-K-20-PI-SP-0002 Clause 9. '{proposed}' may not meet torque limits.",
        )
    return ("safe", "")


def _check_size(
    decoded: DecodedVDS,
    new_size: str,
) -> tuple[str, str]:
    """Re-run Phase 1 combination validation with the proposed size."""
    size_val = parse_size_inches(new_size)
    if size_val is None:
        return ("warning", f"Could not parse size '{new_size}' — skipping size check.")
    seat_code = decoded.seat_type.value if decoded.seat_type else "M"
    result = validate_combination(
        valve_type=decoded.valve_type.value,
        seat=seat_code,
        spec=decoded.piping_class,
        end_conn=decoded.end_connection.value,
        bore=decoded.design if decoded.valve_type.value in ("BL", "BS") else None,
        size_inches=size_val,
    )
    if result.errors:
        return ("rejected", result.errors[0])
    if result.warnings:
        return ("warning", result.warnings[0])
    return ("safe", "")


def validate_overrides(
    decoded: DecodedVDS,
    data: dict,
    overrides: dict[str, str],
    normalize: callable,
) -> OverrideValidation:
    """Classify each proposed override as safe / warning / rejected.

    Args:
        decoded: the current VDS code, parsed.
        data: the current datasheet dict (what the override would replace).
        overrides: raw user-supplied {field_name: value} map (pre-normalization).
        normalize: the same field-name normalizer tools.py uses so aliases
            (e.g. 'size' → 'size_range', 'design_temp' → 'design_temperature')
            resolve consistently.
    """
    result = OverrideValidation()

    # Pre-extract new pressure + temperature together so the duty check sees both
    normalized: dict[str, tuple[str, str]] = {}  # canonical_key -> (original_key, value)
    for raw_key, raw_val in overrides.items():
        if raw_val is None or not str(raw_val).strip():
            continue
        canonical = normalize(raw_key)
        normalized[canonical] = (raw_key, str(raw_val).strip())

    new_pressure_val = normalized.get("design_pressure", (None, None))[1]
    new_temperature_val = normalized.get("design_temperature", (None, None))[1]
    new_size_val = normalized.get("size_range", (None, None))[1]

    for canonical, (raw_key, value) in normalized.items():
        current = str(data.get(canonical, ""))
        decision = OverrideDecision(
            field=canonical,
            proposed_value=value,
            current_value=current,
            status="safe",
        )

        if canonical in STRUCTURAL_FIELDS:
            decision.status = "rejected"
            decision.reason = (
                f"'{canonical}' is encoded in the VDS code ({_vds_str(decoded)}) and "
                f"cannot be changed via a field edit — changing it would produce a "
                f"different VDS."
            )
            decision.suggestion = (
                f"To change {canonical}, start a new spec with the target "
                f"{canonical} value so a fresh VDS code gets generated."
            )

        elif canonical in DUTY_FIELDS:
            status, reason = _check_duty(
                decoded, data, new_pressure_val, new_temperature_val
            )
            decision.status = status
            decision.reason = reason
            # Seat-vs-temp is an independent additional constraint when temp changes
            if canonical == "design_temperature" and status != "rejected":
                seat_status, seat_reason = _check_seat_vs_temperature(
                    decoded, data, value
                )
                if seat_status == "rejected":
                    decision.status = "rejected"
                    decision.reason = seat_reason

        elif canonical in SIZE_FIELDS:
            status, reason = _check_size(decoded, value)
            decision.status = status
            decision.reason = reason

        elif canonical in CA_FIELDS:
            status, reason = _check_corrosion_allowance(decoded, value)
            decision.status = status
            decision.reason = reason

        elif canonical in SOUR_FIELDS:
            status, reason = _check_sour_service(decoded, value)
            decision.status = status
            decision.reason = reason

        elif canonical in HYDROTEST_FIELDS:
            status, reason = _check_hydrotest(decoded, canonical, value)
            decision.status = status
            decision.reason = reason

        elif canonical in BOLTING_FIELDS:
            status, reason = _check_bolting(decoded, canonical, value)
            decision.status = status
            decision.reason = reason

        elif canonical in FIRE_FIELDS:
            status, reason = _check_fire_rating(decoded, value)
            decision.status = status
            decision.reason = reason

        elif canonical in OPERATION_FIELDS:
            status, reason = _check_operation(decoded, data, value, new_size_val)
            decision.status = status
            decision.reason = reason

        # else: free-form field (tag, line, project, qty, service, finish, …)
        #       → default "safe", no check.

        result.decisions.append(decision)

        if decision.status == "safe":
            result.safe[canonical] = value
        elif decision.status == "warning":
            result.safe[canonical] = value
            result.warnings.append(
                f"{canonical}: {decision.reason}" if decision.reason else canonical
            )
        else:  # rejected
            result.rejected.append({
                "field": canonical,
                "proposed_value": value,
                "current_value": current,
                "reason": decision.reason,
                "suggestion": decision.suggestion,
            })

    return result


def _vds_str(decoded: DecodedVDS) -> str:
    """Best-effort reconstruction of the VDS code string for error messages."""
    parts = [decoded.valve_type.value]
    if decoded.design:
        parts.append(decoded.design)
    if decoded.seat_type:
        parts.append(decoded.seat_type.value)
    parts.append(decoded.piping_class)
    parts.append(decoded.end_connection.value)
    return "".join(parts)
