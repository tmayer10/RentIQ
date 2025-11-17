# post_filters.py
"""
Post-retrieval semantic filtering for neighborhoods, amenities, and subway preferences.
These filters are applied AFTER Pinecone retrieval to enable more nuanced, LLM-assisted matching.
"""

import os
import re
import asyncio
from typing import List, Dict, Any, Optional
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from allowable_values import (
    AMENITIES, NEIGHBORHOODS, SUBWAY_ROUTES, SUBWAY_LINES,
    AMENITY_SYNONYMS, NEIGHBORHOOD_ALIASES
)
from rate_limiter import call_llm_with_limit
try:
    from google import genai
    from google.genai import types
except ImportError as e:
    raise ImportError(
        "Failed to import 'genai' from 'google'. "
        "Please ensure 'google-genai' package is installed: pip install google-genai>=1.0.0. "
        "If running in Docker, rebuild the image: docker-compose build --no-cache"
    ) from e

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


async def parse_amenities(user_query: str) -> List[str]:
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

    #messages = [{"role": "user", "content": prompt}]

    try:
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

        # Run synchronously in a thread so async code can await
        response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                system_instruction ="""You are an expert at extracting structured data from user queries.
                You always respond with valid JSON that adheres to the provided schema.""",
                response_mime_type="application/json",
                response_schema= AmenitiesResponse,
                ),
            )

        # `response.parsed` is already a NeighborhoodsResponse object
        parsed = response.parsed
        
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


async def parse_neighborhoods(user_query: str) -> List[str]:
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

    #messages = [{"role": "user", "content": prompt}]

    try:
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

        # Run synchronously in a thread so async code can await
        response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                system_instruction ="""You are an expert at extracting structured data from user queries.
                You always respond with valid JSON that adheres to the provided schema.""",
                response_mime_type="application/json",
                response_schema= NeighborhoodsResponse,
                ),
            )

        # `response.parsed` is already a NeighborhoodsResponse object
        parsed = response.parsed
        
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


async def parse_subway_preferences(user_query: str) -> Dict[str, Any]:
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

    #messages = [{"role": "user", "content": prompt}]

    try:
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

        # Run synchronously in a thread so async code can await
        response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                system_instruction ="""You are an expert at extracting structured data from user queries.
                You always respond with valid JSON that adheres to the provided schema.""",
                response_mime_type="application/json",
                response_schema= SubwayPreferencesResponse,
                ),
            )

        # `response.parsed` is already a NeighborhoodsResponse object
        parsed = response.parsed
       
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

def build_pinecone_filter(
    amenities: Optional[List[str]] = None,
    neighborhoods: Optional[List[str]] = None,
    subway_prefs: Optional[Dict[str, Any]] = None):
    filter_dict = {}

    # Amenities: list stored in metadata, query with $in
    if amenities:
        filter_dict["amenities"] = {"$in": [a.lower() for a in amenities]}

    # Neighborhood: stored as single string, still query with $in
    if neighborhoods:
        filter_dict["neighborhood"] = {"$in": [n.lower() for n in neighborhoods]}

    # Subway line/route filters: lists in metadata
    if subway_prefs.get("lines"):
        filter_dict["subway_lines"] = {"$in": [line.lower() for line in subway_prefs["lines"]]}
    if subway_prefs.get("routes"):
        filter_dict["subway_routes"] = {"$in": [route.lower() for route in subway_prefs["routes"]]}

    # Max distance filter: stored as float
    if subway_prefs.get("max_distance") is not None:
        filter_dict["subway_min_distance"] = {"$lte": float(subway_prefs["max_distance"])}

    return filter_dict

def build_pinecone_filter(amenities, neighborhoods, subway_prefs):
    filter_dict = {}

    # Amenities: list stored in metadata, query with $in
    if amenities:
        filter_dict["amenities"] = {"$in": [a.lower() for a in amenities]}

    # Neighborhood: stored as single string, still query with $in
    if neighborhoods:
        filter_dict["neighborhood"] = {"$in": [n.lower() for n in neighborhoods]}

    # Subway line/route filters: lists in metadata
    if subway_prefs.get("lines"):
        filter_dict["subway_lines"] = {"$in": [line.lower() for line in subway_prefs["lines"]]}
    if subway_prefs.get("routes"):
        filter_dict["subway_routes"] = {"$in": [route.lower() for route in subway_prefs["routes"]]}

    # Max distance filter: stored as float
    if subway_prefs.get("max_distance") is not None:
        filter_dict["subway_min_distance"] = {"$lte": float(subway_prefs["max_distance"])}

    return filter_dict

def combine_soft_with_hard(soft_filters: dict, hard_filters: dict):
    """
    Create filter dictionaries that combine exactly one soft filter key 
    with all hard filters.

    Args:
        soft_filters (dict): Dict of flexible (soft) filters.
        hard_filters (dict): Dict of strict (hard) filters.

    Returns:
        list[dict]: List of combined filter dicts.
    """
    combined_filters_list = []

    for key, value in soft_filters.items():
        # Start with hard filters
        combined = {**hard_filters}

        # Add just one soft filter key/value
        combined[key] = value

        combined_filters_list.append(combined)

    return combined_filters_list

async def apply_post_retrieval_filters(
    matches: List[Any],
    user_query: str,
    hard_filters: Dict[str, Any],
    amenities: Optional[List[str]] = None,
    neighborhoods: Optional[List[str]] = None,
    subway_prefs: Optional[Dict[str, Any]] = None,
    boost_weight: float = 1.0
) -> List[Dict[str, Any]]:
    """
    Post-retrieval filter + scoring applied to Pinecone matches.

    Hard filters = must match (from user query preferences)
    Soft filters = nice-to-have, boost score if matched.

    Returns:
        List of dicts: {
          id,
          metadata,
          pinecone_score,
          boost_score,
          combined_score
        }
    """

    # --- Parse filters if not provided ---
    if amenities is None:
        amenities = await parse_amenities(user_query)
    if neighborhoods is None:
        neighborhoods = await parse_neighborhoods(user_query)
    if subway_prefs is None:
        subway_prefs = await parse_subway_preferences(user_query)

    ## --- Build filter conditions ---
    
    # For now, no additional hard filters – everything is soft post-processing
    soft_filters = []

    if amenities:
        soft_filters.append({"amenities": {"$in": amenities}})
    if neighborhoods:
        soft_filters.extend([{"neighborhood": {"$eq": nb}} for nb in neighborhoods])
    if subway_prefs:
        if subway_prefs.get("routes"):
            soft_filters.append({"subway_routes": {"$in": subway_prefs["routes"]}})
        if subway_prefs.get("lines"):
            soft_filters.append({"subway_lines": {"$in": subway_prefs["lines"]}})
        if subway_prefs.get("max_distance") is not None:
            soft_filters.append({"subway_min_distance": {"$lte": subway_prefs["max_distance"]}})

    def match_condition(value, condition):
        if not isinstance(condition, dict):
            return value == condition
        for op, target in condition.items():
            if op == "$eq" and value != target:
                return False
            elif op == "$lt" and not (value < target):
                return False
            elif op == "$lte" and not (value <= target):
                return False
            elif op == "$gt" and not (value > target):
                return False
            elif op == "$gte" and not (value >= target):
                return False
            elif op == "$in":
                if isinstance(value, list):
                    if not any(v in target for v in value):
                        return False
                else:
                    if value not in target:
                        return False
            elif op == "$nin":
                if isinstance(value, list):
                    if any(v in target for v in value):
                        return False
                else:
                    if value in target:
                        return False
        return True

    def matches_filter(metadata: Dict[str, Any], filter_obj: Dict[str, Any]) -> bool:
        for key, condition in filter_obj.items():
            if key == "$or":
                if not any(matches_filter(metadata, sub_cond) for sub_cond in condition):
                    return False
            else:
                if key not in metadata or not match_condition(metadata[key], condition):
                    return False
        return True

    output = []

    for match in matches:
        metadata = match.metadata
        pinecone_score = getattr(match, "score", 0)

        # Hard filters gate (currently empty unless set above)
        if hard_filters and not matches_filter(metadata, hard_filters):
            continue

        # Boost score from soft filters
        boost_score = sum(1 for f in soft_filters if matches_filter(metadata, f))
        combined_score = pinecone_score + (boost_score * boost_weight)

        output.append({
            "id": getattr(match, "id", None),
            "metadata": metadata,
            "pinecone_score": pinecone_score,
            "boost_score": boost_score,
            "combined_score": combined_score
        })

    # Sort by combined score descending
    output.sort(key=lambda x: x["combined_score"], reverse=True)

    print(f"[INFO] Post-retrieval scoring: {len(matches)} -> {len(output)} kept")
    print(f"[INFO] Amenities={amenities}, Neighborhoods={neighborhoods}, Subway={subway_prefs}")
    return output