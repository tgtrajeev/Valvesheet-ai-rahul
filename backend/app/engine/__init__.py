"""Engine module — VDS decoding, validation, combination generation, knowledge base, and rule engine."""

from .vds_decoder import decode_vds
from .validator import validate_combination, validate_datasheet, parse_size_inches
from .combination_builder import generate_combinations, build_vds_code
from .knowledge import get_knowledge_base, KnowledgeBase
from .pms_loader import get_pms_loader, PmsLoader
from .pms_resolver import (
    resolve_hydrotest,
    resolve_gaskets,
    resolve_bolts,
    resolve_nuts,
    resolve_design_pressure,
    get_pms_field_sources,
)
from .rule_engine import generate_datasheet

__all__ = [
    "decode_vds",
    "validate_combination",
    "validate_datasheet",
    "parse_size_inches",
    "generate_combinations",
    "build_vds_code",
    "get_knowledge_base",
    "KnowledgeBase",
    "get_pms_loader",
    "PmsLoader",
    "resolve_hydrotest",
    "resolve_gaskets",
    "resolve_bolts",
    "resolve_nuts",
    "resolve_design_pressure",
    "get_pms_field_sources",
    "generate_datasheet",
]
