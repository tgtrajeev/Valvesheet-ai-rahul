"""Engine module — VDS decoding, validation, combination generation, and knowledge base."""

from .vds_decoder import decode_vds
from .validator import validate_combination
from .combination_builder import generate_combinations, build_vds_code
from .knowledge import get_knowledge_base, KnowledgeBase

__all__ = [
    "decode_vds",
    "validate_combination",
    "generate_combinations",
    "build_vds_code",
    "get_knowledge_base",
    "KnowledgeBase",
]
