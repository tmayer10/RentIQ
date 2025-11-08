import re
from typing import Dict, Any


def normalize_filter_dict(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce filters to a comparable normalized form.
    Sort keys, ensure numeric types are consistent.
    """
    if not filters:
        return {}
    normalized: Dict[str, Any] = {}
    for key in sorted(filters.keys()):
        val = filters[key]
        if isinstance(val, dict):
            inner = {}
            for op in sorted(val.keys()):
                inner[op] = float(val[op]) if isinstance(val[op], (int, float)) else val[op]
            normalized[key] = inner
        else:
            normalized[key] = val
    return normalized


def have_filters_changed(prev: Dict[str, Any], curr: Dict[str, Any]) -> bool:
    """Return True if filter dicts differ meaningfully."""
    return normalize_filter_dict(prev or {}) != normalize_filter_dict(curr or {})


