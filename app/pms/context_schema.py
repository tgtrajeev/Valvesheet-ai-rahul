"""Pydantic schema for PMS Generator JSON input.

Validates the JSON produced by the PMS Generator tool. This is the canonical
contract between "any PMS" and the ValveSheet engine's v2 pipeline.

The schema mirrors the exact structure the PMS Generator outputs — no
transformation is needed before validation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, model_validator


# ── Stress / Y-curve sub-models (informational, not used by VDS engine) ──

class StressTable(BaseModel):
    key: str                                       # "CS", "SS316L", etc.
    label: str
    stress_psi_by_temp_c: Dict[str, Union[int, float]]
    max_temp_c: Optional[Union[int, float]] = None
    source_pdf_page: Optional[int] = None


class YCurve(BaseModel):
    category: str
    label: str
    temperatures_c: List[Union[int, float]]
    y_values: List[float]


# ── Fitting specs (drives body_material, material_category) ──

class FittingSpecs(BaseModel):
    family: str                     # "Carbon Steel", "CS NACE", "SS316L", etc.
    pipe: Optional[str] = None
    fittings: Optional[str] = None
    flange: Optional[str] = None    # forged material (e.g. "ASTM A 105N")
    valve_body: Optional[str] = None  # cast material (e.g. "ASTM A 216 Gr. WCB")
    branch_outlet: Optional[str] = None


# ── Flange extras (drives bolting, gaskets, end connections, valve list) ──

class FlangeFace(BaseModel):
    code: str                       # "RF", "RTJ", "FF"
    label: Optional[str] = None


class FlangeType(BaseModel):
    type: Optional[str] = None      # "Weld Neck per ASME B 16.5..."
    compact: Optional[str] = None
    hub: Optional[str] = None


class BoltingSpec(BaseModel):
    stud: str
    hex_nut: str


class GasketSpec(BaseModel):
    type: Optional[str] = None      # "Spiral Wound"
    spec: str                       # full specification string


class SpectacleSpec(BaseModel):
    moc: Optional[str] = None
    small_bore: Optional[str] = None
    large_bore: Optional[str] = None


class ValveEntry(BaseModel):
    """One valve type assignment from the PMS (e.g. ball, gate, check)."""
    code: str                       # comma-separated VDS codes
    desc: Optional[str] = None      # brief description with size/material hints


class ValvesSection(BaseModel):
    rating: Optional[str] = None    # "150#, RF" or "EEMUA 20 bar, RF"
    body: Optional[str] = None      # valve body material
    ball: Optional[ValveEntry] = None
    gate: Optional[ValveEntry] = None
    globe: Optional[ValveEntry] = None
    check: Optional[ValveEntry] = None
    butterfly: Optional[ValveEntry] = None
    needle: Optional[ValveEntry] = None
    dbb: Optional[ValveEntry] = None


class FlangeExtras(BaseModel):
    face: FlangeFace
    type: Optional[FlangeType] = None
    bolting: BoltingSpec
    gasket: GasketSpec
    spectacle: Optional[SpectacleSpec] = None
    valves: ValvesSection


# ── Branch chart (informational, not used by VDS engine) ──

class BranchChart(BaseModel):
    id: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    applies_to: List[str] = Field(default_factory=list)
    legend: Optional[Dict[str, str]] = None
    nps_axis: List[Union[int, float]] = Field(default_factory=list)
    matrix: List[List[str]] = Field(default_factory=list)
    resolved_family: Optional[str] = None


# ── Code factors (top-level engineering data) ──

class StressAtCold(BaseModel):
    stress_psi: Optional[Union[int, float]] = None
    stress_mpa: Optional[float] = None
    table_used: Optional[str] = None
    table_label: Optional[str] = None
    clamped: Optional[bool] = None
    interpolated: Optional[bool] = None
    source_pdf_page: Optional[int] = None


class CodeFactors(BaseModel):
    stress_table: Optional[StressTable] = None
    y_curve: Optional[YCurve] = None
    cold_temp_c: Optional[Union[int, float]] = None
    stress_at_cold: Optional[Union[StressAtCold, Dict[str, Any]]] = None
    fitting_specs: FittingSpecs
    flange_extras: FlangeExtras
    branch_chart: Optional[Union[BranchChart, Dict[str, Any]]] = None


# ── Design conditions ──

class DesignConditions(BaseModel):
    design_pressure_barg: float
    design_temp_c: float
    mdmt_c: Optional[float] = -29.0
    joint_type: Optional[str] = "Seamless"


# ── Derived conditions (computed by PMS Generator) ──

class DerivedPressure(BaseModel):
    design_barg: float
    design_psig: Optional[float] = None
    hydrotest_barg: float
    hydrotest_psig: Optional[float] = None
    operating_estimate_barg: Optional[float] = None
    operating_estimate_psig: Optional[float] = None


class DerivedTemperature(BaseModel):
    design_c: float
    design_f: Optional[float] = None
    mdmt_c: Optional[float] = None
    mdmt_f: Optional[float] = None
    operating_estimate_c: Optional[float] = None
    operating_estimate_f: Optional[float] = None


class DerivedConditions(BaseModel):
    pressure: DerivedPressure
    temperature: Optional[DerivedTemperature] = None


# ── Pressure-Temperature rating table ──

class PTPoint(BaseModel):
    pressure_barg: float
    temperature_c: Union[int, float]


class PTDisplayColumns(BaseModel):
    cap_c: Optional[Union[int, float]] = None
    temp_labels: List[str] = Field(default_factory=list)
    temperatures_c: List[Union[int, float]] = Field(default_factory=list)
    pressures_barg: List[float] = Field(default_factory=list)


class PressureTemperatureTable(BaseModel):
    group: Optional[str] = None                # "1.1", "2.1", etc.
    cold_point: Optional[PTPoint] = None
    hottest_point: Optional[PTPoint] = None
    temperatures_c: List[Union[int, float]] = Field(default_factory=list)
    pressures_barg: List[float] = Field(default_factory=list)
    temp_labels: List[str] = Field(default_factory=list)
    hydrotest_barg: Optional[float] = None
    display_columns: Optional[PTDisplayColumns] = None


# ── Adequacy check (informational) ──

class AdequacyCheck(BaseModel):
    adequate: bool
    design_pressure_barg: Optional[float] = None
    design_temp_c: Optional[float] = None
    rated_pressure_at_design_t_barg: Optional[float] = None


# ── Wall thickness rows (informational, not used by VDS engine) ──

class WallThicknessRow(BaseModel):
    nps: str
    nps_decimal: float
    od_mm: float
    t_mm: Optional[float] = None
    d_over_6: Optional[float] = None
    validity: Optional[str] = None
    tm_mm: Optional[float] = None
    mill_tol: Optional[float] = None
    calc_thk_mm: Optional[float] = None
    sch_display: Optional[str] = None
    sel_thk_mm: Optional[float] = None
    sel_thk_mm_display: Optional[str] = None
    sch_status: Optional[str] = None
    mawp_barg: Optional[float] = None
    margin_pct: Optional[float] = None


class WallThicknessSummary(BaseModel):
    min_mawp_barg: Optional[float] = None
    max_mawp_barg: Optional[float] = None
    min_margin_pct: Optional[float] = None
    hydrotest_barg: Optional[float] = None
    total_nps_sizes: Optional[int] = None
    mill_tolerance: Optional[float] = None
    hydrotest_factor: Optional[float] = None
    operating_factor: Optional[float] = None


class WallThicknessFlag(BaseModel):
    level: str                      # "mandatory", "warning", "note"
    title: str
    body: str


class WallThickness(BaseModel):
    rows: List[WallThicknessRow] = Field(default_factory=list)
    summary: Optional[WallThicknessSummary] = None
    flags: List[WallThicknessFlag] = Field(default_factory=list)
    formula_example: Optional[Dict[str, Any]] = None
    unavailable: Optional[bool] = False
    unavailable_reason: Optional[str] = None


# ── Materials tab (piping components, not valve-specific) ──

class MaterialRow(BaseModel):
    component: str
    material: str
    schedule: Optional[str] = None
    standard: Optional[str] = None


class BoreSection(BaseModel):
    range: Optional[str] = None
    connection: Optional[str] = None
    schedule: Optional[str] = None
    rows: List[MaterialRow] = Field(default_factory=list)


class MaterialsTab(BaseModel):
    small_bore: Optional[BoreSection] = None
    large_bore: Optional[BoreSection] = None


# ── Project notes ──

class ProjectNote(BaseModel):
    id: Optional[int] = None
    text: str


# ── TOP-LEVEL PMS Generator JSON schema ──

class PmsGeneratorInput(BaseModel):
    """Complete PMS Generator output for one piping class.

    This is the contract between the PMS Generator and the ValveSheet
    v2 pipeline. Every field the VDS engine needs is extractable from
    this structure.
    """
    class_code: str                 # "Y1", "New-spec-[A1]", etc.
    letter: str                     # pressure-class letter ("A", "B", ...)
    digit: str                      # material digit ("1", "2", "10", ...)
    suffix: str = ""                # "N" (NACE), "L" (low-temp), "LN", ""
    trailing: str = ""

    service: str = ""
    note: Optional[str] = None

    base_class_code: Optional[str] = None   # original class this was derived from

    code_factors: CodeFactors

    design_conditions: DesignConditions
    effective_design_conditions: Optional[DesignConditions] = None
    derived_conditions: DerivedConditions
    pressure_temperature: Optional[PressureTemperatureTable] = None

    adequacy: Optional[AdequacyCheck] = None

    wall_thickness: Optional[WallThickness] = None
    materials_tab: Optional[MaterialsTab] = None
    project_notes: List[ProjectNote] = Field(default_factory=list)
    design_conditions_inputs: Optional[List[Dict[str, Any]]] = None

    # ── Derived helpers ──

    def extract_vds_codes(self) -> list[str]:
        """Extract all VDS codes from the valves section."""
        codes: list[str] = []
        valves = self.code_factors.flange_extras.valves
        for entry in [valves.ball, valves.gate, valves.globe,
                      valves.check, valves.butterfly, valves.needle,
                      valves.dbb]:
            if entry and entry.code:
                for c in entry.code.split(","):
                    c = c.strip()
                    if c:
                        codes.append(c)
        return codes

    def get_material_family(self) -> str:
        """Return the raw material family string from fitting_specs."""
        return self.code_factors.fitting_specs.family

    def is_nace(self) -> bool:
        return "N" in self.suffix.upper()

    def is_low_temp(self) -> bool:
        return "L" in self.suffix.upper()
