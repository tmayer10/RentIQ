# pinecone_filters.py
"""
Simple Pinecone metadata pre-filtering for numeric/easy-to-extract fields.
Only handles: price, bedrooms, bathrooms, sqft, zipcode
"""

import os
import json
import re
from typing import Dict, Any, Tuple, Optional
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# Pydantic models for structured output
class NumericFilter(BaseModel):
    """Numeric filter with operator."""
    eq: Optional[float] = Field(None, description="Equals value")
    lt: Optional[float] = Field(None, description="Less than value")
    lte: Optional[float] = Field(None, description="Less than or equal value")
    gt: Optional[float] = Field(None, description="Greater than value")
    gte: Optional[float] = Field(None, description="Greater than or equal value")


class PineconeFiltersResponse(BaseModel):
    """Structured response for Pinecone filters."""
    price: Optional[NumericFilter] = Field(None, description="Price filter in dollars")
    bedrooms: Optional[int] = Field(None, description="Exact number of bedrooms (use null for studio=0)")
    bathrooms: Optional[float] = Field(None, description="Exact number of bathrooms")
    sqft: Optional[NumericFilter] = Field(None, description="Square footage filter")
    zipcode: Optional[str] = Field(None, description="NYC zipcode (5 digits starting with 10)")


def build_pinecone_filter_prompt(user_query: str) -> str:
    """Build prompt for extracting simple numeric filters only."""
    return f"""Extract ONLY these simple numeric/string filters from the user's query:
- price: Use eq, lt, lte, gt, or gte fields
- bedrooms: Exact count (studio = 0)
- bathrooms: Exact count  
- sqft: Use eq, lt, lte, gt, or gte fields
- zipcode: 5-digit NYC zipcode

DO NOT extract neighborhoods, amenities, or subway info.

EXAMPLES:
- "2br under $3000" → bedrooms=2, price.lt=3000
- "1br, 1ba, at least 800 sqft, max $4000" → bedrooms=1, bathrooms=1, sqft.gt=800, price.lt=4000
- "studio under $2500 in zipcode 10001" → bedrooms=0, price.lt=2500, zipcode="10001"
- "3br with laundry near F train" → bedrooms=3

User query: "{user_query}"

Extract filters using the structured format."""


def extract_pinecone_filters(user_query: str) -> Dict[str, Any]:
    """
    Extract simple Pinecone metadata filters (price, bed, bath, sqft, zipcode only).
    Uses Pydantic models for structured output.
    
    Returns:
        Dict with Pinecone-compatible filter structure
    """
    prompt = build_pinecone_filter_prompt(user_query)
    
    try:
        completion = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format=PineconeFiltersResponse,
            temperature=0
        )
        
        parsed = completion.choices[0].message.parsed
        
        # Convert Pydantic model to Pinecone filter dict
        filters = _pydantic_to_pinecone_filters(parsed)
        return filters
        
    except Exception as e:
        print(f"[WARN] Pinecone filter extraction failed: {e}. Falling back to regex.")
        return _fallback_extract_pinecone_filters(user_query)


def _pydantic_to_pinecone_filters(parsed: PineconeFiltersResponse) -> Dict[str, Any]:
    """Convert Pydantic model to Pinecone filter dict."""
    filters = {}
    
    # Price filter
    if parsed.price:
        price_filter = {}
        if parsed.price.eq is not None:
            price_filter["$eq"] = parsed.price.eq
        if parsed.price.lt is not None:
            price_filter["$lt"] = parsed.price.lt
        if parsed.price.lte is not None:
            price_filter["$lte"] = parsed.price.lte
        if parsed.price.gt is not None:
            price_filter["$gt"] = parsed.price.gt
        if parsed.price.gte is not None:
            price_filter["$gte"] = parsed.price.gte
        if price_filter:
            filters["price"] = price_filter
    
    # Bedrooms (exact match)
    if parsed.bedrooms is not None:
        filters["bedrooms"] = {"$eq": parsed.bedrooms}
    
    # Bathrooms (exact match)
    if parsed.bathrooms is not None:
        filters["bathrooms"] = {"$eq": parsed.bathrooms}
    
    # Sqft filter
    if parsed.sqft:
        sqft_filter = {}
        if parsed.sqft.eq is not None:
            sqft_filter["$eq"] = int(parsed.sqft.eq)
        if parsed.sqft.lt is not None:
            sqft_filter["$lt"] = int(parsed.sqft.lt)
        if parsed.sqft.lte is not None:
            sqft_filter["$lte"] = int(parsed.sqft.lte)
        if parsed.sqft.gt is not None:
            sqft_filter["$gt"] = int(parsed.sqft.gt)
        if parsed.sqft.gte is not None:
            sqft_filter["$gte"] = int(parsed.sqft.gte)
        if sqft_filter:
            filters["sqft"] = sqft_filter
    
    # Zipcode
    if parsed.zipcode:
        filters["zipcode"] = {"$eq": parsed.zipcode}
    
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

