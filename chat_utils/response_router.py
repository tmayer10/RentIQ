import re
from typing import Literal


def decide_response_type(user_query: str) -> Literal["index_query", "general"]:
    """Heuristic router: decide if the user likely changed criteria (index_query)
    or is asking a general follow-up (general).
    """
    q = (user_query or "").lower()

    # Keywords that usually indicate new/updated search criteria
    update_patterns = [
        r"\b(change|switch|update|modify|expand|increase|decrease|raise|lower|bump|make it)\b",
        r"\b(add|remove|also needs|require|must have)\b",
        r"\bunder\s*\$\d+|\$\s*\d+|between\s*\$\d+\s*(?:and|to)\s*\$\d+\b",
        r"\b(\d+\s*(br|bed|bedrooms?|bath|ba|bathrooms?|sq\.?\s*ft|sqft|square\s+feet?)|studio)\b",
        r"\bzipcode\b|\b\d{5}\b",
        r"\b(near|close\s+to|within.*distance\s+of)\b.*\b(train|subway|line|routes?)\b",
    ]

    for pat in update_patterns:
        if re.search(pat, q):
            return "index_query"

    return "general"


