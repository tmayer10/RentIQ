# post_filters.py
"""
Post-retrieval semantic filtering for neighborhoods, amenities, and subway preferences.
These filters are applied AFTER Pinecone retrieval to enable more nuanced, LLM-assisted matching.
"""

import os
import re
from typing import List, Dict, Any, Optional
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from allowable_values import (
    AMENITIES, NEIGHBORHOODS, SUBWAY_ROUTES, SUBWAY_LINES,
    AMENITY_SYNONYMS, NEIGHBORHOOD_ALIASES
)

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# Pydantic models for structured outputs
class AmenitiesResponse(BaseModel):
    """Structured response for amenity extraction."""
    amenities: List[str] = Field(
        default_factory=list,
        description="List of amenity strings from the canonical amenities list"
    )


class NeighborhoodsResponse(BaseModel):
    """Structured response for neighborhood extraction."""
    neighborhoods: List[str] = Field(
        default_factory=list,
        description="List of neighborhood strings in kebab-case format"
    )


class SubwayPreferencesResponse(BaseModel):
    """Structured response for subway preferences."""
    routes: List[str] = Field(
        default_factory=list,
        description="List of subway route identifiers (single char/number, lowercase)"
    )
    lines: List[str] = Field(
        default_factory=list,
        description="List of subway line names (multi-word, lowercase)"
    )
    max_distance: Optional[float] = Field(
        None,
        description="Maximum distance from subway in miles"
    )


def parse_amenities(user_query: str) -> List[str]:
    """
    Extract amenity requirements from user query and map to canonical amenity list.
    Uses Pydantic-enforced structured output for robust parsing.
    
    Returns:
        List of canonical amenity strings from AMENITIES list
    """
    prompt = f"""Extract ALL amenity requirements from the user's query and map to the canonical amenity list.

CANONICAL AMENITIES: {', '.join(AMENITIES[:30])}... (and {len(AMENITIES)-30} more)

SYNONYM MAPPINGS:
- "laundry"/"w/d" → ["laundry", "washer_dryer"]
- "doorman" → ["doorman", "full_time_doorman", "part_time_doorman"]
- "parking"/"garage" → ["parking", "garage", "assigned_parking"]
- "gym" → ["gym"]
- "outdoor space" → ["balcony", "terrace", "patio", "deck"]
- "pets" → ["pets", "cats", "dogs"]
- "elevator", "dishwasher", "pool", "storage" → exact matches
- "ac" → ["central_ac"]
- "hardwood" → ["hardwood_floors"]

Rules:
1. ONLY use amenities from canonical list (underscore_format, lowercase)
2. Include ALL synonyms (e.g., "laundry" → both "laundry" AND "washer_dryer")
3. Empty list if no amenities mentioned

User query: "{user_query}"

Extract amenities:"""

    try:
        completion = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format=AmenitiesResponse,
            temperature=0
        )
        
        parsed = completion.choices[0].message.parsed
        
        # Validate: only keep items that are in the canonical list
        validated = [a for a in parsed.amenities if a in AMENITIES]
        return validated
    except Exception as e:
        print(f"[WARN] Amenity parsing failed: {e}. Falling back to regex.")
        return _fallback_parse_amenities(user_query)


def _fallback_parse_amenities(user_query: str) -> List[str]:
    """Regex-based fallback for amenity extraction."""
    query_lower = user_query.lower()
    found = set()
    
    # Direct matches
    for amenity in AMENITIES:
        # Try both underscore and space versions
        patterns = [
            amenity.replace("_", " "),
            amenity.replace("_", ""),
            amenity
        ]
        for pattern in patterns:
            if pattern in query_lower:
                found.add(amenity)
                # Add synonyms
                for key, synonyms in AMENITY_SYNONYMS.items():
                    if amenity in synonyms:
                        found.update([s for s in synonyms if s in AMENITIES])
                break
    
    return list(found)


def parse_neighborhoods(user_query: str) -> List[str]:
    """
    Extract neighborhood preferences from user query and map to canonical neighborhood list.
    Uses Pydantic-enforced structured output. Handles landmarks (NYU -> East Village).
    
    Returns:
        List of canonical neighborhood strings from NEIGHBORHOODS list
    """
    prompt = f"""Extract ALL neighborhood preferences from the user's query and map to canonical neighborhoods.

CANONICAL NEIGHBORHOODS (Manhattan, kebab-case): {', '.join(NEIGHBORHOODS[:20])}... (and {len(NEIGHBORHOODS)-20} more)

LANDMARK MAPPINGS:
- "NYU" → ["east-village", "greenwich-village", "noho"]
- "Columbia" → ["morningside-heights", "manhattan-valley"]
- "FiDi" → ["financial-district"]
- "UES" → ["upper-east-side"]
- "UWS" → ["upper-west-side"]
- "Hell's Kitchen" → ["hells-kitchen"]
- "The Village" → ["greenwich-village", "west-village", "east-village"]
- "Midtown" → ["midtown", "midtown-south"]
- "LES" → ["lower-east-side"]
- "Harlem" → ["central-harlem", "east-harlem", "west-harlem"]

Rules:
1. ONLY use neighborhoods from canonical list (kebab-case, lowercase)
2. Landmarks → include ALL nearby neighborhoods
3. Empty list if no neighborhoods mentioned

User query: "{user_query}"

Extract neighborhoods:"""

    try:
        completion = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format=NeighborhoodsResponse,
            temperature=0
        )
        
        parsed = completion.choices[0].message.parsed
        
        # Validate
        validated = [n for n in parsed.neighborhoods if n in NEIGHBORHOODS]
        return validated
    except Exception as e:
        print(f"[WARN] Neighborhood parsing failed: {e}. Falling back to regex.")
        return _fallback_parse_neighborhoods(user_query)


def _fallback_parse_neighborhoods(user_query: str) -> List[str]:
    """Regex-based fallback for neighborhood extraction."""
    query_lower = user_query.lower()
    found = set()
    
    # Check canonical names
    for neighborhood in NEIGHBORHOODS:
        # Try with and without hyphens
        patterns = [
            neighborhood,
            neighborhood.replace("-", " "),
            neighborhood.replace("-", "")
        ]
        for pattern in patterns:
            if pattern in query_lower:
                found.add(neighborhood)
                break
    
    # Check aliases
    for alias, canonical_list in NEIGHBORHOOD_ALIASES.items():
        if alias in query_lower:
            found.update([n for n in canonical_list if n in NEIGHBORHOODS])
    
    return list(found)


def parse_subway_preferences(user_query: str) -> Dict[str, Any]:
    """
    Extract subway route/line preferences and distance constraints.
    Uses Pydantic-enforced structured output.
    
    Returns:
        Dict with keys:
        - routes: List[str] - subway routes (e.g., ["1", "2", "a"])
        - lines: List[str] - subway lines (e.g., ["broadway", "lexington"])
        - max_distance: Optional[float] - max distance in miles
    """
    prompt = f"""Extract subway route/line preferences and distance constraints from the user's query.

CANONICAL ROUTES: {', '.join(SUBWAY_ROUTES)}
CANONICAL LINES: {', '.join(SUBWAY_LINES)}

EXAMPLES:
- "near F train" → routes=["f"], max_distance=null
- "within 0.5 miles of 1 train" → routes=["1"], max_distance=0.5
- "close to A/C/E" → routes=["a","c","e"], max_distance=null
- "on Lexington line" → lines=["lexington"], max_distance=null
- "within 10 min walk of subway" → routes=[], lines=[], max_distance=0.5

Rules:
1. Routes: single char/number (lowercase)
2. Lines: multi-word (lowercase)
3. Distance: miles (0.5 mi ≈ 10 min walk, 0.3 mi ≈ 5 min)
4. "close to subway" without route → empty routes/lines

User query: "{user_query}"

Extract subway preferences:"""

    try:
        completion = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format=SubwayPreferencesResponse,
            temperature=0
        )
        
        parsed = completion.choices[0].message.parsed
        
        # Validate and normalize
        result = {
            "routes": [r.lower() for r in parsed.routes if r.lower() in SUBWAY_ROUTES],
            "lines": [l.lower() for l in parsed.lines if l.lower() in SUBWAY_LINES],
            "max_distance": parsed.max_distance
        }
        return result
    except Exception as e:
        print(f"[WARN] Subway parsing failed: {e}. Falling back to regex.")
        return _fallback_parse_subway(user_query)


def _fallback_parse_subway(user_query: str) -> Dict[str, Any]:
    """Regex-based fallback for subway extraction."""
    query_lower = user_query.lower()
    
    # Extract routes
    routes = set()
    for route in SUBWAY_ROUTES:
        patterns = [
            rf"\b{re.escape(route)}\s*train\b",
            rf"\b{re.escape(route)}\s*line\b",
            rf"\b{re.escape(route)}/",
            rf"/{re.escape(route)}\b",
        ]
        for pattern in patterns:
            if re.search(pattern, query_lower):
                routes.add(route.lower())
                break
    
    # Extract lines
    lines = set()
    for line in SUBWAY_LINES:
        if line in query_lower:
            lines.add(line.lower())
    
    # Extract distance
    max_distance = None
    dist_match = re.search(r"within\s+(\d+(?:\.\d+)?)\s*miles?", query_lower)
    if dist_match:
        max_distance = float(dist_match.group(1))
    elif "close to subway" in query_lower or "near subway" in query_lower:
        max_distance = 0.5  # default 0.5 miles
    
    return {
        "routes": list(routes),
        "lines": list(lines),
        "max_distance": max_distance
    }


def apply_post_retrieval_filters(
    matches: List[Any],
    user_query: str,
    amenities: Optional[List[str]] = None,
    neighborhoods: Optional[List[str]] = None,
    subway_prefs: Optional[Dict[str, Any]] = None
) -> List[Any]:
    """
    Apply post-retrieval filters to Pinecone matches.
    
    Args:
        matches: List of Pinecone match objects with .metadata
        user_query: Original user query (for logging/fallback)
        amenities: Parsed amenity requirements (if None, will parse from query)
        neighborhoods: Parsed neighborhood preferences (if None, will parse from query)
        subway_prefs: Parsed subway preferences (if None, will parse from query)
    
    Returns:
        Filtered list of matches
    """
    # Parse if not provided
    if amenities is None:
        amenities = parse_amenities(user_query)
    if neighborhoods is None:
        neighborhoods = parse_neighborhoods(user_query)
    if subway_prefs is None:
        subway_prefs = parse_subway_preferences(user_query)
    
    filtered = []
    
    for match in matches:
        md = match.metadata
        
        # Neighborhood filter
        if neighborhoods:
            listing_neighborhood = md.get("neighborhood", "").lower()
            if listing_neighborhood not in neighborhoods:
                continue
        
        # Amenity filter (ALL required amenities must be present)
        if amenities:
            listing_amenities = [a.lower() for a in md.get("amenities", [])]
            if not all(req_amenity in listing_amenities for req_amenity in amenities):
                continue
        
        # Subway filter
        if subway_prefs.get("routes") or subway_prefs.get("lines"):
            listing_routes = [r.lower() for r in md.get("subway_routes", [])]
            listing_lines = [l.lower() for l in md.get("subway_lines", [])]
            
            route_match = (
                not subway_prefs.get("routes") or
                any(r in listing_routes for r in subway_prefs["routes"])
            )
            line_match = (
                not subway_prefs.get("lines") or
                any(l in listing_lines for l in subway_prefs["lines"])
            )
            
            if not (route_match and line_match):
                continue
        
        # Subway distance filter
        if subway_prefs.get("max_distance") is not None:
            listing_min_dist = md.get("subway_min_distance")
            if listing_min_dist is None or listing_min_dist > subway_prefs["max_distance"]:
                continue
        
        # Passed all filters
        filtered.append(match)
    
    print(f"[INFO] Post-filter: {len(matches)} -> {len(filtered)} matches")
    print(f"[INFO] Filters applied: amenities={amenities}, neighborhoods={neighborhoods}, subway={subway_prefs}")
    
    return filtered

