"""Agent tools — conversational, knowledge-driven tools for valve engineering.

These tools let the agent work the way an engineer thinks:
  "I need a ball valve, carbon steel, class 150, for hydrocarbon service"
NOT:
  "Generate VDS code BLRTA1R"

The knowledge base (VDS index) is used for instant lookup of known specs.
For unknown-but-valid VDS combinations, the Rule Engine dynamically generates
a complete datasheet from PMS data + engineering rules — no hardcoded lookup needed.
"""

import json
import httpx
import yaml

from ..config import settings
from ..engine.knowledge import get_knowledge_base, PRESSURE_CLASS_MAP, MATERIAL_DESCRIPTIONS
from ..engine.validator import validate_combination, validate_datasheet, parse_size_inches, VALID_SPEC_CODES, check_seat_design_temperature, seat_from_vds_code
from ..engine.combination_builder import generate_combinations
from ..engine.field_sources import get_field_sources
from ..engine.pms_resolver import get_pms_field_sources
from ..pms import store as pms_store
from ..pms.query import query as pms_generic_query

# ── Tool definitions (JSON schema for Claude) ────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "find_valves",
        "description": (
            "Search the valve database by any combination of requirements. Use this when "
            "the user describes what they need in natural language — valve type, material, "
            "service, pressure class, size, piping class, NACE/sour service, low temperature. "
            "Returns matching valve specs with VDS codes. This is the PRIMARY tool for "
            "finding the right valve."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "valve_type": {
                    "type": "string",
                    "description": "Valve type: ball, gate, globe, check, butterfly, needle, dbb/double block"
                },
                "piping_class": {
                    "type": "string",
                    "description": "Piping class code: A1, B1N, D1LN, A10, T50A, etc."
                },
                "material": {
                    "type": "string",
                    "description": "Body material: carbon steel, stainless, duplex, super duplex, bronze, inconel"
                },
                "service": {
                    "type": "string",
                    "description": "Service type: hydrocarbon, seawater, steam, cooling water, sour, diesel, nitrogen, firewater"
                },
                "pressure_class": {
                    "type": "integer",
                    "description": "ASME pressure class number: 150, 300, 600, 900, 1500, 2500"
                },
                "size": {
                    "type": "string",
                    "description": "Required size in inches: 2, 1/2, 8, 1-1/2"
                },
                "nace": {
                    "type": "boolean",
                    "description": "True if sour service / NACE MR0175 / H2S required"
                },
                "low_temp": {
                    "type": "boolean",
                    "description": "True if low temperature service (-45C and below) required"
                },
                "query": {
                    "type": "string",
                    "description": "Free text search across all fields (fallback)"
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_piping_class_info",
        "description": (
            "Get comprehensive information about a piping class — what material it uses, "
            "pressure rating, design pressure, temperature range, available services, "
            "what valve types exist for it, bolting specs, gaskets. Use this when the user "
            "asks 'what is piping class A1?' or 'tell me about B1N'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "piping_class": {
                    "type": "string",
                    "description": "Piping class code: A1, B1N, D1LN, A10, A20N, T50A, etc."
                },
            },
            "required": ["piping_class"],
        },
    },
    {
        "name": "generate_datasheet",
        "description": (
            "Generate a complete valve datasheet for a specific VDS code. "
            "First tries the local VDS index for instant lookup. "
            "For unknown codes, the Rule Engine dynamically derives ALL fields "
            "from PMS data + engineering rules — ANY valid combination works. "
            "Use after find_valves has identified the right VDS code. "
            "Pass user-specified field overrides to customize the datasheet — "
            "e.g. if the user requests size 8\", pass overrides with size. "
            "Only truly invalid combinations should be rejected."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "vds_code": {
                    "type": "string",
                    "description": "VDS code to generate datasheet for (e.g. BSFA1R, GAYMA1R)"
                },
                "overrides": {
                    "type": "object",
                    "description": (
                        "User-specified field overrides to apply on top of the base datasheet. "
                        "Common overrides: size (e.g. '8\"'), service, tag_number, line_number, "
                        "project_name, quantity, revision. Any field name from the datasheet can be overridden."
                    ),
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["vds_code"],
        },
    },
    {
        "name": "find_piping_class",
        "description": (
            "Find the right piping class when the user specifies requirements like "
            "'carbon steel, class 150, NACE compliant'. Returns matching piping classes "
            "with their properties. Use this when the user doesn't know the piping class code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "material": {
                    "type": "string",
                    "description": "Material family: carbon steel, stainless, duplex, super duplex"
                },
                "pressure_min": {
                    "type": "integer",
                    "description": "Minimum ASME pressure class: 150, 300, 600, 900, 1500, 2500"
                },
                "nace": {
                    "type": "boolean",
                    "description": "Requires NACE/sour service compliance"
                },
                "low_temp": {
                    "type": "boolean",
                    "description": "Requires low temperature service"
                },
                "corrosion_allowance_mm": {
                    "type": "number",
                    "description": "Required corrosion allowance in mm (e.g., 1.5, 3, 6). Affects class tier selection — B1N has 3mm, B2N has 6mm."
                },
                "service": {
                    "type": "string",
                    "description": "Service keywords to match (e.g., 'glycol', 'firewater', 'corrosive HC', 'fuel gas')"
                },
            },
            "required": [],
        },
    },
    {
        "name": "validate_combination",
        "description": (
            "Validate whether a specific VDS component combination is valid per project rules. "
            "Use when the user gives specific technical details (valve type code, seat type, spec) "
            "and you need to check compatibility before generating."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "valve_type": {"type": "string", "description": "2-char code: BL, BF, GA, GL, CH, DB, NE"},
                "seat": {"type": "string", "description": "Seat code: T (PTFE), P (PEEK), M (Metal)"},
                "spec": {"type": "string", "description": "Piping spec code: A1, B1N, E1, T50A"},
                "end_conn": {"type": "string", "description": "End connection: R (RF), J (RTJ), F (FF), T (NPT), H (Hub)"},
                "bore": {"type": "string", "description": "Bore for Ball valves: R (Reduced), F (Full)"},
                "size": {"type": "string", "description": "Valve size in inches: 1/2, 2, 8, 10. Needed for mounting, gearbox, body form checks."},
                "service": {"type": "string", "description": "Service type if known: hydrocarbon, seawater, clean, etc."},
            },
            "required": ["valve_type", "seat", "spec"],
        },
    },
    {
        "name": "explain_field",
        "description": (
            "Explain what a datasheet field means — its definition, data source, "
            "and what engineering rules apply. Use when the user asks 'what is sour_service?' "
            "or 'what does corrosion_allowance mean?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "field_name": {
                    "type": "string",
                    "description": "Field name: body_material, sour_service, pressure_class, design_pressure, etc."
                },
            },
            "required": ["field_name"],
        },
    },
    {
        "name": "compare_valves",
        "description": (
            "Compare two or more VDS codes side by side. Shows differences in materials, "
            "pressure ratings, construction, etc. Use when user asks to compare options."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "vds_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of VDS codes to compare (2-5 codes)"
                },
            },
            "required": ["vds_codes"],
        },
    },
    {
        "name": "query_pms",
        "description": (
            "Look up Piping Material Specification (PMS) data for a specific piping class. "
            "Returns materials, gaskets, bolts, nuts, flanges, design pressure, hydrotest values, "
            "corrosion allowance, service description, and pressure-temperature ratings. "
            "Use this when the user provides a piping class and you need to know the exact "
            "PMS specifications for materials, bolting, gaskets, or testing requirements. "
            "ALWAYS provide the piping_class parameter."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "piping_class": {
                    "type": "string",
                    "description": "Piping class code: A1, B1N, D1LN, A10, A20N, T50A, etc."
                },
            },
            "required": ["piping_class"],
        },
    },
    {
        "name": "query_project_pms",
        "description": (
            "Generic, project-scoped query against any uploaded PMS. Filters are a list of "
            "{path, op, value}. Path examples: 'spec_code', 'pressure_rating.numeric', "
            "'material_description.tokens', 'service.tokens', 'corrosion_allowance.numeric'. "
            "Operators: eq, neq, gt, gte, lt, lte, in, not_in, contains, contains_any, "
            "contains_all, regex, exists. Returns matching piping classes with their valve "
            "assignments (so the agent can derive which VDS codes are valid). Use this whenever "
            "the user asks 'what piping class for ...' or refers to a specific project PMS."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project slug (e.g. 'fpso-albacora', 'demo-b1n')."},
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "op": {"type": "string"},
                            "value": {},
                        },
                        "required": ["path"],
                    },
                },
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["project_id", "filters"],
        },
    },
    {
        "name": "list_projects",
        "description": "List all PMS projects available in the system, with their class counts.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

# ── Tool execution ────────────────────────────────────────────────────────────

# Module-level project context — set per tool execution by the orchestrator.
# This lets tools resolve PMS from the correct project without changing every signature.
_current_project_id: str | None = None


async def execute_tool(name: str, input_data: dict, project_id: str | None = None) -> dict:
    """Dispatch a tool call to the appropriate handler."""
    global _current_project_id
    _current_project_id = project_id

    handlers = {
        "find_valves": _handle_find_valves,
        "get_piping_class_info": _handle_piping_class_info,
        "generate_datasheet": _handle_generate,
        "find_piping_class": _handle_find_piping_class,
        "validate_combination": _handle_validate,
        "explain_field": _handle_explain,
        "compare_valves": _handle_compare,
        "query_pms": _handle_query_pms,
        "query_project_pms": _handle_query_project_pms,
        "list_projects": _handle_list_projects,
    }
    handler = handlers.get(name)
    if not handler:
        return {"error": f"Unknown tool: {name}"}
    return await handler(input_data)


# ── Handlers ──────────────────────────────────────────────────────────────────

async def _handle_find_valves(input_data: dict) -> dict:
    """Search the VDS index by natural-language parameters."""
    kb = get_knowledge_base()
    results = kb.search(
        valve_type=input_data.get("valve_type"),
        piping_class=input_data.get("piping_class"),
        material=input_data.get("material"),
        service=input_data.get("service"),
        pressure_class=input_data.get("pressure_class"),
        size=input_data.get("size"),
        nace=input_data.get("nace"),
        low_temp=input_data.get("low_temp"),
        query=input_data.get("query"),
        limit=25,
    )

    if not results:
        return {
            "count": 0,
            "results": [],
            "hint": "No matching valves found. Try broader search criteria or check piping class availability.",
        }

    return {
        "count": len(results),
        "total_in_database": kb.total_specs,
        "results": [
            {
                "vds_code": s.vds_code,
                "valve_type": s.valve_type,
                "piping_class": s.piping_class,
                "pressure_class": s.pressure_class,
                "size_range": s.size_range,
                "body_material": s.body_material[:80],
                "end_connections": s.data.get("end_connections", ""),
                "service": s.service[:100] + ("..." if len(s.service) > 100 else ""),
                "sour_service": s.sour_service,
            }
            for s in results
        ],
    }


async def _handle_piping_class_info(input_data: dict) -> dict:
    """Get comprehensive piping class details."""
    kb = get_knowledge_base()
    return kb.get_piping_class_info(input_data["piping_class"])


async def _handle_generate(input_data: dict) -> dict:
    """Generate datasheet — VDS index first, then validate + ML API fallback.

    Validation flow:
    1. If code is in the VDS index → return immediately (it's a known-good spec)
    2. If not in index → decode the VDS code, validate the combination
    3. If validation fails → return errors + fix suggestions, NO datasheet
    4. If validation passes → call ML API for prediction
    """
    vds_code = input_data["vds_code"].upper().strip()
    overrides = input_data.get("overrides") or {}
    kb = get_knowledge_base()

    # ── Step 1: Try VDS index (100% accurate, instant) ──
    spec = kb.get(vds_code)
    if spec:
        data = dict(spec.data)  # copy so we don't mutate the index

        # Apply user overrides — let users customize size, service, tag, etc.
        applied_overrides = {}
        for key, val in overrides.items():
            if val and val.strip():
                # Map common override names to VDS index field names
                field_key = _normalize_field_name(key)
                old_val = data.get(field_key, "")
                data[field_key] = val.strip()
                applied_overrides[field_key] = {"from": old_val, "to": val.strip()}

        total = len(data)
        filled = sum(1 for v in data.values() if v and v != "-" and str(v).strip())
        completion = round((filled / total * 100) if total else 0, 1)
        # Use PMS-aware field sources with granular provenance
        piping_class = data.get("piping_class", "")
        sources = get_pms_field_sources(piping_class, data) if piping_class else get_field_sources(data)

        # Seat vs design temperature (hard error, deterministic)
        seat_errors = check_seat_design_temperature(
            data.get("design_pressure", ""), seat_from_vds_code(vds_code)
        )

        # Run full Phase 1 + Phase 2 validators (VMS/PMS rules) against index hits
        # too, so warnings surface in chat + preview + download for every datasheet.
        phase_warnings: list[str] = []
        phase_errors: list[str] = []
        try:
            from ..engine.vds_decoder import decode_vds
            decoded = decode_vds(vds_code)
            size_str = (
                overrides.get("size")
                or overrides.get("size_range")
                or overrides.get("nominal_size")
                or data.get("size_range", "")
            )
            size_val = parse_size_inches(size_str) if size_str else None
            seat_code = decoded.seat_type.value if decoded.seat_type else "M"

            p1 = validate_combination(
                valve_type=decoded.valve_type.value,
                seat=seat_code,
                spec=decoded.piping_class,
                end_conn=decoded.end_connection.value,
                bore=decoded.design if decoded.valve_type.value in ("BL", "BS") else None,
                size_inches=size_val,
            )
            p2 = validate_datasheet(
                data=data,
                valve_type=decoded.valve_type.value,
                design=decoded.design,
                seat=seat_code,
                spec=decoded.piping_class,
                size_inches=size_val,
            )
            phase_warnings = list(p1.warnings or []) + list(p2.warnings or [])
            # Index-hit codes are known-good per master reference — demote any
            # Phase 1 errors to warnings (would indicate stale index, not a real
            # invalid combination). Phase 2 errors are true conflicts (e.g.
            # piston check valve must be horizontal) and stay as errors.
            if p1.errors:
                phase_warnings.extend(p1.errors)
            if p2.errors:
                phase_errors.extend(p2.errors)
        except Exception:
            # Decode failure on an index code shouldn't break generation —
            # seat_errors alone still apply.
            pass

        all_errors = list(seat_errors) + phase_errors
        result = {
            "vds_code": vds_code,
            "data": data,
            "field_sources": sources,
            "source": "vds_index",
            "completion_pct": completion,
            "validation": {
                "is_valid": not all_errors,
                "source": "known_spec",
                "errors": all_errors,
                "warnings": phase_warnings,
            },
        }
        if all_errors:
            result["draft"] = True
        if applied_overrides:
            result["applied_overrides"] = applied_overrides
        return result

    # ── Step 2: Decode + validate unknown code ──
    from ..engine.vds_decoder import decode_vds
    try:
        decoded = decode_vds(vds_code)
    except ValueError as e:
        return {
            "error": f"Cannot parse VDS code '{vds_code}': {str(e)}",
            "hint": "Use find_valves to search for valid specs instead of guessing codes.",
        }

    # Parse size from overrides for size-dependent validation
    size_str = overrides.get("size") or overrides.get("size_range") or overrides.get("nominal_size")
    size_val = parse_size_inches(size_str) if size_str else None

    # Validate the decoded combination (Phase 1)
    seat_code = decoded.seat_type.value if decoded.seat_type else "M"
    validation = validate_combination(
        valve_type=decoded.valve_type.value,
        seat=seat_code,
        spec=decoded.piping_class,
        end_conn=decoded.end_connection.value,
        bore=decoded.design if decoded.valve_type.value in ("BL", "BS") else None,
        size_inches=size_val,
    )

    if not validation.is_valid:
        # Block generation — return validation errors + suggestions
        return {
            "error": "Invalid VDS combination — cannot generate datasheet.",
            "vds_code": vds_code,
            "decoded": decoded.to_dict(),
            "validation": validation.model_dump(),
            "hint": "Fix the errors above or use find_valves to search for valid specs.",
        }

    # ── Step 3: Valid combination — generate datasheet from rules + PMS data ──
    from ..engine.rule_engine import generate_datasheet as rule_generate
    data = rule_generate(decoded, size_inches=size_val)

    # Apply user overrides
    applied_overrides = {}
    for key, val in overrides.items():
        if val and val.strip():
            field_key = _normalize_field_name(key)
            old_val = data.get(field_key, "")
            data[field_key] = val.strip()
            applied_overrides[field_key] = {"from": old_val, "to": val.strip()}

    # Phase 2 validation (size-dependent spec rules)
    phase2 = validate_datasheet(
        data=data,
        valve_type=decoded.valve_type.value,
        design=decoded.design,
        seat=seat_code,
        spec=decoded.piping_class,
        size_inches=size_val,
    )

    total = len(data)
    filled = sum(1 for v in data.values() if v and v != "-" and str(v).strip())
    completion = round((filled / total * 100) if total else 0, 1)

    piping_class = data.get("piping_class", decoded.piping_class)
    sources = get_pms_field_sources(piping_class, data) if piping_class else get_field_sources(data)

    all_warnings = (validation.warnings or []) + (phase2.warnings or [])
    seat_errors = check_seat_design_temperature(data.get("design_pressure", ""), seat_code)
    all_errors = list(seat_errors) + list(phase2.errors or [])
    result = {
        "vds_code": vds_code,
        "data": data,
        "field_sources": sources,
        "source": "rule_engine",
        "completion_pct": completion,
        "validation": {
            "is_valid": not all_errors,
            "errors": all_errors,
            "warnings": all_warnings,
        },
    }
    if all_errors:
        result["draft"] = True
    if applied_overrides:
        result["applied_overrides"] = applied_overrides
    return result


async def _handle_find_piping_class(input_data: dict) -> dict:
    """Find piping classes matching requirements."""
    kb = get_knowledge_base()
    matches = kb.list_piping_classes_for_requirements(
        material=input_data.get("material"),
        pressure_min=input_data.get("pressure_min"),
        nace=input_data.get("nace", False),
        low_temp=input_data.get("low_temp", False),
    )

    if not matches:
        return {
            "count": 0,
            "classes": [],
            "hint": "No piping classes match these requirements. Available classes: " +
                    ", ".join(kb.piping_classes[:20]),
        }

    return {
        "count": len(matches),
        "classes": matches,
    }


async def _handle_validate(input_data: dict) -> dict:
    """Validate a VDS component combination against spec rules."""
    size_val = parse_size_inches(input_data.get("size"))
    result = validate_combination(
        valve_type=input_data["valve_type"],
        seat=input_data["seat"],
        spec=input_data["spec"],
        end_conn=input_data.get("end_conn"),
        bore=input_data.get("bore"),
        size_inches=size_val,
        service=input_data.get("service"),
    )
    return result.model_dump()


async def _handle_explain(input_data: dict) -> dict:
    """Explain a datasheet field from field_mappings.yaml."""
    field_name = input_data["field_name"].lower().strip()

    mappings_path = settings.data_dir / "field_mappings.yaml"
    try:
        with open(mappings_path) as f:
            mappings = yaml.safe_load(f)
    except Exception:
        return {"error": "Cannot load field_mappings.yaml"}

    for section_name, section_data in mappings.get("sections", {}).items():
        fields = section_data.get("fields", {})
        if field_name in fields:
            f = fields[field_name]
            return {
                "field_name": field_name,
                "display_name": f.get("display_name", field_name),
                "section": section_name,
                "source": f.get("source", "unknown"),
                "description": f.get("description", ""),
                "default": f.get("default", ""),
                "is_required": f.get("is_required", False),
            }

    # Try fuzzy match
    all_fields = {}
    for section_data in mappings.get("sections", {}).values():
        all_fields.update(section_data.get("fields", {}))

    close = [k for k in all_fields if field_name in k or k in field_name]
    if close:
        return {
            "error": f"Field '{field_name}' not found. Did you mean: {', '.join(close[:5])}?",
            "available_fields": close[:10],
        }

    return {"error": f"Field '{field_name}' not found.", "available_fields": list(all_fields.keys())[:20]}


def _normalize_field_name(name: str) -> str:
    """Map common user/agent field names to VDS index field names."""
    aliases = {
        "size": "size_range",
        "valve_size": "size_range",
        "nominal_size": "size_range",
        "tag": "tag_number",
        "line": "line_number",
        "project": "project_name",
        "qty": "quantity",
        "service_type": "service",
        "material": "body_material",
        "body": "body_material",
        "seat": "seat_material",
        "end_conn": "end_connections",
        "ends": "end_connections",
        "end_connection": "end_connections",
        "design_temp": "design_temperature",
        "design_press": "design_pressure",
        "dp": "design_pressure",
        "fire_safe": "fire_rating",
    }
    normalized = name.lower().strip().replace(" ", "_")
    return aliases.get(normalized, normalized)


async def _handle_query_pms(input_data: dict) -> dict:
    """Query PMS data for a specific piping class.

    Project-aware: if a project_id is set in session context, tries
    the project's PMS data first, then falls back to global pms_extracted.json.
    """
    piping_class = input_data.get("piping_class", "").upper().strip()
    if not piping_class:
        return {"error": "piping_class is required. Provide a class code like A1, B1N, T50A."}

    # ── Try project-scoped PMS first ──
    if _current_project_id:
        project_pms = pms_store.load_pms(_current_project_id)
        if project_pms:
            pc = project_pms.piping_classes.get(piping_class)
            if pc:
                return _format_project_pms_response(piping_class, pc, _current_project_id)

    # ── Fallback to global pms_extracted.json ──
    try:
        from ..engine.pms_loader import get_pms_loader
        pms = get_pms_loader()
        spec = pms.get_spec(piping_class)
    except FileNotFoundError:
        return {"error": "PMS data file not found. Ensure pms_extracted.json is in app/data/."}

    if not spec:
        available = pms.spec_codes[:20]
        hint_parts = [f"Available classes include: {', '.join(available)}..."]
        if _current_project_id:
            project_pms = pms_store.load_pms(_current_project_id)
            if project_pms:
                hint_parts.append(f"Project '{_current_project_id}' has: {', '.join(project_pms.class_codes())}")
        return {
            "error": f"Piping class '{piping_class}' not found in PMS data.",
            "available_classes": available,
            "hint": " | ".join(hint_parts),
        }

    result: dict = {
        "piping_class": piping_class,
        "pressure_rating": spec.header.pressure_rating,
        "material_description": spec.header.material_description,
        "corrosion_allowance": spec.header.corrosion_allowance,
        "design_code": spec.header.design_code,
        "service": spec.header.service,
        "nace_compliant": spec.header.nace_flag,
        "low_temperature": spec.header.lt_flag,
    }

    # Design pressure & hydrotest
    if spec.index_row:
        if spec.index_row.design_pressure_barg:
            result["design_pressure_barg"] = spec.index_row.design_pressure_barg
        if spec.index_row.hydrotest_barg:
            shell = round(spec.index_row.hydrotest_barg, 2)
            closure = round((shell / 1.5) * 1.1, 2)
            result["hydrotest_shell_barg"] = shell
            result["hydrotest_closure_barg"] = closure
        if spec.index_row.min_temp_c is not None:
            result["min_temperature_c"] = spec.index_row.min_temp_c
        if spec.index_row.pt_breakpoints:
            result["pt_ratings"] = spec.index_row.pt_breakpoints[:5]

    # Bolting & gaskets
    if spec.bolting_gaskets:
        result["gaskets"] = spec.bolting_gaskets.gasket_spec
        result["stud_bolts"] = spec.bolting_gaskets.stud_bolt_spec
        result["hex_nuts"] = spec.bolting_gaskets.hex_nut_spec

    # Flanges
    if spec.flanges:
        result["flanges"] = [
            {
                "size_range": f.size_range,
                "material": f.flange_moc,
                "face": f.flange_face,
                "type": f.flange_type,
            }
            for f in spec.flanges
        ]

    # Valve assignments
    if spec.valve_assignments:
        result["valve_assignments"] = spec.valve_assignments[:10]

    # Available NPS sizes
    if spec.nps_sizes:
        sizes = sorted(set(s.get("nps_inch", 0) for s in spec.nps_sizes if s.get("nps_inch")))
        if sizes:
            result["available_sizes_inch"] = sizes
            result["size_range"] = f'{sizes[0]}" - {sizes[-1]}"'

    # PT ratings table
    if spec.pt_ratings:
        result["pressure_temperature_ratings"] = spec.pt_ratings[:8]

    return result


async def _handle_compare(input_data: dict) -> dict:
    """Compare multiple VDS codes side by side."""
    kb = get_knowledge_base()
    codes = [c.upper().strip() for c in input_data["vds_codes"][:5]]

    comparison = {}
    missing = []

    # Fields to compare
    compare_fields = [
        "valve_type", "piping_class", "pressure_class", "design_pressure",
        "size_range", "body_material", "seat_material", "end_connections",
        "sour_service", "corrosion_allowance", "gaskets", "bolts", "nuts",
        "fire_rating", "hydrotest_shell", "hydrotest_closure",
    ]

    for code in codes:
        spec = kb.get(code)
        if spec:
            comparison[code] = {f: spec.data.get(f, "-") for f in compare_fields}
        else:
            missing.append(code)

    # Find differences
    differences = []
    if len(comparison) >= 2:
        vals = list(comparison.values())
        for f in compare_fields:
            unique_vals = set(v.get(f, "-") for v in vals)
            if len(unique_vals) > 1:
                differences.append(f)

    return {
        "codes": list(comparison.keys()),
        "comparison": comparison,
        "differing_fields": differences,
        "missing_codes": missing,
    }


def _format_project_pms_response(piping_class: str, pc, project_id: str) -> dict:
    """Format a project-scoped PipingClass into the same shape as query_pms output."""
    result: dict = {
        "piping_class": piping_class,
        "source": f"project:{project_id}",
    }
    # Extract key attributes
    for key in ("pressure_rating", "material_description", "corrosion_allowance",
                "design_code", "service", "mill_tolerance"):
        attr = pc.attributes.get(key)
        if attr:
            result[key] = attr.raw

    # NACE detection from material description
    mat_tokens = []
    mat_attr = pc.attributes.get("material_description")
    if mat_attr and mat_attr.tokens:
        mat_tokens = mat_attr.tokens
    result["nace_compliant"] = "nace" in mat_tokens

    # PT ratings
    if pc.pt_ratings:
        result["pt_ratings"] = [
            {"temperature_c": pt.temperature_c, "max_pressure_barg": pt.max_pressure_barg}
            for pt in pc.pt_ratings[:8]
        ]

    # Hydrotest
    ht_attr = pc.attributes.get("hydrotest_pressure_barg")
    if ht_attr and ht_attr.numeric:
        shell = round(ht_attr.numeric, 2)
        closure = round((shell / 1.5) * 1.1, 2)
        result["hydrotest_shell_barg"] = shell
        result["hydrotest_closure_barg"] = closure

    # Bolting/gaskets
    for key in ("bolting_stud_bolt", "bolting_hex_nut", "bolting_gasket"):
        attr = pc.attributes.get(key)
        if attr:
            clean_key = key.replace("bolting_", "")
            result[clean_key] = attr.raw

    # Flanges
    for key in ("flange_type", "flange_rating", "flange_face", "flange_moc"):
        attr = pc.attributes.get(key)
        if attr:
            result[key] = attr.raw

    # Valve assignments
    if pc.valve_assignments:
        result["valve_assignments"] = [
            {
                "valve_type": va.valve_type,
                "nps_min": va.nps_min,
                "nps_max": va.nps_max,
                "vds_codes": va.vds_codes,
            }
            for va in pc.valve_assignments[:10]
        ]

    # Available NPS sizes from pipe schedule
    if pc.pipe_schedule:
        sizes = sorted(set(ps.nps_inch for ps in pc.pipe_schedule))
        if sizes:
            result["available_sizes_inch"] = sizes
            result["size_range"] = f'{sizes[0]}" - {sizes[-1]}"'

    return result


# ── Dynamic per-project PMS handlers ─────────────────────────────────────────

async def _handle_list_projects(input_data: dict) -> dict:
    projects = pms_store.list_projects()
    out = []
    for m in projects:
        pms = pms_store.load_pms(m.project_id)
        idx = pms_store.load_vds_index(m.project_id)
        out.append({
            "project_id": m.project_id,
            "name": m.name,
            "status": m.status,
            "source_file": m.source_file,
            "class_count": len(pms.piping_classes) if pms else 0,
            "vds_count": len(idx.valid_codes()) if idx else 0,
        })
    return {"projects": out}


async def _handle_query_project_pms(input_data: dict) -> dict:
    project_id = input_data.get("project_id") or _current_project_id
    filters = input_data.get("filters") or []
    limit = input_data.get("limit") or 20
    if not project_id:
        return {"error": "project_id is required. No project context set for this session."}
    pms = pms_store.load_pms(project_id)
    if not pms:
        return {"error": f"project '{project_id}' not found"}
    results = pms_generic_query(pms, filters, limit=limit)
    summary = []
    for pc in results:
        summary.append({
            "spec_code": pc.spec_code,
            "attributes": {k: v.raw for k, v in pc.attributes.items()},
            "valve_assignments": [
                {
                    "valve_type": va.valve_type,
                    "nps_min": va.nps_min,
                    "nps_max": va.nps_max,
                    "vds_codes": va.vds_codes,
                }
                for va in pc.valve_assignments
            ],
        })
    return {"count": len(summary), "results": summary, "project_id": project_id}
