# pinecone_filters.py
"""
Simple Pinecone metadata pre-filtering for numeric/easy-to-extract fields.
Only handles: price, bedrooms, bathrooms, sqft, zipcode
"""

import os
import json
import re
import asyncio
from typing import Dict, Any, Tuple, Optional, Literal
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from rate_limiter import call_llm_with_limit

load_dotenv()
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Lazy import for Google - only when needed
_google_genai = None
_google_types = None

def _get_google_client():
    """Lazy import and initialization of Google GenAI client."""
    global _google_genai, _google_types
    if _google_genai is None:
        try:
            from google import genai
            from google.genai import types
            _google_genai = genai
            _google_types = types
        except ImportError as e:
            raise ImportError(
                "Failed to import 'genai' from 'google'. "
                "Please ensure 'google-genai' package is installed: pip install google-genai>=1.0.0. "
                "If running in Docker, rebuild the image: docker-compose build --no-cache"
            ) from e
    return _google_genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))


# Simpler approach: separate models for each operator type
class PriceFilter(BaseModel):
    """Price filter with single operator and value."""
    operator: Literal["eq", "lt", "lte", "gt", "gte"] = Field(description="The comparison operator")
    value: float = Field(description="The price value in dollars")


class SqftFilter(BaseModel):
    """Square footage filter with single operator and value."""
    operator: Literal["eq", "lt", "lte", "gt", "gte"] = Field(description="The comparison operator")
    value: int = Field(description="The square footage value")


class PineconeFiltersResponse(BaseModel):
    """Structured response for Pinecone filters."""
    price: Optional[PriceFilter] = Field(default=None, description="Price filter. Only set if user mentions price/budget. Use 'lt' for 'under', 'gte' for 'at least'.")
    bedrooms: Optional[int] = Field(default=None, description="Exact number of bedrooms. Set to 0 for studio, null if not mentioned.")
    bathrooms: Optional[float] = Field(default=None, description="Exact number of bathrooms. Null if not mentioned.")
    sqft: Optional[SqftFilter] = Field(default=None, description="Square footage filter. Only set if user mentions sqft/size. Use 'gte' for 'at least'.")
    zipcode: Optional[str] = Field(default=None, description="NYC zipcode (5 digits). Null if not mentioned.")


def build_pinecone_filter_prompt(user_query: str) -> str:
    """Build prompt for extracting simple numeric filters only."""
    return f"""Extract ONLY the filters explicitly mentioned in the user's query. Leave unmentioned fields as null.

OPERATOR MAPPING:
- "under $3000" / "max $3000" → price: {{operator: "lt", value: 3000}}
- "at least $2000" / "min $2000" → price: {{operator: "gte", value: 2000}}
- "exactly $2500" → price: {{operator: "eq", value: 2500}}
- "at least 800 sqft" → sqft: {{operator: "gte", value: 800}}
- "studio" → bedrooms: 0

DO NOT extract neighborhoods, amenities, or subway info.

EXAMPLES:

"2br under $3000" →
{{
  "bedrooms": 2,
  "price": {{"operator": "lt", "value": 3000}},
  "bathrooms": null,
  "sqft": null,
  "zipcode": null
}}

"Looking for a 2 bedroom apartment under $3000 with a gym and near the A train" →
{{
  "bedrooms": 2,
  "price": {{"operator": "lt", "value": 3000}},
  "bathrooms": null,
  "sqft": null,
  "zipcode": null
}}

"studio under $2500 in zipcode 10001" →
{{
  "bedrooms": 0,
  "price": {{"operator": "lt", "value": 2500}},
  "bathrooms": null,
  "sqft": null,
  "zipcode": "10001"
}}

"1br, 1ba, at least 800 sqft, max $4000" →
{{
  "bedrooms": 1,
  "bathrooms": 1.0,
  "sqft": {{"operator": "gte", "value": 800}},
  "price": {{"operator": "lt", "value": 4000}},
  "zipcode": null
}}

"3br with laundry near F train" →
{{
  "bedrooms": 3,
  "price": null,
  "bathrooms": null,
  "sqft": null,
  "zipcode": null
}}

User query: "{user_query}"

Extract ONLY mentioned filters."""


async def extract_pinecone_filters(user_query: str, provider: Literal["google", "openai"] = "google") -> Dict[str, Any]:
    """
    Extract simple Pinecone metadata filters (price, bed, bath, sqft, zipcode only).
    Uses Pydantic models for structured output.
    
    Args:
        user_query: The user's search query
        provider: Which LLM provider to use ('google' or 'openai'), default 'google'
    
    Returns:
        Dict with Pinecone-compatible filter structure
    """
    prompt = build_pinecone_filter_prompt(user_query)
    
    try:
        if provider == "google":
            client = _get_google_client()
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=_google_types.GenerateContentConfig(
                    system_instruction="""You are an expert at extracting structured data from user queries.
                    You always respond with valid JSON that adheres to the provided schema.""",
                    response_mime_type="application/json",
                    response_schema=PineconeFiltersResponse,
                ),
            )
            parsed = response.parsed
        else:  # openai
            response = openai_client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an expert at extracting structured data from user queries. You always respond with valid JSON that adheres to the provided schema."},
                    {"role": "user", "content": prompt}
                ],
                response_format=PineconeFiltersResponse,
                temperature=0
            )
            parsed = response.choices[0].message.parsed

        # Convert Pydantic model to Pinecone filter dict with mention gating and range handling
        filters = _pydantic_to_pinecone_filters(parsed, user_query)
        return filters
        
    except Exception as e:
        print(f"[WARN] Pinecone filter extraction failed: {e}. Falling back to regex.")
        return _fallback_extract_pinecone_filters(user_query)


def _pydantic_to_pinecone_filters(parsed: PineconeFiltersResponse, user_query: str) -> Dict[str, Any]:
    """Convert Pydantic model to Pinecone filter dict with strict mention gating.
    Only include a field if the user explicitly mentioned it in the query.
    Also handles explicit price ranges like "between $X and $Y".
    """
    text = user_query.lower()

    def mentioned_price() -> bool:
        return bool(re.search(r"\$\s*\d|\b(price|budget|max|under|over|between|upto|up to)\b", text))

    def mentioned_bedrooms() -> bool:
        return bool(re.search(r"\bstudio\b|\b\d+\s*(br|bed|bedroom|bedrooms)\b", text))

    def mentioned_bathrooms() -> bool:
        return bool(re.search(r"\b\d+(?:\.\d+)?\s*(ba|bath|bathroom|bathrooms)\b", text))

    def mentioned_sqft() -> bool:
        return bool(re.search(r"\b\d+\s*(sq\.?\s*ft|sqft|square\s*feet|sf)\b|\b(sqft|square\s*feet)\b", text))

    def extract_zipcode() -> Optional[str]:
        m = re.search(r"\b(10\d{3})\b", text)
        return m.group(1) if m else None

    def extract_price_range() -> Optional[Dict[str, float]]:
        # between $X and $Y
        m = re.search(r"between\s*\$?\s*([\d,]+)\s*(?:and|to)\s*\$?\s*([\d,]+)", text)
        if m:
            lo = float(m.group(1).replace(",", ""))
            hi = float(m.group(2).replace(",", ""))
            if lo > hi:
                lo, hi = hi, lo
            return {"$gte": lo, "$lte": hi}
        return None

    filters: Dict[str, Any] = {}

    # Bedrooms (exact) - require explicit mention
    if mentioned_bedrooms() and parsed.bedrooms is not None:
        filters["bedrooms"] = {"$eq": parsed.bedrooms}

    # Bathrooms (exact) - require explicit mention and non-zero
    if mentioned_bathrooms() and parsed.bathrooms is not None and parsed.bathrooms != 0:
        filters["bathrooms"] = {"$eq": parsed.bathrooms}

    # Price - require explicit mention; support explicit ranges from text
    if mentioned_price():
        range_filter = extract_price_range()
        if range_filter:
            filters["price"] = range_filter
        elif parsed.price:
            # Map single operator
            filters["price"] = {f"${parsed.price.operator}": parsed.price.value}

    # Sqft - require explicit mention and non-zero
    if mentioned_sqft() and parsed.sqft and parsed.sqft.value not in (None, 0):
        filters["sqft"] = {f"${parsed.sqft.operator}": int(parsed.sqft.value)}

    # Zipcode - require explicit presence of a valid zipcode in text
    zc = extract_zipcode()
    if zc:
        filters["zipcode"] = {"$eq": zc}

    return filters


def _normalize_pinecone_filters(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure filters are valid Pinecone operators."""
    allowed_fields = {"price", "bedrooms", "bathrooms", "sqft", "zipcode"}
    normalized = {}
    
    for key, value in filters.items():
        if key not in allowed_fields:
            continue
        
        # Numeric fields
        if key in {"price", "sqft"}:
            if isinstance(value, dict):
                rng = {}
                for op in ("$eq", "$lt", "$lte", "$gt", "$gte"):
                    if op in value and value[op] is not None:
                        try:
                            rng[op] = float(value[op])
                        except (ValueError, TypeError):
                            pass
                if rng:
                    normalized[key] = rng
            else:
                try:
                    normalized[key] = {"$eq": float(value)}
                except (ValueError, TypeError):
                    pass
        
        # Integer fields
        elif key == "bedrooms":
            if isinstance(value, dict):
                rng = {}
                for op in ("$eq", "$lt", "$lte", "$gt", "$gte"):
                    if op in value and value[op] is not None:
                        try:
                            rng[op] = int(float(value[op]))
                        except (ValueError, TypeError):
                            pass
                if rng:
                    normalized[key] = rng
            else:
                try:
                    normalized[key] = {"$eq": int(float(value))}
                except (ValueError, TypeError):
                    pass
        
        # Float fields
        elif key == "bathrooms":
            if isinstance(value, dict):
                rng = {}
                for op in ("$eq", "$lt", "$lte", "$gt", "$gte"):
                    if op in value and value[op] is not None:
                        try:
                            rng[op] = float(value[op])
                        except (ValueError, TypeError):
                            pass
                if rng:
                    normalized[key] = rng
            else:
                try:
                    normalized[key] = {"$eq": float(value)}
                except (ValueError, TypeError):
                    pass
        
        # String fields
        elif key == "zipcode":
            if isinstance(value, dict) and "$eq" in value:
                normalized[key] = {"$eq": str(value["$eq"])}
            else:
                normalized[key] = {"$eq": str(value)}
    
    return normalized


def _fallback_extract_pinecone_filters(user_query: str) -> Dict[str, Any]:
    """Regex-based fallback extraction for simple filters."""
    text = user_query.lower()
    filters = {}
    
    # Price
    m = re.search(r"(?:under|less than|<=|up to|max(?:imum)?)[^\d]{0,10}\$?\s*([\d,]+)", text)
    if m:
        try:
            filters["price"] = {"$lt": float(m.group(1).replace(",", ""))}
        except ValueError:
            pass
    else:
        m = re.search(r"\$\s*([\d,]+)", text)
        if m:
            try:
                filters["price"] = {"$lt": float(m.group(1).replace(",", ""))}
            except ValueError:
                pass
    
    # Bedrooms
    if "studio" in text:
        filters["bedrooms"] = {"$eq": 0}
    else:
        m = re.search(r"(\d+)\s*(?:br|bed|bedroom|bedrooms)\b", text)
        if m:
            try:
                filters["bedrooms"] = {"$eq": int(m.group(1))}
            except ValueError:
                pass
    
    # Bathrooms
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:ba|bath|bathroom|bathrooms)\b", text)
    if m:
        try:
            filters["bathrooms"] = {"$eq": float(m.group(1))}
        except ValueError:
            pass
    
    # Sqft
    m = re.search(r"(\d+)\s*(?:sq\.?\s*ft|sqft|square feet)", text)
    if m:
        try:
            filters["sqft"] = {"$eq": int(m.group(1))}
        except ValueError:
            pass
    
    # Zipcode
    m = re.search(r"\b(10\d{3})\b", text)  # NYC zipcodes start with 10
    if m:
        filters["zipcode"] = {"$eq": m.group(1)}
    
    return _normalize_pinecone_filters(filters)

