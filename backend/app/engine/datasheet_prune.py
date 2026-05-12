"""Valve-type-aware pruning of datasheet fields.

Removes Material / Construction subsection keys that do not apply to the decoded
valve type so the valvesheet matches VMS-style layouts and avoids ball-only rows
(e.g. antistatic / Viton seal) on gate, check, butterfly, or instrument DBB valves.
"""

from __future__ import annotations


# Subsection keys that are *not* universal — only keep when allowed for this valve type.
_TYPED_SECTION_KEYS: frozenset[str] = frozenset({
    "ball_construction",
    "ball_mounting_type",
    "dbb_feature",
    "seat_loading",
    "body_vent_drain",
    "sealant_injection",
    "body_cavity_relief",
    "wedge_construction",
    "disc_construction",
    "shaft_construction",
    "stem_construction",
    "back_seat_construction",
    "packing_construction",
    "bonnet_construction",
    "check_valve_note",
    "dbb_end_connection",
    "hinge_pin_material",
    "ball_material",
    "wedge_material",
    "disc_material",
    "shaft_material",
    "stem_material",
    "trim_material",
    "needle_material",
    "minimum_bore",
    "seat_material",
    "seal_material",
    "seal_material_note",
    "resilient_seat_note",
    "seat_coating",
    "stellite_overlay",
    "hardness_requirement",
    "bonnet_material",
    "backseat",
    "back_seat_material",
    "seat_pocket_overlay",
    "spring_material",
    "position_indicator",
    "seat_construction",
    "gland_material",
    "gland_packing",
    "lever_handwheel",
    "locks",
    "fire_test",
    "antistatic_device",
})


def _allowed_typed_keys(
    vt: str,
    design: str,
    seat: str,
    *,
    dbb_instrument: bool,
) -> frozenset[str]:
    d = (design or "").upper()
    st = (seat or "M").upper()

    # Rotating / rising stem *construction* row (gate/globe/ball/needle/DBB) — not used on
    # swing / dual / wafer valves where the datasheet uses a shaft or disc pivot narrative instead.
    _stem_construction = frozenset({"stem_construction"})
    # Stem trim + packing + lever/gear row — applies to valves with a stem seal system and operator.
    _stem_trim_pack_lever = frozenset({"stem_material", "gland_material", "gland_packing", "lever_handwheel"})
    _gland_pack_lever = frozenset({"gland_material", "gland_packing", "lever_handwheel"})

    # Ball (incl. SDSS ball)
    if vt in ("BL", "BS"):
        keys = {
            "ball_material", "ball_construction", "ball_mounting_type",
            "seat_material", "seal_material", "seat_construction",
            "spring_material", "seat_coating", "stellite_overlay", "hardness_requirement",
            "dbb_feature", "seat_loading", "body_vent_drain", "sealant_injection", "body_cavity_relief",
            "flange_face_note", "body_form", "position_indicator",
            "seal_material_note", "resilient_seat_note", "fire_test", "antistatic_device",
            "locks",
            *_stem_construction,
            *_stem_trim_pack_lever,
        }
        return frozenset(keys)

    if vt == "BF":
        keys = {
            "shaft_material",
            "shaft_construction",
            "seat_material",
            "seat_construction",
            "flange_face_note",
            "body_form",
            "position_indicator",
            "locks",
            *_gland_pack_lever,
        }
        if st in ("T", "P"):
            keys |= {"resilient_seat_note"}
        return frozenset(keys)

    if vt == "GA":
        return frozenset({
            "wedge_material", "wedge_construction", "seal_material", "seat_construction",
            "back_seat_construction", "packing_construction",
            "bonnet_material", "backseat", "back_seat_material",
            "seat_pocket_overlay",
            "hardness_requirement", "flange_face_note", "body_form",
            "seal_material_note", "resilient_seat_note",
            "locks",
            *_stem_construction,
            *_stem_trim_pack_lever,
        })

    if vt == "GL":
        return frozenset({
            "disc_material", "disc_construction",
            "back_seat_construction", "packing_construction",
            "bonnet_material", "backseat", "back_seat_material",
            "seat_pocket_overlay",
            "seat_material", "seal_material", "spring_material",
            "seal_material_note", "resilient_seat_note",
            "hardness_requirement",
            "flange_face_note", "body_form",
            "locks",
            *_stem_construction,
            *_stem_trim_pack_lever,
        })

    if vt == "CH":
        keys = {
            "disc_material", "seat_construction",
            "flange_face_note", "body_form", "spring_material",
        }
        if d == "S":
            keys.add("hinge_pin_material")
        if d == "D":
            keys.add("disc_construction")
        # Small-bore piston note is conditional in rule_engine; keep if present
        keys.add("check_valve_note")
        # Check valves do not use a gate/ball-style stem row or stem packing table lines.
        return frozenset(keys)

    if vt == "DB":
        keys = {
            "ball_material", "seat_material",
            "flange_face_note", "body_form", "position_indicator",
            "locks",
            *_stem_construction,
            *_stem_trim_pack_lever,
        }
        if not dbb_instrument:
            keys |= {
                "seat_construction", "dbb_end_connection",
            }
            if st in ("T", "P"):
                keys |= {"fire_test", "antistatic_device"}
        else:
            keys.add("seat_construction")
        return frozenset(keys)

    if vt == "NE":
        return frozenset({
            "needle_material", "minimum_bore", "backseat", "back_seat_material",
            "flange_face_note", "body_form",
            "seal_material_note",
            *_stem_construction,
            *_stem_trim_pack_lever,
        })

    return frozenset()


def keys_to_drop_for_chat_ui(
    vt: str,
    design: str,
    seat: str,
    *,
    dbb_instrument: bool = False,
) -> frozenset[str]:
    """Subset of :func:`_TYPED_SECTION_KEYS` to strip from AI/chatbot payloads only.

    Full verification datasheets (REST ``/datasheets``, client generator) keep the
    rule-engine output; the chat card must not show rows that are not on the VMS
    grid for this valve type (and globe must omit seal/spring per product policy).
    """
    allowed = _allowed_typed_keys(vt, design, seat, dbb_instrument=dbb_instrument)
    drops: set[str] = {k for k in _TYPED_SECTION_KEYS if k not in allowed}
    if vt == "GL":
        drops.update({"seal_material", "spring_material"})
    return frozenset(drops)


def prune_datasheet_by_valve_type(
    vt: str,
    design: str,
    seat: str,
    data: dict[str, str],
    *,
    dbb_instrument: bool = False,
) -> None:
    """In-place: drop typed keys that are not allowed for ``vt`` / ``design`` / ``seat``."""
    allowed = _allowed_typed_keys(vt, design, seat, dbb_instrument=dbb_instrument)
    for k in list(data.keys()):
        if k.startswith("_"):
            continue
        if k in _TYPED_SECTION_KEYS and k not in allowed:
            data.pop(k, None)
