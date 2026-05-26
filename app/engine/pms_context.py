"""PmsContext — Adapter from PMS Generator JSON to rule-engine interface.

This is the v2 pipeline's bridge between the PMS Generator's JSON output
(validated by ``pms.context_schema.PmsGeneratorInput``) and the data
contract that ``generate_v2.py`` needs to produce a complete datasheet.

It exposes the SAME data points as the existing pipeline's singletons
(``PmsLoader``, ``PmsReferenceTables``, ``GlobalVdsDatasheetLoader``) but
reads exclusively from the PMS Generator JSON — no global singletons, no
shared state, no risk of mutating the frozen pipeline.

Key design rules:
  1. **Stateless adapter** — one ``PmsContext`` per PMS Generator JSON blob.
  2. **No imports from pms_loader / pms_datasheet_loader** at module level.
     We import ``PmsHeader``, ``PmsBoltingGaskets``, etc. lazily for type
     compatibility only; never touch the global ``_loader`` singleton.
  3. Every accessor returns a concrete value or ``None``. Callers (generate_v2)
     decide how to handle ``None`` (fall back to reference tables, raise, etc.).
"""
from __future__ import annotations

import re
from typing import Optional

from ..pms.context_schema import PmsGeneratorInput


# ── Material-family string → engine category code ──────────────────────────
#
# PMS Generator's ``fitting_specs.family`` uses descriptive labels like
# "Carbon Steel", "CS NACE", "SS316L", etc. The engine expects short codes
# like "CS", "CS_NACE", "SS316L". This mapping handles the translation.
#
# The first matching rule wins (order matters for substring checks).

_FAMILY_EXACT: dict[str, str] = {
    # Exact (case-insensitive) matches checked FIRST
    "cs":                       "CS",
    "cs nace":                  "CS_NACE",
    "carbon steel":             "CS",
    "carbon steel nace":        "CS_NACE",
    "ltcs":                     "LTCS_NACE",
    "ltcs nace":                "LTCS_NACE",
    "low temperature carbon steel": "LTCS_NACE",
    "ss316l":                   "SS316L",
    "ss316l nace":              "SS316L_NACE",
    "316l":                     "SS316L",
    "stainless steel 316l":     "SS316L",
    "dss":                      "DSS",
    "duplex":                   "DSS",
    "duplex stainless steel":   "DSS",
    "sdss":                     "SDSS",
    "sdss nace":                "SDSS_NACE",
    "super duplex":             "SDSS",
    "super duplex stainless steel": "SDSS",
    "cu-ni":                    "CUNI",
    "cuni":                     "CUNI",
    "copper nickel":            "CUNI",
    "copper":                   "COPPER",
    "bronze":                   "COPPER",
    "gre":                      "GRE",
    "gre bondstrand":           "GRE_BONSTRAND",
    "cpvc":                     "CPVC",
    "galvanised":               "GALV",
    "galv":                     "GALV",
    "titanium":                 "TITANIUM",
    "tubing ss":                "TUBING_SS",
    "tubing 6mo":               "TUBING_6MO",
}

# Substring rules (checked if exact match fails)
_FAMILY_SUBSTRING: list[tuple[str, str]] = [
    ("cpvc",            "CPVC"),
    ("super duplex",    "SDSS"),
    ("sdss",            "SDSS"),
    ("duplex",          "DSS"),
    ("dss",             "DSS"),
    ("316l",            "SS316L"),
    ("316",             "SS316L"),
    ("stainless",       "SS316L"),
    ("titanium",        "TITANIUM"),
    ("cu-ni",           "CUNI"),
    ("cuni",            "CUNI"),
    ("copper nickel",   "CUNI"),
    ("copper",          "COPPER"),
    ("bronze",          "COPPER"),
    ("gre",             "GRE"),
    ("galv",            "GALV"),
    ("ltcs",            "LTCS_NACE"),
    ("low temp",        "LTCS_NACE"),
    ("carbon",          "CS"),
]


def _family_to_category(family: str, is_nace: bool) -> str:
    """Map a PMS Generator fitting_specs.family string to an engine material category."""
    key = family.strip().lower()

    # 1) Exact match
    cat = _FAMILY_EXACT.get(key)
    if cat:
        # Append _NACE suffix when appropriate
        if is_nace and cat in ("CS", "SS316L", "SDSS"):
            return f"{cat}_NACE"
        return cat

    # 2) Substring match
    for needle, cat in _FAMILY_SUBSTRING:
        if needle in key:
            if is_nace:
                # Only these categories have a _NACE variant in reference tables
                if cat in ("CS", "SS316L", "SDSS"):
                    return f"{cat}_NACE"
                if cat == "LTCS_NACE":
                    return "LTCS_NACE"
            return cat

    # 3) Fallback — treat as carbon steel
    return "CS_NACE" if is_nace else "CS"


# ── Pressure-class letter → numeric ASME class ────────────────────────────

_PRESSURE_CLASS_NUM: dict[str, int] = {
    "A": 150, "B": 300, "D": 600, "E": 900, "F": 1500, "G": 2500,
}

_NUM_TO_LETTER: dict[int, str] = {v: k for k, v in _PRESSURE_CLASS_NUM.items()}


class PmsContext:
    """Adapter that wraps a validated PmsGeneratorInput and exposes
    every data point the v2 datasheet generator needs.

    Usage::

        ctx = PmsContext(pms_input)      # pms_input: PmsGeneratorInput
        cat = ctx.get_material_category()
        bolts = ctx.get_bolts()
        ...
    """

    def __init__(self, pms: PmsGeneratorInput) -> None:
        self._pms = pms

    # ── Identity ──────────────────────────────────────────────────────────

    def get_class_code(self) -> str:
        """Piping class code this context represents (e.g. 'Y1')."""
        return self._pms.class_code

    def get_base_class_code(self) -> str | None:
        """Original class this was derived from (e.g. 'A1' when class_code='Y1')."""
        return self._pms.base_class_code

    # ── Material category ─────────────────────────────────────────────────

    def get_material_category(self) -> str:
        """Engine-standard material category code derived from fitting_specs.family."""
        family = self._pms.code_factors.fitting_specs.family
        return _family_to_category(family, self.is_nace())

    # ── NACE / low-temp flags ─────────────────────────────────────────────

    def is_nace(self) -> bool:
        return self._pms.is_nace()

    def is_low_temp(self) -> bool:
        return self._pms.is_low_temp()

    # ── Pressure class ────────────────────────────────────────────────────

    def get_pressure_class_letter(self) -> str:
        """Resolve the ASME pressure-class letter.

        For standard classes (A1, B1N) the letter is the first character.
        For custom classes (Y1) where the letter isn't in the ASME map,
        we derive it from the flange_extras rating or derived conditions.
        """
        letter = self._pms.letter.upper()
        if letter in _PRESSURE_CLASS_NUM:
            return letter

        # Custom letter — try to resolve from rating string ("150#, RF" → A)
        rating = self._pms.code_factors.flange_extras.valves.rating or ""
        m = re.search(r"(\d+)\s*#", rating)
        if m:
            num = int(m.group(1))
            return _NUM_TO_LETTER.get(num, letter)

        # Try from the flange_extras face code → pressure from PT table
        return letter

    def get_pressure_class_num(self) -> int:
        """Numeric ASME pressure class (150, 300, 600, ...).

        First tries the letter→number map, then rating string from PMS JSON.
        """
        letter = self._pms.letter.upper()
        if letter in _PRESSURE_CLASS_NUM:
            return _PRESSURE_CLASS_NUM[letter]

        # Parse from the valves.rating string (e.g. "150#, RF")
        rating = self._pms.code_factors.flange_extras.valves.rating or ""
        m = re.search(r"(\d+)\s*#", rating)
        if m:
            return int(m.group(1))

        # Fallback: extract from pressure_class if stored in derived conditions
        return 150

    def get_pressure_class_display(self) -> str:
        """Formatted pressure class string (e.g. 'ASME B16.34 Class 150').

        Uses the reference tables when the letter is standard; for custom
        classes, builds the string from the numeric value.
        """
        letter = self.get_pressure_class_letter()
        num = self.get_pressure_class_num()

        # Try the rating label from valves section first (most specific)
        rating = self._pms.code_factors.flange_extras.valves.rating
        if rating:
            # If it's just "150#, RF", convert to full ASME B16.34 label
            m = re.match(r"(\d+)\s*#", rating)
            if m:
                return f"ASME B16.34 Class {m.group(1)}"
            return rating

        # Standard letter lookup
        if letter == "T":
            return "N/A - Instrumentation Tubing Class"
        return f"ASME B16.34 Class {num}"

    # ── Design pressure ───────────────────────────────────────────────────

    def get_design_pressure_barg(self) -> float:
        """Numeric design pressure in barg."""
        return self._pms.design_conditions.design_pressure_barg

    def get_design_pressure_display(self) -> str:
        """Formatted design pressure string with P-T breakpoints.

        Format: "19.6 @ -29°C, 2.8 @ 500°C" matching existing pipeline output.
        Uses the cold point (first P-T entry) and the pressure AT the actual
        design temperature — NOT the last P-T table entry (which may extend
        beyond design temp for ASME standard tables).
        """
        design_temp = self._pms.design_conditions.design_temp_c
        pt = self._pms.pressure_temperature
        if pt and pt.temperatures_c and pt.pressures_barg:
            temps = pt.temperatures_c
            press = pt.pressures_barg
            if len(temps) >= 2 and len(press) >= 2:
                # Cold point (first entry)
                cold_p, cold_t = press[0], temps[0]

                # Hot point: find pressure at the design temperature
                hot_p = None
                for t, p in zip(temps, press):
                    if abs(t - design_temp) < 0.5:
                        hot_p = p
                        break
                if hot_p is None:
                    # Interpolate between bracketing entries
                    for i in range(len(temps) - 1):
                        if temps[i] <= design_temp <= temps[i + 1]:
                            frac = (design_temp - temps[i]) / (temps[i + 1] - temps[i])
                            hot_p = round(press[i] + frac * (press[i + 1] - press[i]), 1)
                            break
                if hot_p is None:
                    # Design temp beyond table — use last entry
                    hot_p = press[-1]

                return f"{cold_p} @ {int(cold_t)}°C, {hot_p} @ {int(design_temp)}°C"

        # Fallback: from derived_conditions
        dp = self._pms.derived_conditions.pressure.design_barg
        dt = self._pms.design_conditions.design_temp_c
        mdmt = self._pms.design_conditions.mdmt_c or -29
        return f"{dp} @ {int(mdmt)}°C, {dp} @ {int(dt)}°C"

    # ── Hydrotest ─────────────────────────────────────────────────────────

    def get_hydrotest_barg(self) -> tuple[float, float]:
        """Return (shell_test_barg, closure_test_barg).

        Shell = 1.5 × design_pressure (per ASME B16.34 / API 598).
        Closure = 1.1 × design_pressure (seat test).
        Uses derived_conditions.pressure.hydrotest_barg when available.
        """
        derived = self._pms.derived_conditions.pressure

        # Shell test — prefer pre-computed value
        shell = derived.hydrotest_barg
        if shell is None or shell == 0:
            shell = round(derived.design_barg * 1.5, 2)

        # Closure — always 1.1 × design pressure
        closure = round(derived.design_barg * 1.1, 2)

        return round(shell, 2), round(closure, 2)

    def get_hydrotest_display(self) -> tuple[str, str]:
        """Return (shell_str, closure_str) formatted as 'XX.XX barg'."""
        shell, closure = self.get_hydrotest_barg()
        return f"{shell} barg", f"{closure} barg"

    # ── Service ───────────────────────────────────────────────────────────

    def get_service(self) -> str:
        """Service description from PMS Generator (e.g. 'Hydrocarbon')."""
        return self._pms.service or ""

    # ── Bolting & gaskets ─────────────────────────────────────────────────

    def get_bolts(self) -> str | None:
        """Stud bolt specification from PMS JSON."""
        return self._pms.code_factors.flange_extras.bolting.stud

    def get_nuts(self) -> str | None:
        """Hex nut specification from PMS JSON."""
        return self._pms.code_factors.flange_extras.bolting.hex_nut

    def get_gaskets(self) -> str | None:
        """Gasket specification from PMS JSON."""
        gs = self._pms.code_factors.flange_extras.gasket
        return gs.spec if gs else None

    def get_gasket_type(self) -> str | None:
        """Gasket type (e.g. 'Spiral Wound')."""
        gs = self._pms.code_factors.flange_extras.gasket
        return gs.type if gs else None

    # ── Materials (from fitting_specs and flange_extras) ──────────────────

    def get_body_material_pms(self) -> str | None:
        """Valve body material from PMS (cast specification).

        The PMS fitting_specs.valve_body holds the CAST material spec
        (e.g. 'ASTM A 216 Gr. WCB'). fitting_specs.flange holds the
        FORGED spec (e.g. 'ASTM A 105N'). Both are relevant for
        the body_material datasheet field which typically combines them:
        'ASTM A105N (1.5" and below), ASTM A216 WCB (2" & Above)'.
        """
        fs = self._pms.code_factors.fitting_specs
        valve_body = fs.valve_body  # Cast spec
        flange = fs.flange          # Forged spec

        if flange and valve_body:
            return f'{flange} (1.5" and below), {valve_body} (2" & Above)'
        if valve_body:
            return valve_body
        if flange:
            return flange
        return None

    def get_forged_material(self) -> str | None:
        """Forged material spec (flange material) from PMS."""
        return self._pms.code_factors.fitting_specs.flange

    def get_valve_body_material(self) -> str | None:
        """Cast valve body material from PMS."""
        return self._pms.code_factors.fitting_specs.valve_body

    def get_pipe_material(self) -> str | None:
        """Pipe material spec."""
        return self._pms.code_factors.fitting_specs.pipe

    def get_fittings_material(self) -> str | None:
        """Fittings material spec."""
        return self._pms.code_factors.fitting_specs.fittings

    def get_branch_outlet_material(self) -> str | None:
        """Branch outlet material spec."""
        return self._pms.code_factors.fitting_specs.branch_outlet

    def get_valves_body_material(self) -> str | None:
        """Valve body material from the valves section (may differ from fitting_specs)."""
        return self._pms.code_factors.flange_extras.valves.body

    # ── End connections / flange ──────────────────────────────────────────

    def get_flange_face_code(self) -> str:
        """Flange face code: 'RF', 'RTJ', 'FF'."""
        return self._pms.code_factors.flange_extras.face.code

    def get_flange_face_label(self) -> str | None:
        """Flange face label (descriptive)."""
        return self._pms.code_factors.flange_extras.face.label

    def get_flange_type(self) -> str | None:
        """Flange type string (e.g. 'Weld Neck per ASME B 16.5...')."""
        ft = self._pms.code_factors.flange_extras.type
        if not ft:
            return None
        return ft.type

    def get_flange_type_compact(self) -> str | None:
        """Compact flange type (for CL 1500+ / Hub connectors)."""
        ft = self._pms.code_factors.flange_extras.type
        if not ft:
            return None
        return ft.compact

    def get_flange_std(self) -> str | None:
        """Extract the ASME flange standard from the flange type string.

        e.g. 'Weld Neck per ASME B 16.5...' → 'ASME B 16.5'
        """
        ft_str = self.get_flange_type()
        if not ft_str:
            return None
        m = re.search(r"ASME\s*B\s*16\.\d+(?:\s*Series\s*[A-Z])?", ft_str)
        return m.group(0) if m else None

    # ── Corrosion allowance ───────────────────────────────────────────────

    def get_corrosion_allowance(self) -> str | None:
        """Corrosion allowance from design conditions or PMS notes.

        Not directly present in PMS Generator JSON — derived from material
        category defaults unless overridden in project_notes.
        """
        # Check project notes for explicit CA
        for note in self._pms.project_notes:
            text = note.text.lower()
            if "corrosion" in text and "allowance" in text:
                # Extract numeric value
                m = re.search(r"(\d+(?:\.\d+)?)\s*mm", note.text)
                if m:
                    return f"{m.group(1)} mm"
                return note.text
        return None

    # ── Design temperature / MDMT ─────────────────────────────────────────

    def get_design_temp_c(self) -> float:
        """Design temperature in °C."""
        return self._pms.design_conditions.design_temp_c

    def get_mdmt_c(self) -> float:
        """Minimum Design Metal Temperature in °C."""
        return self._pms.design_conditions.mdmt_c or -29.0

    def get_min_design_temp_display(self) -> str:
        """Formatted MDMT string."""
        mdmt = self.get_mdmt_c()
        return f"{int(mdmt)}°C"

    # ── VDS codes & valve assignments ─────────────────────────────────────

    def get_vds_codes(self) -> list[str]:
        """All VDS codes from the valves section.

        When the PMS context is a custom class (e.g. Y1 derived from A1),
        the raw VDS codes in the PMS JSON still reference the base class
        (BLRTA1R). This method rewrites the piping-class portion so codes
        carry the actual class code (BLRTY1R).
        """
        raw_codes = self._pms.extract_vds_codes()
        base = self._pms.base_class_code
        actual = self._pms.class_code

        # No rewriting needed when there's no base class or they're the same
        if not base or not actual or base.upper() == actual.upper():
            return raw_codes

        # Rewrite: replace the base class code embedded in each VDS code
        # with the actual class code.  VDS format is PREFIX + SEAT + CLASS + END
        # e.g. BLRTA1R → BLR + T + A1 + R  →  BLR + T + Y1 + R
        base_upper = base.upper()
        actual_upper = actual.upper()
        rewritten: list[str] = []
        for code in raw_codes:
            upper = code.upper()
            # Find and replace the base class code within the VDS string
            idx = upper.find(base_upper)
            if idx >= 0:
                new_code = code[:idx] + actual_upper + code[idx + len(base_upper):]
                rewritten.append(new_code)
            else:
                rewritten.append(code)
        return rewritten

    def get_valve_entry(self, valve_type: str) -> Optional[tuple[str, str | None]]:
        """Get (code, description) for a valve type ('ball', 'gate', etc.).

        Returns None if the valve type is not assigned in this PMS.
        """
        valves = self._pms.code_factors.flange_extras.valves
        entry = getattr(valves, valve_type.lower(), None)
        if entry is None:
            return None
        return entry.code, entry.desc

    def get_size_range_for_vds(self, vds_code: str) -> str | None:
        """Extract size range for a specific VDS code from valve descriptions.

        Valve descriptions often embed size hints like '1/2"-2", RF' or
        '≤1.5" NPT'. When present, we parse them into a size_range string.
        """
        vds_upper = vds_code.upper().strip()
        valves = self._pms.code_factors.flange_extras.valves

        # Build a set of rewritten VDS codes from get_vds_codes() so we can
        # match the caller's (rewritten) code against the raw entry codes.
        rewritten_codes = self.get_vds_codes()
        raw_codes = self._pms.extract_vds_codes()
        # Map rewritten → raw for reverse lookup
        _rewrite_map = {rw.upper(): rc.upper() for rw, rc in zip(rewritten_codes, raw_codes)}
        # The raw code that matches the caller's (possibly rewritten) vds_code
        raw_lookup = _rewrite_map.get(vds_upper, vds_upper)

        for entry in [valves.ball, valves.gate, valves.globe,
                      valves.check, valves.butterfly, valves.needle,
                      valves.dbb]:
            if not entry or not entry.code:
                continue
            codes = [c.strip().upper() for c in entry.code.split(",")]
            if raw_lookup in codes and entry.desc:
                # Try to parse a size range from the description.
                # Descriptions look like:
                #   "Reduced bore (0.5"–24"), ..."
                #   "1/2"-2", RF"
                #   "sizes 0.5"–8""
                # Strategy: find ALL size tokens (decimal, fraction, integer)
                # followed by " and return "smallest – largest".
                _SIZE_TOK = re.compile(
                    r'(\d+(?:\.\d+)?(?:/\d+)?)\s*(?:"|″|\'\')',
                )
                sizes_raw = _SIZE_TOK.findall(entry.desc)
                if sizes_raw:
                    # Convert to float for sorting
                    def _to_float(s: str) -> float:
                        if "/" in s:
                            parts = s.split("/")
                            return float(parts[0]) / float(parts[1])
                        return float(s)
                    nums = []
                    for sr in sizes_raw:
                        try:
                            nums.append((_to_float(sr), sr))
                        except (ValueError, ZeroDivisionError):
                            continue
                    if nums:
                        nums.sort(key=lambda x: x[0])
                        lo = nums[0][1]
                        hi = nums[-1][1]
                        if lo == hi:
                            return f'{lo}"'
                        return f'{lo}" - {hi}"'
        return None

    # ── Spectacle / special fittings ──────────────────────────────────────

    def get_spectacle_spec(self) -> dict | None:
        """Spectacle blind specs if present."""
        sp = self._pms.code_factors.flange_extras.spectacle
        if not sp:
            return None
        return {
            "moc": sp.moc,
            "small_bore": sp.small_bore,
            "large_bore": sp.large_bore,
        }

    # ── Project notes ─────────────────────────────────────────────────────

    def get_project_notes(self) -> list[str]:
        """Plain text project notes."""
        return [n.text for n in self._pms.project_notes]

    def get_class_note(self) -> str | None:
        """Class-level note (e.g. 'Class A1 derived from ...')."""
        note = getattr(self._pms, "note", None)
        return note if note and str(note).strip() else None

    # ── Wall thickness (informational) ────────────────────────────────────

    def get_wall_thickness_summary(self) -> dict | None:
        """Wall thickness summary from PMS Generator (informational)."""
        wt = self._pms.wall_thickness
        if not wt or not wt.summary:
            return None
        s = wt.summary
        return {
            "min_mawp_barg": s.min_mawp_barg,
            "max_mawp_barg": s.max_mawp_barg,
            "min_margin_pct": s.min_margin_pct,
            "hydrotest_barg": s.hydrotest_barg,
            "mill_tolerance": s.mill_tolerance,
        }

    # ── Materials tab (piping components, not valve-specific) ─────────────

    def get_materials_tab(self) -> dict | None:
        """Materials tab data (small_bore / large_bore piping components)."""
        mt = self._pms.materials_tab
        if not mt:
            return None
        result: dict = {}
        for bore_name in ("small_bore", "large_bore"):
            bore = getattr(mt, bore_name, None)
            if bore:
                result[bore_name] = {
                    "range": bore.range,
                    "connection": bore.connection,
                    "schedule": bore.schedule,
                    "rows": [
                        {
                            "component": r.component,
                            "material": r.material,
                            "schedule": r.schedule,
                            "standard": r.standard,
                        }
                        for r in bore.rows
                    ],
                }
        return result or None

    # ── P-T table (for display / adequacy) ────────────────────────────────

    def get_pt_breakpoints(self) -> list[dict]:
        """Pressure-temperature breakpoints for display.

        Returns list of {temp_c: int, press_barg: float} dicts.
        """
        pt = self._pms.pressure_temperature
        if not pt or not pt.temperatures_c or not pt.pressures_barg:
            return []
        return [
            {"temp_c": t, "press_barg": p}
            for t, p in zip(pt.temperatures_c, pt.pressures_barg)
        ]

    # ── Adequacy check ────────────────────────────────────────────────────

    def is_adequate(self) -> bool | None:
        """Whether the P-T rating is adequate for design conditions."""
        if self._pms.adequacy:
            return self._pms.adequacy.adequate
        return None

    # ── Suffix / trailing ─────────────────────────────────────────────────

    def get_suffix(self) -> str:
        return self._pms.suffix

    def get_trailing(self) -> str:
        return self._pms.trailing

    # ── Raw PMS access (escape hatch for generate_v2) ─────────────────────

    @property
    def raw(self) -> PmsGeneratorInput:
        """Direct access to the underlying PmsGeneratorInput for edge cases."""
        return self._pms

    # ── String representation ─────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"PmsContext(class_code={self.get_class_code()!r}, "
            f"base={self.get_base_class_code()!r}, "
            f"cat={self.get_material_category()!r}, "
            f"nace={self.is_nace()}, "
            f"vds_codes={self.get_vds_codes()!r})"
        )
