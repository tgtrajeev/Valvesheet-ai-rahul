"""Helpers for shaping API payloads for the datasheet card UI."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml


@lru_cache(maxsize=1)
def card_field_keys() -> frozenset[str]:
    """Fields explicitly configured for rendered datasheet card sections.

    Any field not listed in ``field_mappings.yaml`` would otherwise be grouped
    by the UI into an "Others" section. Product wants that entire section
    hidden, so card payloads only include configured section fields.
    """
    mapping_path = Path(__file__).resolve().parents[1] / "data" / "field_mappings.yaml"
    with mapping_path.open(encoding="utf-8") as f:
        mappings = yaml.safe_load(f) or {}

    keys: set[str] = set()
    for section_name, section_data in (mappings.get("sections") or {}).items():
        if str(section_name).strip().lower() in {"other", "others"}:
            continue
        fields = section_data.get("fields") if isinstance(section_data, dict) else None
        if isinstance(fields, dict):
            keys.update(str(k) for k in fields)
    return frozenset(keys)


def filter_card_data(data: Mapping[str, Any] | None) -> dict[str, Any]:
    """Remove fields that would render under the card's "Others" section."""
    if not isinstance(data, Mapping):
        return {}
    allowed = card_field_keys()
    return {str(k): v for k, v in data.items() if str(k) in allowed}


def filter_card_metadata(
    metadata: Mapping[str, Any] | None,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep per-field metadata aligned with the filtered card fields."""
    if not isinstance(metadata, Mapping):
        return {}
    allowed = set(data.keys())
    return {str(k): v for k, v in metadata.items() if str(k) in allowed}
