"""Helpers for shaping API payloads for the datasheet card UI."""

from __future__ import annotations

import re
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


def _infer_dbb_instrument_for_chat(dec: Any) -> bool:
    """Match rule_engine instrument-DBB heuristic without loading valve_assignments."""
    if dec.valve_type.value != "DB":
        return False
    if (dec.design or "").upper() == "P":
        return True
    pc = (dec.piping_class or "").upper().strip()
    return bool(re.match(r"^T\d", pc))


def apply_chatbot_field_mask(data: dict[str, Any]) -> dict[str, Any]:
    """Drop typed rows that must not appear in the AI chatbot card (verification sheet unchanged)."""
    out = dict(data)
    raw = str(out.get("vds_no") or out.get("vds_code") or "").strip()
    if not raw:
        return out
    try:
        from .datasheet_prune import keys_to_drop_for_chat_ui
        from .vds_decoder import decode_vds

        dec = decode_vds(raw)
        vt = dec.valve_type.value
        seat = dec.seat_type.value if dec.seat_type else "M"
        dbb_inst = _infer_dbb_instrument_for_chat(dec)
        for k in keys_to_drop_for_chat_ui(vt, dec.design, seat, dbb_instrument=dbb_inst):
            out.pop(k, None)
    except Exception:
        return out
    return out


def filter_card_data(
    data: Mapping[str, Any] | None,
    *,
    for_chat_ui: bool = False,
) -> dict[str, Any]:
    """Remove fields that would render under the card's "Others" section.

    When ``for_chat_ui`` is True (agent tool / chat stream only), also strip
    valve-type-specific construction and material rows that must not appear in
    the chatbot. REST ``/datasheets`` uses ``for_chat_ui=False`` so client
    verification flows keep the full rule-engine grid.
    """
    if not isinstance(data, Mapping):
        return {}
    allowed = card_field_keys()
    filtered = {str(k): v for k, v in data.items() if str(k) in allowed}
    if for_chat_ui:
        filtered = apply_chatbot_field_mask(filtered)
    return filtered


def filter_card_metadata(
    metadata: Mapping[str, Any] | None,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep per-field metadata aligned with the filtered card fields."""
    if not isinstance(metadata, Mapping):
        return {}
    allowed = set(data.keys())
    return {str(k): v for k, v in metadata.items() if str(k) in allowed}
