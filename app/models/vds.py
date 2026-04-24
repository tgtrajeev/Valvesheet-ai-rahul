"""VDS data models — valve types, seat types, end connections, decoded VDS."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator
import re


class ValveType(str, Enum):
    BL = "BL"   # Ball Valve
    BF = "BF"   # Butterfly Valve
    GA = "GA"   # Gate Valve
    GL = "GL"   # Globe Valve
    CH = "CH"   # Check Valve
    DB = "DB"   # Double Block and Bleed
    NE = "NE"   # Needle Valve
    BS = "BS"   # Ball Valve SDSS (ISO 17292)

    @property
    def full_name(self) -> str:
        return {
            self.BL: "Ball Valve",
            self.BF: "Butterfly Valve",
            self.GA: "Gate Valve",
            self.GL: "Globe Valve",
            self.CH: "Check Valve",
            self.DB: "Double Block and Bleed Valve",
            self.NE: "Needle Valve",
            self.BS: "Ball Valve (SDSS, ISO 17292)",
        }[self]

    @property
    def primary_standard(self) -> str:
        return {
            self.BL: "API SPEC 6D / ISO 14313",
            self.BF: "API STD 609",
            self.GA: "API STD 602 / API STD 600",
            self.GL: "BS 1873",
            self.CH: "API STD 594 / API STD 602",
            self.DB: "API SPEC 6D",
            self.NE: "Manufacturer Standard",
            self.BS: "API SPEC 6D / ISO 17292",
        }[self]


class SeatType(str, Enum):
    PTFE = "T"
    PEEK = "P"
    METAL = "M"

    @property
    def full_name(self) -> str:
        return {"T": "PTFE", "P": "PEEK", "M": "Metal Seated"}[self.value]


class EndConnection(str, Enum):
    RF = "R"
    RTJ = "J"
    FF = "F"
    BW = "W"
    SW = "S"
    HUB = "H"
    NPT = "T"
    RTJ_NPT = "JT"

    @property
    def full_name(self) -> str:
        return {
            "R": "Raised Face", "J": "Ring Type Joint", "F": "Flat Face",
            "W": "Butt Weld", "S": "Socket Weld", "H": "Hub Connector",
            "T": "NPT Female", "JT": "RTJ with NPT Female",
        }[self.value]

    @classmethod
    def from_string(cls, value: str) -> "EndConnection":
        value = value.upper()
        if value == "JT":
            return cls.RTJ_NPT
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(f"Unknown end connection: {value}")


class DesignCode(str, Enum):
    R = "R"   # Reduced Bore
    F = "F"   # Full Bore
    M = "M"   # Metal Seated
    Y = "Y"   # Screw and Yoke
    W = "W"   # Wafer / Wedge
    P = "P"   # Piston
    S = "S"   # Swing / Slab
    D = "D"   # Dual Plate
    T = "T"   # Triple Offset
    I = "I"   # Straight Inline
    A = "A"   # Angle


class DecodedVDS(BaseModel):
    """Fully parsed VDS number."""
    raw_vds: str
    valve_type: ValveType
    design: str = ""
    seat_type: Optional[SeatType] = None
    piping_class: str
    piping_class_base: str = ""
    end_connection: EndConnection
    is_nace: bool = False
    is_low_temp: bool = False
    is_metal_seated: bool = False

    def model_post_init(self, __context) -> None:
        self.raw_vds = self.raw_vds.upper().strip()
        if not self.piping_class_base:
            inst = re.match(r"^(T\d+[A-C]?)$", self.piping_class)
            std = re.match(r"^([A-G]\d+)", self.piping_class)
            self.piping_class_base = (inst or std).group(1) if (inst or std) else self.piping_class
        if self.seat_type == SeatType.METAL:
            self.is_metal_seated = True

    @field_validator("piping_class")
    @classmethod
    def validate_piping_class(cls, v: str) -> str:
        v = v.upper().strip()
        if not re.match(r"^([A-G]\d+[LN]*|T\d+[A-C]?)$", v):
            raise ValueError(f"Invalid piping class: {v}")
        return v

    def to_dict(self) -> dict:
        return {
            "raw_vds": self.raw_vds,
            "valve_type": self.valve_type.value,
            "valve_type_name": self.valve_type.full_name,
            "design": self.design,
            "seat_type": self.seat_type.value if self.seat_type else None,
            "seat_type_name": self.seat_type.full_name if self.seat_type else None,
            "piping_class": self.piping_class,
            "piping_class_base": self.piping_class_base,
            "end_connection": self.end_connection.value,
            "end_connection_name": self.end_connection.full_name,
            "is_nace": self.is_nace,
            "is_low_temp": self.is_low_temp,
            "is_metal_seated": self.is_metal_seated,
            "primary_standard": self.valve_type.primary_standard,
        }
