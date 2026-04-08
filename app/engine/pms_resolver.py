"""PMS Resolver — Runtime field resolution from PMS extracted data.

Pure-function resolver that replaces hardcoded dictionary lookups with actual
PMS data. Each function tries PMS data first, with graceful fallback.
"""

from .pms_loader import get_pms_loader


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
        if pms_spec:
            if key in ("hydrotest_shell", "hydrotest_closure"):
                if pms_spec.index_row and pms_spec.index_row.hydrotest_barg:
                    base_source = f"PMS {spec_code} -- INDEX sheet col AG (Hydrotest)"
            elif key == "design_pressure":
                if pms_spec.index_row and pms_spec.index_row.design_pressure_barg:
                    base_source = f"PMS {spec_code} -- INDEX sheet P-T ratings"
            elif key == "gaskets":
                if pms_spec.bolting_gaskets and pms_spec.bolting_gaskets.gasket_spec:
                    base_source = f"PMS {spec_code} -- bolting_gaskets table"
            elif key == "bolts":
                if pms_spec.bolting_gaskets and pms_spec.bolting_gaskets.stud_bolt_spec:
                    base_source = f"PMS {spec_code} -- bolting_gaskets table"
            elif key == "nuts":
                if pms_spec.bolting_gaskets and pms_spec.bolting_gaskets.hex_nut_spec:
                    base_source = f"PMS {spec_code} -- bolting_gaskets table"
            elif key == "body_material":
                base_source = f"PMS {spec_code} -- material category & valve standard"
            elif key in ("size_range", "service", "pressure_class", "sour_service"):
                base_source = f"Automated based on PMS class {spec_code}"

        sources[key] = base_source

    return sources
