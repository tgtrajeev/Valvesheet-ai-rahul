"""PMS Data Loader — Singleton that loads pms_extracted.json for runtime lookups.

Provides typed access to PMS piping class data extracted from the 74 PMS sheets.
Used by pms_resolver.py and knowledge.py for PMS-driven field resolution.
"""

import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass
class PmsHeader:
    spec_code: str
    pressure_rating: str | None
    material_description: str | None
    corrosion_allowance: str | None
    design_code: str | None
    service: str | None
    nace_flag: bool
    lt_flag: bool
    design_pressure_barg: float | None
    hydrotest_pressure_barg: float | None


@dataclass
class PmsBoltingGaskets:
    spec_code: str
    stud_bolt_spec: str | None
    hex_nut_spec: str | None
    gasket_spec: str | None


@dataclass
class PmsFlange:
    spec_code: str
    size_range: str
    nps_min: float | None
    nps_max: float | None
    flange_moc: str | None
    flange_face: str | None
    flange_type: str | None


@dataclass
class PmsIndexRow:
    spec_code: str
    hydrotest_barg: float | None
    design_pressure_barg: float | None
    min_temp_c: float | None
    pt_breakpoints: list[dict]


@dataclass
class PmsSpec:
    """Complete PMS data for one piping class."""
    spec_code: str
    header: PmsHeader
    bolting_gaskets: PmsBoltingGaskets | None
    flanges: list[PmsFlange]
    index_row: PmsIndexRow | None
    valve_assignments: list[dict]
    pt_ratings: list[dict]
    nps_sizes: list[dict]


class PmsLoader:
    """Singleton loader for PMS extracted data."""

    def __init__(self, json_path: Path):
        with open(json_path, encoding="utf-8") as f:
            raw = json.load(f)

        self._specs: dict[str, PmsSpec] = {}
        for code, data in raw.items():
            self._specs[code] = self._parse_spec(code, data)

    def _parse_spec(self, code: str, data: dict) -> PmsSpec:
        hdr = data.get("header", {})
        header = PmsHeader(
            spec_code=code,
            pressure_rating=hdr.get("pressure_rating"),
            material_description=hdr.get("material_description"),
            corrosion_allowance=hdr.get("corrosion_allowance"),
            design_code=hdr.get("design_code"),
            service=hdr.get("service"),
            nace_flag=hdr.get("nace_flag", False),
            lt_flag=hdr.get("lt_flag", False),
            design_pressure_barg=hdr.get("design_pressure_barg"),
            hydrotest_pressure_barg=hdr.get("hydrotest_pressure_barg"),
        )

        bg_raw = data.get("bolting_gaskets")
        bolting = None
        if bg_raw:
            bolting = PmsBoltingGaskets(
                spec_code=code,
                stud_bolt_spec=bg_raw.get("stud_bolt_spec"),
                hex_nut_spec=bg_raw.get("hex_nut_spec"),
                gasket_spec=bg_raw.get("gasket_spec"),
            )

        flanges = []
        for fl in data.get("flanges", []):
            flanges.append(PmsFlange(
                spec_code=code,
                size_range=fl.get("size_range", "ALL"),
                nps_min=fl.get("nps_min"),
                nps_max=fl.get("nps_max"),
                flange_moc=fl.get("flange_moc"),
                flange_face=fl.get("flange_face"),
                flange_type=fl.get("flange_type"),
            ))

        idx_raw = data.get("index_row")
        index_row = None
        if idx_raw:
            index_row = PmsIndexRow(
                spec_code=code,
                hydrotest_barg=idx_raw.get("hydrotest_barg"),
                design_pressure_barg=idx_raw.get("design_pressure_barg"),
                min_temp_c=idx_raw.get("min_temp_c"),
                pt_breakpoints=idx_raw.get("pt_breakpoints", []),
            )

        return PmsSpec(
            spec_code=code,
            header=header,
            bolting_gaskets=bolting,
            flanges=flanges,
            index_row=index_row,
            valve_assignments=data.get("valve_assignments", []),
            pt_ratings=data.get("pt_ratings", []),
            nps_sizes=data.get("nps_sizes", []),
        )

    @property
    def spec_codes(self) -> list[str]:
        return sorted(self._specs.keys())

    @property
    def total_specs(self) -> int:
        return len(self._specs)

    def get_spec(self, spec_code: str) -> PmsSpec | None:
        return self._specs.get(spec_code.upper().strip())

    def get_hydrotest(self, spec_code: str) -> tuple[float | None, float | None]:
        """Return (shell_barg, closure_barg) from PMS INDEX data."""
        spec = self.get_spec(spec_code)
        if spec and spec.index_row and spec.index_row.hydrotest_barg:
            shell = round(spec.index_row.hydrotest_barg, 2)
            closure = round((shell / 1.5) * 1.1, 2)
            return shell, closure
        return None, None

    def get_gaskets(self, spec_code: str) -> str | None:
        spec = self.get_spec(spec_code)
        if spec and spec.bolting_gaskets:
            return spec.bolting_gaskets.gasket_spec
        return None

    def get_bolts(self, spec_code: str) -> str | None:
        spec = self.get_spec(spec_code)
        if spec and spec.bolting_gaskets:
            return spec.bolting_gaskets.stud_bolt_spec
        return None

    def get_nuts(self, spec_code: str) -> str | None:
        spec = self.get_spec(spec_code)
        if spec and spec.bolting_gaskets:
            return spec.bolting_gaskets.hex_nut_spec
        return None

    def get_design_pressure(self, spec_code: str) -> float | None:
        spec = self.get_spec(spec_code)
        if spec and spec.index_row:
            return spec.index_row.design_pressure_barg
        return None

    def get_flange_face(self, spec_code: str, nps: float | None = None) -> str | None:
        """Get flange face type. For 900# split specs, uses NPS to select segment."""
        spec = self.get_spec(spec_code)
        if not spec or not spec.flanges:
            return None
        if len(spec.flanges) == 1:
            return spec.flanges[0].flange_face
        # Multiple segments — match by NPS
        if nps is not None:
            for fl in spec.flanges:
                if fl.nps_min is not None and fl.nps_max is not None:
                    if fl.nps_min <= nps <= fl.nps_max:
                        return fl.flange_face
        # Default to first segment
        return spec.flanges[0].flange_face


# ── Singleton ──────────────────────────────────────────────────────────────

_loader: PmsLoader | None = None


def get_pms_loader() -> PmsLoader:
    """Get or lazily load the PMS data singleton."""
    global _loader
    if _loader is None:
        from ..config import settings
        pms_path = settings.data_dir / "pms_extracted.json"
        if not pms_path.exists():
            raise FileNotFoundError(
                f"PMS data not found at {pms_path}. "
                f"Run export_pms_json.py to generate it."
            )
        _loader = PmsLoader(pms_path)
    return _loader
