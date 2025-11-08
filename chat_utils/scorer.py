from typing import Any, Dict, List, Tuple


def score_listing(match: Any, criteria: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Compute a score and compromise list for a listing against user criteria.
    Heuristic scoring: 0..100.

    Criteria keys may include:
    - price: {"$lt": x} or {"$lte": x} or range (ignored for score if already filtered)
    - bedrooms: {"$eq": n}
    - bathrooms: {"$eq": n}
    - amenities: [..]
    - neighborhoods: [..]
    - subway: {"routes": [...], "lines": [...], "max_distance": float|None}
    """
    md = match.metadata
    score = 0.0
    compromises: List[str] = []

    # Bedrooms
    desired_bed = criteria.get("bedrooms", {}).get("$eq")
    if desired_bed is not None:
        if md.get("bedrooms") == desired_bed:
            score += 15
        else:
            compromises.append(f"bedrooms != {desired_bed}")

    # Bathrooms
    desired_bath = criteria.get("bathrooms", {}).get("$eq")
    if desired_bath is not None:
        if float(md.get("bathrooms", 0)) == float(desired_bath):
            score += 10
        else:
            compromises.append(f"bathrooms != {desired_bath}")

    # Price closeness (if budget exists)
    price_filter = criteria.get("price", {})
    budget = price_filter.get("$lt") or price_filter.get("$lte")
    if budget is not None:
        price = float(md.get("price", budget))
        if price <= budget:
            # Higher score if more under budget (cap at 15)
            under = max(0.0, (budget - price) / max(budget, 1))
            score += min(15.0, 15.0 * under * 2)
        else:
            compromises.append("over budget")

    # Neighborhood
    neighborhoods = criteria.get("neighborhoods") or []
    if neighborhoods:
        if (md.get("neighborhood", "").lower() in neighborhoods):
            score += 10
        else:
            compromises.append("different neighborhood")

    # Amenities (coverage)
    desired_amen = criteria.get("amenities") or []
    if desired_amen:
        listing_amen = [a.lower() for a in (md.get("amenities", []) or [])]
        covered = [a for a in desired_amen if a in listing_amen]
        coverage = len(covered) / max(1, len(desired_amen))
        score += 30.0 * coverage
        missing = [a for a in desired_amen if a not in listing_amen]
        if missing:
            compromises.append("missing amenities: " + ", ".join(missing))

    # Subway
    subway = criteria.get("subway") or {}
    routes = subway.get("routes") or []
    lines = subway.get("lines") or []
    max_dist = subway.get("max_distance")

    if routes or lines or (max_dist is not None):
        l_routes = [r.lower() for r in (md.get("subway_routes", []) or [])]
        l_lines = [l.lower() for l in (md.get("subway_lines", []) or [])]
        l_min = md.get("subway_min_distance")

        route_ok = (not routes) or any(r in l_routes for r in routes)
        line_ok = (not lines) or any(l in l_lines for l in lines)
        dist_ok = (max_dist is None) or (l_min is not None and l_min <= max_dist)

        # Determine how many conditions we’re checking
        route_weight = 1 if routes else 0
        line_weight = 1 if lines else 0
        dist_weight = 1 if max_dist is not None else 0

        score += 20.0 * (sum(1 for b in [route_ok, line_ok, dist_ok] if b) /
                        max(1, route_weight + line_weight + dist_weight))

        if not route_ok and routes:
            compromises.append("different subway route")
        if not line_ok and lines:
            compromises.append("different subway line")
        if not dist_ok and (max_dist is not None):
            compromises.append("farther from subway than desired")

    return round(score, 2), compromises


def score_listings(matches: List[Any], criteria: Dict[str, Any]) -> List[Tuple[Any, float, List[str]]]:
    """Return list of (match, score, compromises), sorted by score desc."""
    scored = [(* (m,),) + score_listing(m, criteria) for m in matches]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


