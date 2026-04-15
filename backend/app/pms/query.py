"""Generic attribute filter engine.

A filter is a dict: {"path": "corrosion_allowance.numeric", "op": "gte", "value": 6}

Path resolution against a PipingClass:
- "spec_code"                      -> pc.spec_code
- "<attr>.raw|numeric|tokens|unit" -> pc.attributes[attr].<field>
- "<attr>"                         -> pc.attributes[attr].raw  (sugar)
- "header.<key>"                   -> back-compat alias for attributes[key]

Operators: eq, neq, gt, gte, lt, lte, in, not_in, contains, contains_any,
contains_all, regex, exists, not_exists.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from .schema import PipingClass, ProjectPMS, AttributeValue


def _resolve(pc: PipingClass, path: str) -> Any:
    if path == "spec_code":
        return pc.spec_code
    if path.startswith("header."):
        path = "attributes." + path[len("header."):]
    parts = path.split(".")
    if parts[0] == "attributes":
        if len(parts) < 2:
            return None
        attr = pc.attributes.get(parts[1])
        if attr is None:
            return None
        if len(parts) == 2:
            return attr.raw
        field = parts[2]
        return getattr(attr, field, None)
    # bare key sugar -> attribute.raw or sub-field
    attr = pc.attributes.get(parts[0])
    if attr is None:
        return None
    if len(parts) == 1:
        return attr.raw
    return getattr(attr, parts[1], None)


def _as_list(v: Any) -> List[Any]:
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        return list(v)
    return [v]


def _norm_str(v: Any) -> str:
    return str(v).strip().lower() if v is not None else ""


def _match(actual: Any, op: str, expected: Any) -> bool:
    if op == "exists":
        return actual is not None
    if op == "not_exists":
        return actual is None

    if op in ("eq", "neq"):
        # try numeric comparison first so 300 == 300.0
        try:
            result = float(actual) == float(expected)
        except (TypeError, ValueError):
            result = _norm_str(actual) == _norm_str(expected)
        return result if op == "eq" else not result

    if op in ("gt", "gte", "lt", "lte"):
        try:
            a = float(actual); e = float(expected)
        except (TypeError, ValueError):
            return False
        return {"gt": a > e, "gte": a >= e, "lt": a < e, "lte": a <= e}[op]

    if op == "in":
        exp = [_norm_str(x) for x in _as_list(expected)]
        return _norm_str(actual) in exp
    if op == "not_in":
        exp = [_norm_str(x) for x in _as_list(expected)]
        return _norm_str(actual) not in exp

    if op == "contains":
        return _norm_str(expected) in _norm_str(actual)

    if op in ("contains_any", "contains_all"):
        actuals = [_norm_str(x) for x in _as_list(actual)]
        if not actuals:
            actuals = [_norm_str(actual)]
        wanted = [_norm_str(x) for x in _as_list(expected)]
        # match if expected token is substring of any actual token
        hits = [any(w and w in a for a in actuals) for w in wanted]
        return any(hits) if op == "contains_any" else all(hits)

    if op == "regex":
        try:
            return re.search(str(expected), str(actual or ""), re.I) is not None
        except re.error:
            return False
    return False


def evaluate(pc: PipingClass, filters: List[Dict[str, Any]]) -> bool:
    for f in filters:
        actual = _resolve(pc, f["path"])
        if not _match(actual, f.get("op", "eq"), f.get("value")):
            return False
    return True


def query(
    pms: ProjectPMS,
    filters: List[Dict[str, Any]],
    limit: Optional[int] = None,
) -> List[PipingClass]:
    out = [pc for pc in pms.piping_classes.values() if evaluate(pc, filters)]
    out.sort(key=lambda p: p.spec_code)
    return out[:limit] if limit else out
