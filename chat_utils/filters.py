# filters.py
import os
import json
import re
from typing import Dict, Tuple, Optional, Any
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def build_filter_extraction_prompt(user_query: str) -> str:
    return f"""
You are a structured filter extractor for a rental search RAG system.
Extract ONLY a valid JSON object representing filters compatible with a Pinecone metadata filter.

SCHEMA (allowed fields only):
- listing_id (string)
- price (number; use {{"$lt"}}, {{"$gt"}}, or {{"$eq"}})
- bedrooms (integer; use {{"$eq"}} unless a range is given)
- bathrooms (float; use {{"$eq"}} unless a range is given)
- sqft (integer)
- borough (string; e.g., {{"$eq": "manhattan"}} when specified)
- neighborhood (string or {{"$in": [..]}})
- zipcode (string)
- building_address (string)
- amenities ({{"$in": [lowercase strings]}})
- subway_lines ({{"$in": [lowercase strings]}})
- subway_routes ({{"$in": [lowercase strings]}})
- subway_min_distance (number in miles; {{"$lt"}} preferred)
- description (string)

REQUIREMENTS:
- Translate landmarks/universities (e.g., "nyu", "columbia university") into likely neighborhoods and/or boroughs and populate the neighborhood and/or borough fields accordingly. Do NOT output a "landmark" field.
- Normalize amenities to lowercase tokens that would plausibly appear in listing metadata; include close synonyms in the same $in list when ambiguous (e.g., ["laundry", "washer dryer", "washer_dryer"]).
- If the user mentions being near specific subway lines/routes or "within X miles of subway", set subway_routes/subway_lines and subway_min_distance accordingly.
- All strings must be lowercase. Use only the fields listed above.
- Output ONLY the JSON object; no comments or extra text.

EXAMPLES:
Query: "1br near columbia university under 3000 with laundry"
Output:
{{
  "price": {{"$lt": 3000}},
  "bedrooms": {{"$eq": 1}},
  "neighborhood": {{"$in": ["morningside heights", "upper west side"]}},
  "amenities": {{"$in": ["laundry", "washer dryer", "washer_dryer"]}}
}}

Query: "2br in manhattan within 0.5 miles of the f train, elevator"
Output:
{{
  "bedrooms": {{"$eq": 2}},
  "borough": {{"$eq": "manhattan"}},
  "subway_routes": {{"$in": ["f"]}},
  "subway_min_distance": {{"$lt": 0.5}},
  "amenities": {{"$in": ["elevator"]}}
}}

USER QUERY:
{user_query}

Now output ONLY the JSON filters.
"""


def _fallback_extract_basic_filters(user_query: str) -> Dict[str, Any]:
    """Deterministic minimal extraction when LLM JSON is invalid/empty.
    Captures budget, bedrooms/bathrooms, borough, and crude subway hints.
    """
    text = user_query.lower()
    filters: Dict[str, Any] = {}

    # price/budget
    m = re.search(r"(?:under|less than|<=|up to|upto|max(?:imum)?)[^\d]{0,10}(\$?\s*([\d,]+))", text)
    if m:
        val = float(m.group(2).replace(",", ""))
        filters["price"] = {"$lt": val}
    else:
        m = re.search(r"\$\s*([\d,]+)", text)
        if m:
            filters["price"] = {"$lt": float(m.group(1).replace(",", ""))}

    # bedrooms
    m = re.search(r"(\d+(?:\.0)?)\s*(?:br|bed|bedroom|bedrooms)\b", text)
    if m:
        try:
            filters["bedrooms"] = {"$eq": int(float(m.group(1)))}
        except ValueError:
            pass

    # bathrooms
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:ba|bath|bathroom|bathrooms)\b", text)
    if m:
        try:
            filters["bathrooms"] = {"$eq": float(m.group(1))}
        except ValueError:
            pass

    # borough mentions
    for b in ["manhattan", "brooklyn", "queens", "bronx", "staten island"]:
        if re.search(rf"\b{re.escape(b)}\b", text):
            filters["borough"] = {"$eq": b}
            break

    # subway proximity (miles)
    m = re.search(r"within\s*(\d+(?:\.\d+)?)\s*miles?\s*(?:of|from)?\s*(?:the\s*)?subway", text)
    if m:
        try:
            filters["subway_min_distance"] = {"$lt": float(m.group(1))}
        except ValueError:
            pass

    # subway route letter(s) or numbers
    routes = re.findall(r"\b([a-z0-9])\s*train\b", text)
    if routes:
        filters["subway_routes"] = {"$in": [r.lower() for r in routes]}

    return filters


def _build_clarification_from_missing(filters: Dict[str, Any]) -> Optional[str]:
    needed = []
    if "price" not in filters:
        needed.append("budget (max monthly rent)")
    if "bedrooms" not in filters:
        needed.append("number of bedrooms")
    if "neighborhood" not in filters and "borough" not in filters:
        needed.append("preferred neighborhoods or landmarks (e.g., near nyu/columbia)")
    if "amenities" not in filters:
        needed.append("must-have amenities (elevator, laundry/washer dryer, doorman)")
    if "subway_routes" not in filters and "subway_min_distance" not in filters:
        needed.append("subway lines and distance (e.g., f train, within 0.5 miles)")

    if not needed:
        return None

    if len(needed) == 1:
        body = needed[0]
    else:
        body = ", ".join(needed[:-1]) + " and " + needed[-1]

    return f"Quick clarification: could you share your {body}?"


def process_user_query(user_query: str) -> Tuple[Dict[str, Any], Optional[str]]:
    """Return (filters, clarification).
    Clarification is a short question when extracted filters are empty or sparse.
    """
    prompt = build_filter_extraction_prompt(user_query)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    filters: Dict[str, Any] = {}
    try:
        candidate = json.loads(resp.choices[0].message.content)
        if isinstance(candidate, dict):
            filters = candidate
    except json.JSONDecodeError:
        print("[WARN] Invalid filter JSON. Falling back to heuristics.")

    if not filters:
        filters = _fallback_extract_basic_filters(user_query)

    # Normalize to Pinecone-compatible structure
    filters = _normalize_pinecone_filter(filters)

    clarification = None
    minimal_keys = {"price", "bedrooms", "borough", "neighborhood", "amenities", "subway_routes", "subway_min_distance"}
    if not filters or len(set(filters.keys()) & minimal_keys) <= 1:
        clarification = _build_clarification_from_missing(filters)

    return filters, clarification


def _normalize_pinecone_filter(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce extracted filters into Pinecone-compatible filter dict.
    - Lowercase strings
    - Ensure operators are one of $eq, $lt, $lte, $gt, $gte, $in
    - Coerce scalars to $eq and lists to $in for array-like fields
    - Drop unsupported fields
    """
    allowed_fields = {
        "listing_id", "price", "bedrooms", "bathrooms", "sqft",
        "borough", "neighborhood", "zipcode", "building_address",
        "amenities", "subway_lines", "subway_routes", "subway_min_distance",
        "description",
    }

    def to_lower_str(x: Any) -> str:
        return str(x).strip().lower()

    def norm_scalar(value: Any):
        if isinstance(value, str):
            return {"$eq": to_lower_str(value)}
        return {"$eq": value}

    def norm_list(value: Any):
        if isinstance(value, dict) and "$in" in value:
            vals = value["$in"] if isinstance(value["$in"], list) else [value["$in"]]
        elif isinstance(value, list):
            vals = value
        else:
            vals = [value]
        return {"$in": [to_lower_str(v) for v in vals if v is not None]}

    normalized: Dict[str, Any] = {}

    for key, value in filters.items():
        if key not in allowed_fields:
            continue

        if key in {"price", "sqft", "bedrooms", "bathrooms"}:
            if isinstance(value, dict):
                rng = {}
                for op in ("$eq", "$lt", "$lte", "$gt", "$gte"):
                    if op in value and value[op] is not None:
                        try:
                            if key in {"price", "sqft", "bathrooms"}:
                                rng[op] = float(value[op])
                            else:
                                rng[op] = int(float(value[op]))
                        except (ValueError, TypeError):
                            pass
                if rng:
                    normalized[key] = rng
                    continue
            normalized[key] = norm_scalar(value)
            continue

        if key in {"listing_id", "borough", "zipcode", "building_address", "description"}:
            normalized[key] = norm_scalar(value)
            continue

        if key == "neighborhood":
            if isinstance(value, dict) and "$in" in value:
                normalized[key] = norm_list(value)
            elif isinstance(value, list):
                normalized[key] = norm_list(value)
            else:
                normalized[key] = norm_scalar(value)
            continue

        if key in {"amenities", "subway_lines", "subway_routes"}:
            normalized[key] = norm_list(value)
            continue

        if key == "subway_min_distance":
            if isinstance(value, dict):
                rng = {}
                for op in ("$lt", "$lte", "$gt", "$gte", "$eq"):
                    if op in value and value[op] is not None:
                        try:
                            rng[op] = float(value[op])
                        except (ValueError, TypeError):
                            pass
                if rng:
                    normalized[key] = rng
                else:
                    try:
                        normalized[key] = {"$lt": float(value)}
                    except (ValueError, TypeError):
                        pass
            else:
                try:
                    normalized[key] = {"$lt": float(value)}
                except (ValueError, TypeError):
                    pass
            continue

    return normalized