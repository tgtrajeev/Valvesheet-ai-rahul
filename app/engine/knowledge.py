"""Piping knowledge base — loads VDS index and provides natural-language search.

This is the brain of the agent. It indexes 679 valve specs from the VDS index
and lets users search by any combination of:
  - valve type ("ball", "gate", "check")
  - material ("carbon steel", "stainless", "duplex")
  - service ("hydrocarbon", "seawater", "sour")
  - pressure class ("150", "300", "900")
  - size ("2 inch", "1/2 to 8")
  - piping class ("A1", "B1N")
  - NACE / low-temp requirements
"""

import json
import re
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass, field

# ── Piping class knowledge (embedded, not loaded from file) ───────────────────

PRESSURE_CLASS_MAP = {
    "A": {"class": 150, "label": "ASME B16.34 Class 150", "max_nps": 24},
    "B": {"class": 300, "label": "ASME B16.34 Class 300", "max_nps": 24},
    "D": {"class": 600, "label": "ASME B16.34 Class 600", "max_nps": 24},
    "E": {"class": 900, "label": "ASME B16.34 Class 900", "max_nps": 24},
    "F": {"class": 1500, "label": "ASME B16.34 Class 1500", "max_nps": 16},
    "G": {"class": 2500, "label": "ASME B16.34 Class 2500", "max_nps": 12},
    "T": {"class": 0, "label": "Instrumentation Tubing", "max_nps": 2},
}

# Piping class number → material family
MATERIAL_FAMILY_MAP = {
    1: "CS",       # Carbon Steel
    2: "CS",       # Carbon Steel (variant)
    3: "GALV",     # Galvanized (SS valve body)
    4: "GALV",     # Galvanized (SS valve body)
    5: "GALV",     # Galvanized
    6: "GALV",     # Galvanized
    10: "SS316L",  # Stainless Steel 316L
    20: "DSS",     # Duplex Stainless Steel
    25: "SDSS",    # Super Duplex SS
    30: "CUNI",    # 90/10 Cu-Ni
    31: "COPPER",  # Bronze
    40: "GRE",     # Glass Reinforced Epoxy
    41: "GRE",     # GRE Bonstrand
    42: "CPVC",    # Chlorinated PVC
}

MATERIAL_DESCRIPTIONS = {
    "CS": "Carbon Steel (ASTM A216 WCB / A105N)",
    "CS_NACE": "Carbon Steel NACE (ASTM A216 WCB / A105N, NACE MR0175)",
    "LTCS_NACE": "Low-Temp Carbon Steel (ASTM A350 LF2, -45C, NACE)",
    "SS316L": "Stainless Steel 316L (ASTM A351 CF3M / A182 F316L)",
    "DSS": "Duplex SS UNS S31803 (ASTM A182 F51, NACE)",
    "SDSS": "Super Duplex SS UNS S32750 (ASTM A182 F53)",
    "GALV": "Carbon Steel Hot-Dip Galvanized (ASTM A123/A153)",
    "CUNI": "90/10 Cu-Ni Alloy UNS C70600 (EEMUA 234)",
    "COPPER": "Bronze ASTM B61 UNS C92200",
    "GRE": "NAB body (Nickel Aluminium Bronze) for GRE piping",
    "CPVC": "NAB body for CPVC piping",
    "TUBING_SS": "SS 316/316L for instrumentation",
    "TUBING_6MO": "6Mo UNS S31254 for instrumentation",
}

# Valve type keyword mapping (natural language → VDS index valve_type patterns)
VALVE_TYPE_KEYWORDS = {
    "ball": ["Ball Valve"],
    "gate": ["Gate valve", "Gate Valve"],
    "globe": ["Globe valve", "Globe Valve"],
    "check": ["Check Valve"],
    "butterfly": ["Butterfly Valve", "Butterfly"],
    "needle": ["Needle Valve", "Needle"],
    "dbb": ["Double Block", "DBB"],
    "double block": ["Double Block", "DBB"],
    "plug": ["Plug Valve"],
}

# Service keyword mapping
SERVICE_KEYWORDS = {
    "hydrocarbon": ["HC", "Hydrocarbon"],
    "hc": ["HC"],
    "seawater": ["Seawater", "Sea Water"],
    "cooling water": ["Cooling Water"],
    "cooling": ["Cooling Water"],
    "steam": ["Steam"],
    "diesel": ["Diesel"],
    "nitrogen": ["Nitrogen"],
    "firewater": ["Firewater", "Fire Water"],
    "sour": ["sour", "H2S", "NACE"],
    "water injection": ["WI", "Water Injection"],
    "hydraulic": ["Hydraulic"],
    "fuel oil": ["Fuel Oil"],
    "fresh water": ["Fresh Water"],
    "instrument": ["Instrument", "Tubing"],
}


@dataclass
class ValveSpec:
    """A single valve specification from the VDS index."""
    vds_code: str
    data: dict[str, str]

    @property
    def valve_type(self) -> str:
        return self.data.get("valve_type", "")

    @property
    def piping_class(self) -> str:
        return self.data.get("piping_class", "")

    @property
    def service(self) -> str:
        return self.data.get("service", "")

    @property
    def pressure_class(self) -> str:
        return self.data.get("pressure_class", "")

    @property
    def size_range(self) -> str:
        return self.data.get("size_range", "")

    @property
    def body_material(self) -> str:
        return self.data.get("body_material", "")

    @property
    def sour_service(self) -> str:
        return self.data.get("sour_service", "")

    def matches_valve_type(self, query: str) -> bool:
        q = query.lower().strip()
        for kw, patterns in VALVE_TYPE_KEYWORDS.items():
            if kw in q:
                return any(p.lower() in self.valve_type.lower() for p in patterns)
        return False

    def matches_service(self, query: str) -> bool:
        q = query.lower().strip()
        svc = self.service.lower()
        for kw, patterns in SERVICE_KEYWORDS.items():
            if kw in q:
                return any(p.lower() in svc for p in patterns)
        # Direct substring match
        return q in svc

    def matches_material(self, query: str) -> bool:
        q = query.lower().strip()
        mat = self.body_material.lower()
        if "carbon" in q or "cs" == q:
            return "carbon steel" in mat
        if "stainless" in q or "ss" in q or "316" in q:
            return "316" in mat or "stainless" in mat
        if "duplex" in q and "super" not in q:
            return "duplex" in mat and "super" not in mat
        if "super duplex" in q or "sdss" in q:
            return "super duplex" in mat
        if "bronze" in q or "copper" in q:
            return "bronze" in mat or "copper" in mat or "cu-ni" in mat
        if "inconel" in q or "alloy" in q:
            return "inconel" in mat or "alloy" in mat
        return q in mat

    def summary(self) -> str:
        """One-line human-readable summary."""
        return (
            f"{self.vds_code} — {self.valve_type} | "
            f"Class: {self.piping_class} | "
            f"Material: {self.body_material[:50]} | "
            f"Size: {self.size_range} | "
            f"Ends: {self.data.get('end_connections', '')}"
        )


class KnowledgeBase:
    """In-memory searchable index of all valve specs."""

    def __init__(self, index_path: Path):
        with open(index_path, encoding="utf-8") as f:
            raw = json.load(f)
        self.specs: dict[str, ValveSpec] = {
            code: ValveSpec(vds_code=code, data=data)
            for code, data in raw.items()
        }
        self._piping_classes = sorted(set(s.piping_class for s in self.specs.values()))

    @property
    def total_specs(self) -> int:
        return len(self.specs)

    @property
    def piping_classes(self) -> list[str]:
        return self._piping_classes

    def get(self, vds_code: str) -> ValveSpec | None:
        return self.specs.get(vds_code.upper().strip())

    def search(
        self,
        valve_type: str | None = None,
        piping_class: str | None = None,
        material: str | None = None,
        service: str | None = None,
        pressure_class: int | None = None,
        size: str | None = None,
        nace: bool | None = None,
        low_temp: bool | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> list[ValveSpec]:
        """Search specs by any combination of parameters.

        All filters are AND-ed together. Returns up to `limit` matches.
        """
        results = list(self.specs.values())

        if valve_type:
            results = [s for s in results if s.matches_valve_type(valve_type)]

        if piping_class:
            pc = piping_class.upper().strip()
            results = [s for s in results if s.piping_class.upper() == pc]

        if material:
            results = [s for s in results if s.matches_material(material)]

        if service:
            results = [s for s in results if s.matches_service(service)]

        if pressure_class:
            label = f"Class {pressure_class}"
            results = [s for s in results if label in s.pressure_class]

        if size:
            # Parse size like "2", "2 inch", "1/2" from query
            size_val = _parse_size(size)
            if size_val is not None:
                results = [s for s in results if _size_in_range(size_val, s.size_range)]

        if nace is True:
            results = [s for s in results if s.sour_service and s.sour_service != "-"]

        if low_temp is True:
            # Low temp specs have L in piping class or mention -45/-46 in design
            results = [s for s in results if "L" in s.piping_class.upper()
                        or "-45" in s.data.get("design_pressure", "")
                        or "-46" in s.data.get("design_pressure", "")]

        if query:
            # Free-text search across all fields
            q = query.lower()
            results = [s for s in results
                       if any(q in str(v).lower() for v in s.data.values())]

        return results[:limit]

    def get_piping_class_info(self, piping_class: str) -> dict:
        """Get comprehensive info about a piping class.

        Uses PMS extracted data for authoritative values (hydrotest, gaskets,
        bolts, nuts, design pressure) and falls back to VDS index samples.
        """
        pc = piping_class.upper().strip()
        specs = [s for s in self.specs.values() if s.piping_class.upper() == pc]

        if not specs:
            return {"error": f"No valves found for piping class '{pc}'"}

        # Extract info from first spec
        sample = specs[0]
        letter = pc[0] if pc else ""
        pressure_info = PRESSURE_CLASS_MAP.get(letter, {})

        # Collect all valve types and services for this class
        valve_types = sorted(set(s.valve_type for s in specs))
        services = sample.service

        # Determine material family
        num_match = re.search(r"\d+", pc)
        num = int(num_match.group()) if num_match else 1
        family = MATERIAL_FAMILY_MAP.get(num, "CS")
        is_nace = "N" in pc
        is_low_temp = "L" in pc
        if is_low_temp and is_nace:
            family = "LTCS_NACE"
        elif is_nace and family == "CS":
            family = "CS_NACE"

        result = {
            "piping_class": pc,
            "pressure_class": pressure_info.get("label", "Unknown"),
            "pressure_rating": pressure_info.get("class", 0),
            "max_nps": pressure_info.get("max_nps", 24),
            "material_family": family,
            "material_description": MATERIAL_DESCRIPTIONS.get(family, family),
            "body_material": sample.body_material,
            "design_pressure": sample.data.get("design_pressure", ""),
            "corrosion_allowance": sample.data.get("corrosion_allowance", ""),
            "is_nace": is_nace,
            "is_low_temp": is_low_temp,
            "services": services,
            "available_valve_types": valve_types,
            "total_valves": len(specs),
            "size_range": sample.size_range,
            "gaskets": sample.data.get("gaskets", ""),
            "bolts": sample.data.get("bolts", ""),
            "nuts": sample.data.get("nuts", ""),
        }

        # Enrich with PMS extracted data if available
        try:
            from .pms_loader import get_pms_loader
            pms = get_pms_loader()
            pms_spec = pms.get_spec(pc)
            if pms_spec:
                # Hydrotest from PMS INDEX (authoritative)
                if pms_spec.index_row and pms_spec.index_row.hydrotest_barg:
                    shell = round(pms_spec.index_row.hydrotest_barg, 2)
                    closure = round((shell / 1.5) * 1.1, 2)
                    result["hydrotest_shell"] = f"{shell} barg"
                    result["hydrotest_closure"] = f"{closure} barg"
                # Design pressure from INDEX
                if pms_spec.index_row and pms_spec.index_row.design_pressure_barg:
                    result["design_pressure_barg"] = pms_spec.index_row.design_pressure_barg
                # PT breakpoints
                if pms_spec.index_row and pms_spec.index_row.pt_breakpoints:
                    result["pt_breakpoints"] = pms_spec.index_row.pt_breakpoints
                # Flange info
                if pms_spec.flanges:
                    faces = [f.flange_face for f in pms_spec.flanges if f.flange_face]
                    if faces:
                        result["flange_face"] = faces[0]
                    mocs = [f.flange_moc for f in pms_spec.flanges if f.flange_moc]
                    if mocs:
                        result["flange_moc"] = mocs[0]
                    types = [f.flange_type for f in pms_spec.flanges if f.flange_type]
                    if types:
                        result["flange_type"] = types[0]
                result["pms_data_available"] = True
        except (FileNotFoundError, Exception):
            result["pms_data_available"] = False

        return result

    def list_piping_classes_for_requirements(
        self,
        material: str | None = None,
        pressure_min: int | None = None,
        nace: bool = False,
        low_temp: bool = False,
    ) -> list[dict]:
        """Find piping classes that match given requirements."""
        results = []
        seen = set()

        for spec in self.specs.values():
            pc = spec.piping_class.upper()
            if pc in seen:
                continue

            # Check NACE
            if nace and "N" not in pc:
                continue
            # Check low temp
            if low_temp and "L" not in pc:
                continue
            # Check material
            if material and not spec.matches_material(material):
                continue
            # Check pressure
            if pressure_min:
                letter = pc[0] if pc else ""
                info = PRESSURE_CLASS_MAP.get(letter, {})
                if info.get("class", 0) < pressure_min:
                    continue

            seen.add(pc)
            results.append({
                "piping_class": pc,
                "pressure_class": spec.pressure_class,
                "body_material": spec.body_material[:60],
                "size_range": spec.size_range,
                "services": spec.service[:80] + "..." if len(spec.service) > 80 else spec.service,
            })

        return sorted(results, key=lambda x: x["piping_class"])


def _parse_size(s: str) -> float | None:
    """Parse a size string like '2', '2 inch', '1/2', '1-1/2' to a float in inches."""
    s = s.strip().lower().replace('"', '').replace('inch', '').replace('in', '').strip()
    # Handle mixed fractions like "1-1/2"
    m = re.match(r"(\d+)-(\d+)/(\d+)", s)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    # Handle plain fractions like "1/2"
    m = re.match(r"(\d+)/(\d+)", s)
    if m:
        return int(m.group(1)) / int(m.group(2))
    # Handle integers/floats
    try:
        return float(s)
    except ValueError:
        return None


def _size_in_range(size: float, range_str: str) -> bool:
    """Check if a size falls within a range like '1/2" - 36"'."""
    m = re.match(r'([\d/\-]+)"\s*-\s*([\d/\-]+)"', range_str.replace(" ", ""))
    if not m:
        return True  # can't parse, don't filter
    lo = _parse_size(m.group(1))
    hi = _parse_size(m.group(2))
    if lo is None or hi is None:
        return True
    return lo <= size <= hi


# ── Singleton loader ──────────────────────────────────────────────────────────

_kb: KnowledgeBase | None = None


def get_knowledge_base() -> KnowledgeBase:
    """Get or lazily load the knowledge base singleton."""
    global _kb
    if _kb is None:
        from ..config import settings
        index_path = settings.data_dir / "all_valve_vds_index.json"
        if not index_path.exists():
            raise FileNotFoundError(
                f"VDS index not found at {index_path}. "
                f"Ensure all_valve_vds_index.json is in the app/data/ directory."
            )
        _kb = KnowledgeBase(index_path)
    return _kb
