"""vds_config.py — per-project VDS code structure configuration.

Different clients use different VDS prefix conventions. PTTEP Sabah uses
BL/GA/CH/etc.; another client might use BV (ball valve) or KD (knife gate).
This module supplies the default convention AND loads per-project overrides
from `app/data/projects/<project_id>/vds_config.json`, so adding a new
client's naming scheme is data, not code.

Schema of the per-project JSON file:

    {
      "valve_type_prefixes": {
        "BV": {"engine_type": "BL", "name": "Ball Valve", "designs": ["R","F","M"], "default_design": "R"},
        "KG": {"engine_type": "GA", "name": "Knife Gate Valve", "designs": ["W"], "default_design": "W"},
        ...
      },
      "seat_chars": ["T", "P", "M"],
      "end_chars":  ["R", "J", "F", "T", "W", "H"],
      "double_char_ends": ["JT"]
    }

`engine_type` is the canonical 2-char type that the rest of the engine works
with (BL, BF, GA, GL, CH, DB, NE). The two-letter ``BS`` ball prefix is accepted
for decoding but maps to engine type ``BL``. The decoder translates the project
prefix to the engine type so all downstream rules continue to work.
"""
from __future__ import annotations

import json
from pathlib import Path

# ── Default config (matches the codebase's current PTTEP-style behavior) ──

DEFAULT_CONFIG = {
    "valve_type_prefixes": {
        "BL": {"engine_type": "BL", "name": "Ball Valve",                  "designs": ["R","F","M"], "default_design": "R"},
        # "BS" is a legacy client prefix for ball valves; engine type is always BL.
        # SDSS / material variants are carried by the piping class (e.g. F25, B25N), not valve_type.
        "BS": {"engine_type": "BL", "name": "Ball Valve (BS prefix → BL)", "designs": ["R","F","M"], "default_design": "R"},
        "BF": {"engine_type": "BF", "name": "Butterfly Valve",             "designs": ["W","T","P","D"], "default_design": "W"},
        "GA": {"engine_type": "GA", "name": "Gate Valve",                  "designs": ["Y","W","S"],   "default_design": "Y"},
        "GL": {"engine_type": "GL", "name": "Globe Valve",                 "designs": ["Y","S"],       "default_design": "Y"},
        "CH": {"engine_type": "CH", "name": "Check Valve",                 "designs": ["P","S","D","W"], "default_design": "S"},
        "DB": {"engine_type": "DB", "name": "Double Block and Bleed",      "designs": ["R","F","P","M"], "default_design": "R"},
        "NE": {"engine_type": "NE", "name": "Needle Valve",                "designs": ["I","A"],       "default_design": "I"},
    },
    "seat_chars": ["T", "P", "M"],
    "end_chars":  ["R", "J", "F", "T", "W", "H"],
    # Two-char end codes — tried before single-char so e.g. `BLFA40FF` parses
    # as piping_class='A40' end='FF' rather than collapsing to class='A40F' end='F'.
    "double_char_ends": ["JT", "FF"],
    "legacy_3char_prefixes": {
        # Backward-compat for old 3-char codes (BSF=Ball Full, GAW=Gate Wedge…)
        "BSF": ("BL", "F"),  "BSR": ("BL", "R"),
        "GAW": ("GA", "W"),  "GLS": ("GL", "Y"),
        "CHP": ("CH", "P"),  "CSW": ("CH", "S"),  "CDP": ("CH", "D"),
        "BFD": ("BF", "W"),  "DSR": ("DB", "R"),  "DSF": ("DB", "F"),
        "NEE": ("NE", "I"),
    },
    "legacy_2char_prefixes": {
        "BS": ("BL", "F"),  "GS": ("GA", "Y"),  "CS": ("CH", "S"),  "PS": ("GA", "Y"),
    },
}


# ── Per-project loader ─────────────────────────────────────────────────────

_cache: dict[str, dict] = {}


def get_vds_config(project_id: str | None = None) -> dict:
    """Return the VDS-decoding config for a project. Layered:
       1. Start from DEFAULT_CONFIG.
       2. If `app/data/projects/<project_id>/vds_config.json` exists, deep-merge it.
    """
    cache_key = project_id or "__default__"
    if cache_key in _cache:
        return _cache[cache_key]

    config = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy

    if project_id:
        from ..config import settings
        path = settings.data_dir / "projects" / project_id / "vds_config.json"
        if path.exists():
            try:
                override = json.loads(path.read_text(encoding="utf-8"))
                # Merge prefixes (override wins on collision)
                if "valve_type_prefixes" in override:
                    config["valve_type_prefixes"].update(override["valve_type_prefixes"])
                if "seat_chars" in override:
                    config["seat_chars"] = override["seat_chars"]
                if "end_chars" in override:
                    config["end_chars"] = override["end_chars"]
                if "double_char_ends" in override:
                    config["double_char_ends"] = override["double_char_ends"]
                if "legacy_3char_prefixes" in override:
                    config["legacy_3char_prefixes"].update(override["legacy_3char_prefixes"])
                if "legacy_2char_prefixes" in override:
                    config["legacy_2char_prefixes"].update(override["legacy_2char_prefixes"])
            except Exception:
                pass

    _cache[cache_key] = config
    return config


def refresh_vds_config(project_id: str | None = None) -> None:
    """Force reload after editing vds_config.json (used by tests)."""
    if project_id is None:
        _cache.clear()
    else:
        _cache.pop(project_id, None)
