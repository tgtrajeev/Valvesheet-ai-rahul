"""Engine module — VDS decoding, validation, combination generation, and knowledge base."""

from .vds_decoder import decode_vds
from .validator import validate_combination
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

__all__ = [
    "decode_vds",
    "validate_combination",
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
]
