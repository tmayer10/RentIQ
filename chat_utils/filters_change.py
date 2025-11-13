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
    """Return True if filter dicts differ meaningfully.

    Handles both formats:
    - Old: {price: {...}, bedrooms: ..., ...}  (just hard filters)
    - New: {hard: {...}, amenities: [...], neighborhoods: [...], subway: {...}}

    Compares hard filters, amenities, neighborhoods, and subway preferences.
    """
    prev = prev or {}
    curr = curr or {}

    # Detect format: if 'hard' key exists, it's new format
    is_prev_new_format = "hard" in prev
    is_curr_new_format = "hard" in curr

    # Extract hard filters
    prev_hard = prev.get("hard", {}) if is_prev_new_format else prev
    curr_hard = curr.get("hard", {}) if is_curr_new_format else curr

    # Compare hard filters (price, bedrooms, bathrooms, sqft, zipcode)
    hard_changed = normalize_filter_dict(prev_hard) != normalize_filter_dict(curr_hard)

    # If either is old format, only compare hard filters (backward compatibility)
    if not is_prev_new_format or not is_curr_new_format:
        return hard_changed

    # Compare soft filters (new format only)
    amenities_changed = set(prev.get("amenities", [])) != set(curr.get("amenities", []))
    neighborhoods_changed = set(prev.get("neighborhoods", [])) != set(curr.get("neighborhoods", []))

    # Compare subway preferences
    prev_subway = prev.get("subway", {})
    curr_subway = curr.get("subway", {})
    subway_changed = (
        set(prev_subway.get("routes", [])) != set(curr_subway.get("routes", [])) or
        set(prev_subway.get("lines", [])) != set(curr_subway.get("lines", [])) or
        prev_subway.get("max_distance") != curr_subway.get("max_distance")
    )

    return hard_changed or amenities_changed or neighborhoods_changed or subway_changed


