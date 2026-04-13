"""Valve datasheet data models."""

from typing import Optional
from pydantic import BaseModel, Field


class DatasheetField(BaseModel):
    """A single field in the datasheet."""
    name: str
    display_name: str
    value: Optional[str] = None
    section: str = ""
    source: str = ""  # VDS, PMS, VDS_INDEX, STANDARDS, CALCULATED, FIXED
    confidence: float = 1.0
    notes: str = ""


class DatasheetSection(BaseModel):
    """A section of the datasheet (Header, Design, Material, etc.)."""
    name: str
    fields: list[DatasheetField] = []


class ValveDatasheet(BaseModel):
    """Complete valve datasheet."""
    vds_code: str
    valve_type: str
    valve_type_name: str = ""
    piping_class: str = ""
    seat_type: str = ""
    end_connection: str = ""
    design: str = ""
    sections: list[DatasheetSection] = []
    validation_status: str = "pending"  # valid, invalid, pending
    validation_errors: list[str] = []
    validation_warnings: list[str] = []
    completion_pct: float = 0.0

    def to_flat_dict(self) -> dict:
        """Flatten all fields into {field_name: value}."""
        flat = {
            "vds_code": self.vds_code,
            "valve_type": self.valve_type,
            "valve_type_name": self.valve_type_name,
            "piping_class": self.piping_class,
            "seat_type": self.seat_type,
            "end_connection": self.end_connection,
            "validation_status": self.validation_status,
            "completion_pct": self.completion_pct,
        }
        for section in self.sections:
            for field in section.fields:
                flat[field.name] = field.value
        return flat
