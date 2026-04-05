"""Typeahead suggestions endpoint — instant autocomplete as user types.

Returns contextual suggestions based on partial input:
- Valve types when typing "ball", "gate", etc.
- Piping classes when typing "A1", "B1N"
- Services when typing "hydrocarbon", "sour"
- Materials when typing "carbon", "stainless"
- VDS codes when typing a code prefix
"""

import re
from fastapi import APIRouter

from ..engine.knowledge import (
    get_knowledge_base,
    VALVE_TYPE_KEYWORDS,
    SERVICE_KEYWORDS,
    PRESSURE_CLASS_MAP,
    MATERIAL_DESCRIPTIONS,
)

router = APIRouter()


@router.get("/suggest")
async def suggest(q: str = "", limit: int = 8):
    """Return typeahead suggestions for the chat input.

    Categories returned:
    - prompts: Full prompt suggestions the user can send directly
    - valves: Matching VDS codes from the index
    - classes: Matching piping classes
    """
    text = q.strip().lower()
    if len(text) < 2:
        return {"prompts": [], "valves": [], "classes": []}

    kb = get_knowledge_base()
    prompts: list[dict] = []
    valves: list[dict] = []
    classes: list[dict] = []

    upper = q.strip().upper()

    # ── Check if typing a VDS code prefix ──
    if re.match(r"^[A-Z]{2,4}", upper) and len(upper) >= 3:
        matches = [
            {"vds_code": code, "valve_type": s.valve_type, "piping_class": s.piping_class}
            for code, s in kb.specs.items()
            if code.startswith(upper)
        ]
        valves = matches[:limit]

    # ── Check if typing a piping class ──
    if re.match(r"^[A-GT]\d", upper):
        matching_classes = [pc for pc in kb.piping_classes if pc.upper().startswith(upper)]
        for pc in matching_classes[:limit]:
            info = kb.get_piping_class_info(pc)
            if not info.get("error"):
                classes.append({
                    "piping_class": pc,
                    "pressure_class": info.get("pressure_class", ""),
                    "material": info.get("material_description", "")[:50],
                })

    # ── Contextual prompt suggestions ──

    # Valve type detected
    for kw in VALVE_TYPE_KEYWORDS:
        if kw in text:
            vt_label = kw.replace("dbb", "double block & bleed").title()
            prompts.extend([
                {"text": f"Find all {kw} valves for hydrocarbon service", "category": "search"},
                {"text": f"Find {kw} valve, class 150, carbon steel", "category": "search"},
                {"text": f"Compare {kw} valve options for A1 vs A1N", "category": "compare"},
            ])
            break

    # Material detected
    mat_keywords = ["carbon", "stainless", "duplex", "super duplex", "bronze", "inconel", "ss316"]
    for mk in mat_keywords:
        if mk in text:
            prompts.extend([
                {"text": f"Find all valves with {mk} body material", "category": "search"},
                {"text": f"What piping classes use {mk}?", "category": "info"},
            ])
            break

    # Service detected
    for svc in SERVICE_KEYWORDS:
        if svc in text:
            prompts.extend([
                {"text": f"Find ball valves for {svc} service", "category": "search"},
                {"text": f"What piping classes support {svc} service?", "category": "info"},
            ])
            break

    # Pressure class detected
    pressure_match = re.search(r"\b(150|300|600|900|1500|2500)\b", text)
    if pressure_match:
        pc = pressure_match.group(1)
        prompts.extend([
            {"text": f"Find all valves rated class {pc}", "category": "search"},
            {"text": f"What materials are available for class {pc}?", "category": "info"},
        ])

    # NACE/sour detected
    if any(kw in text for kw in ["nace", "sour", "h2s"]):
        prompts.extend([
            {"text": "Find all NACE-compliant piping classes", "category": "search"},
            {"text": "What materials are approved for sour service?", "category": "info"},
        ])

    # Size detected
    size_match = re.search(r'\b(\d+(?:/\d+)?)\s*(?:inch|"|in)\b', text)
    if size_match:
        sz = size_match.group(1)
        prompts.extend([
            {"text": f'Find ball valves available in {sz}" size', "category": "search"},
        ])

    # Generic — explain / datasheet keywords
    if "explain" in text or "what is" in text:
        prompts.extend([
            {"text": "Explain the pressure_class field", "category": "explain"},
            {"text": "Explain the sour_service field", "category": "explain"},
        ])

    if "generate" in text or "datasheet" in text or "sheet" in text:
        prompts.extend([
            {"text": "Generate datasheet for ball valve, A1, carbon steel", "category": "generate"},
        ])

    # Deduplicate and limit
    seen = set()
    unique_prompts = []
    for p in prompts:
        if p["text"] not in seen:
            seen.add(p["text"])
            unique_prompts.append(p)
    prompts = unique_prompts[:limit]

    return {
        "prompts": prompts,
        "valves": valves,
        "classes": classes,
    }
