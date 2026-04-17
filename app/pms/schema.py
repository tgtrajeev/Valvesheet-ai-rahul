"""Canonical Pydantic schema for project-scoped PMS data.

The core primitive is `AttributeValue` — every piping-class field is stored
as {raw, numeric, tokens, unit} so the generic query engine can filter on
typed values (numeric ranges, token membership) while preserving the exact
source string for display/audit.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class AttributeValue(BaseModel):
    """Typed attribute value. All fields except `raw` are optional."""
    raw: Optional[Union[str, float, int, bool]] = None
    numeric: Optional[float] = None
    unit: Optional[str] = None
    tokens: List[str] = Field(default_factory=list)  # normalized lowercase tokens


class ValveAssignment(BaseModel):
    valve_type: str                   # BALL, GATE, GLOBE, CHECK, BUTTERFLY, NEEDLE, DBB
    nps_min: Optional[float] = None
    nps_max: Optional[float] = None
    vds_codes: List[str] = Field(default_factory=list)
    raw_cell_value: Optional[str] = None
    notes: Optional[str] = None
    valve_standard: Optional[str] = None


class PTRating(BaseModel):
    temperature_c: float
    max_pressure_barg: float


class PipeScheduleRow(BaseModel):
    nps_inch: float
    od_mm: Optional[float] = None
    schedule_val: Optional[str] = None
    wall_thickness_mm: Optional[float] = None
    pipe_type: Optional[str] = None
    pipe_moc: Optional[str] = None
    pipe_std: Optional[str] = None
    ends: Optional[str] = None


class PipingClass(BaseModel):
    """A single piping class (e.g. B1N) within a project.

    `attributes` is the dynamic bag — any header-row key the parser/LLM
    extracts lands here as an AttributeValue. This is what the generic
    query engine filters against.
    """
    spec_code: str
    attributes: Dict[str, AttributeValue] = Field(default_factory=dict)
    pt_ratings: List[PTRating] = Field(default_factory=list)
    pipe_schedule: List[PipeScheduleRow] = Field(default_factory=list)
    valve_assignments: List[ValveAssignment] = Field(default_factory=list)
    flanges: List[Dict[str, Any]] = Field(default_factory=list)
    bolting_gaskets: Optional[Dict[str, Any]] = None
    fittings: List[Dict[str, Any]] = Field(default_factory=list)
    branch_chart: Optional[List[List[str]]] = None
    extra: Dict[str, Any] = Field(default_factory=dict)  # anything unclassified


class ProjectMetadata(BaseModel):
    project_id: str
    name: str
    source_file: Optional[str] = None
    uploaded_at: Optional[str] = None
    status: str = "draft"   # draft | approved
    notes: Optional[str] = None


class ProjectPMS(BaseModel):
    """Top-level container persisted as pms.json per project."""
    metadata: ProjectMetadata
    piping_classes: Dict[str, PipingClass] = Field(default_factory=dict)

    def class_codes(self) -> List[str]:
        return sorted(self.piping_classes.keys())


class VDSIndexEntry(BaseModel):
    vds_code: str
    piping_class: str
    valve_type: str
    nps_min: Optional[float] = None
    nps_max: Optional[float] = None


class VDSIndex(BaseModel):
    project_id: str
    entries: List[VDSIndexEntry] = Field(default_factory=list)

    def valid_codes(self) -> List[str]:
        return sorted({e.vds_code for e in self.entries})
