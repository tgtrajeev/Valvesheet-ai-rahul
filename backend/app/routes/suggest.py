"""Typeahead suggestions endpoint — context-aware autocomplete as user types.

Builds suggestions by combining ALL detected keywords from the user's input
(valve type + material + service + pressure class + size) into relevant prompts.
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


def _build_contextual_prompts(text: str) -> list[dict]:
    """Parse ALL keywords from input and build prompts that combine them."""
    text_lower = text.strip().lower()
    detected: dict[str, str] = {}

    # Detect valve type
    for kw in VALVE_TYPE_KEYWORDS:
        if kw in text_lower:
            detected["valve"] = kw.replace("dbb", "DBB").replace("double block", "DBB")
            break

    # Detect material
    mat_map = {
        "carbon": "carbon steel", "cs": "carbon steel",
        "stainless": "SS316L", "ss316": "SS316L", "316": "SS316L",
        "duplex": "duplex SS", "super duplex": "super duplex SS",
        "6mo": "6Mo", "bronze": "bronze", "inconel": "inconel",
        "cu-ni": "Cu-Ni", "copper": "Cu-Ni",
    }
    for mk, label in mat_map.items():
        if mk in text_lower:
            detected["material"] = label
            break

    # Detect service
    svc_map = {
        "hydrocarbon": "hydrocarbon", "hc": "hydrocarbon",
        "seawater": "seawater", "cooling": "cooling water",
        "steam": "steam", "diesel": "diesel", "nitrogen": "nitrogen",
        "firewater": "firewater", "sour": "sour (NACE)",
        "chemical": "chemical injection", "instrument": "instrument air",
    }
    for sk, label in svc_map.items():
        if sk in text_lower:
            detected["service"] = label
            break

    # Detect pressure class
    pressure_match = re.search(r"\b(150|300|600|900|1500|2500)\b", text_lower)
    if pressure_match:
        detected["class"] = pressure_match.group(1)

    # Detect NACE
    if any(kw in text_lower for kw in ["nace", "h2s"]):
        detected["nace"] = "NACE"

    # Detect size
    size_match = re.search(r'\b(\d+(?:/\d+)?)\s*(?:inch|"|in)?\b', text_lower)
    if size_match and size_match.group(1) not in ("150", "300", "600", "900", "1500", "2500"):
        sz = size_match.group(1)
        if sz in ("1", "2", "3", "4", "6", "8", "10", "12", "14", "16", "24") or "/" in sz:
            detected["size"] = f'{sz}"'

    if not detected:
        return []

    prompts = []
    valve = detected.get("valve", "")
    material = detected.get("material", "")
    service = detected.get("service", "")
    pclass = detected.get("class", "")
    nace = detected.get("nace", "")
    size = detected.get("size", "")

    # Build combined search prompt from what was detected
    parts = []
    if valve:
        parts.append(f"{valve} valve")
    if pclass:
        parts.append(f"class {pclass}")
    if material:
        parts.append(material)
    if service:
        parts.append(f"{service} service")
    if nace and "nace" not in service.lower():
        parts.append("NACE")
    if size:
        parts.append(f"size {size}")

    combined = ", ".join(parts)

    if len(detected) >= 2:
        # Multi-keyword: generate a combined prompt
        prompts.append({"text": f"Find {combined}", "category": "search"})
        if valve:
            prompts.append({"text": f"Generate datasheet for {combined}", "category": "generate"})
    elif valve:
        prompts.extend([
            {"text": f"Find all {valve} valves in the database", "category": "search"},
            {"text": f"Find {valve} valve, class 150, carbon steel", "category": "search"},
            {"text": f"Find {valve} valve for hydrocarbon service", "category": "search"},
        ])
    elif material:
        prompts.extend([
            {"text": f"Find all valves with {material} body material", "category": "search"},
            {"text": f"What piping classes use {material}?", "category": "info"},
        ])
    elif service:
        prompts.extend([
            {"text": f"Find valves for {service} service", "category": "search"},
            {"text": f"What piping classes support {service} service?", "category": "info"},
        ])
    elif pclass:
        prompts.extend([
            {"text": f"Find all valves rated class {pclass}", "category": "search"},
            {"text": f"What materials are available for class {pclass}?", "category": "info"},
        ])

    # Add variation prompts that incorporate context
    if valve and not service:
        prompts.append({"text": f"Find {valve} valve for sour (NACE) service", "category": "search"})
    if valve and not material:
        prompts.append({"text": f"Find {valve} valve, carbon steel", "category": "search"})
    if service and not valve:
        prompts.append({"text": f"Find ball valves for {service} service", "category": "search"})

    return prompts


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

    # ── Context-aware prompt suggestions ──
    prompts = _build_contextual_prompts(q)

    # Generic fallbacks for explain / datasheet keywords
    if "explain" in text or "what is" in text:
        prompts.extend([
            {"text": "Explain the pressure_class field", "category": "explain"},
            {"text": "Explain the sour_service field", "category": "explain"},
        ])

    if ("generate" in text or "datasheet" in text or "sheet" in text) and not any(
        p["category"] == "generate" for p in prompts
    ):
        prompts.append(
            {"text": "Generate datasheet for ball valve, class 150, carbon steel, RF ends", "category": "generate"}
        )

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
