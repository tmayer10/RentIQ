# RentIQ Chat Utils - Two-Tier Filtering System

## Quick Start

```python
from rag_pipeline import rag_search

# Simple usage
llm_output, matches, clarification = rag_search(
    user_query="2br in East Village with laundry under $3500",
    top_k=5,
    chat_history=[],
    is_first_turn=True
)
```

## File Overview

### Core Pipeline
- **`chat_app.py`** - Streamlit UI
- **`rag_pipeline.py`** - Main RAG orchestration (two-tier filtering)
- **`rewriter.py`** - Multi-turn query rewriting
- **`vectorstore.py`** - Pinecone hybrid search

### Two-Tier Filtering
- **`pinecone_filters.py`** - Tier 1: Simple pre-filters (price, bed, bath, sqft, zip)
- **`post_filters.py`** - Tier 2: Semantic post-filters (neighborhoods, amenities, subway)
- **`allowable_values.py`** - Canonical lists and synonyms

### Database & Ingestion
- **`chatdb.py`** - PostgreSQL connection and queries
- **`ingest.py`** - Pinecone ingestion pipeline
- **`utils.py`** - Utility functions

### Legacy (Reference Only)
- **`filters.py`** - Old single-tier filtering (kept for reference)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      User Query                             │
│           "2br in East Village with laundry                 │
│            near F train under $3500"                        │
└─────────────────────────────────────────────────────────────┘
                           │
                           ↓
┌─────────────────────────────────────────────────────────────┐
│              Query Rewriter (rewriter.py)                   │
│  - Resolves pronouns from chat history                      │
│  - Creates standalone query                                 │
└─────────────────────────────────────────────────────────────┘
                           │
                           ↓
        ┌──────────────────┴──────────────────┐
        │                                     │
        ↓                                     ↓
┌────────────────────┐              ┌────────────────────────┐
│ TIER 1: PINECONE   │              │  TIER 2: PARSE         │
│ (pinecone_filters) │              │  (post_filters)        │
├────────────────────┤              ├────────────────────────┤
│ Extract:           │              │ Parse:                 │
│ • price: $lt 3500  │              │ • neighborhoods:       │
│ • bedrooms: $eq 2  │              │   ["east-village"]     │
│                    │              │ • amenities:           │
│ Simple, Fast       │              │   ["laundry",          │
│                    │              │    "washer_dryer"]     │
│                    │              │ • subway:              │
│                    │              │   routes: ["f"]        │
│                    │              │   max_dist: 0.5        │
│                    │              │                        │
│                    │              │ LLM-Assisted,          │
│                    │              │ Semantic               │
└────────────────────┘              └────────────────────────┘
        │                                     │
        ↓                                     │
┌─────────────────────────────────────────────────────────────┐
│          Pinecone Hybrid Search (vectorstore.py)            │
│  - Dense + Sparse vectors                                   │
│  - Metadata filter: {bedrooms: 2, price: <3500}             │
│  - Over-fetch: top_k × 3 = 15 results                       │
└─────────────────────────────────────────────────────────────┘
                           │
                           ↓
┌─────────────────────────────────────────────────────────────┐
│         Apply Post-Retrieval Filters (post_filters.py)      │
│                                                              │
│  For each of 15 matches:                                    │
│    ✓ neighborhood in ["east-village"]?                      │
│    ✓ has "laundry" OR "washer_dryer"?                       │
│    ✓ has "f" in subway_routes?                              │
│    ✓ subway_min_distance < 0.5?                             │
│                                                              │
│  Result: 15 → 7 matches pass all filters                    │
└─────────────────────────────────────────────────────────────┘
                           │
                           ↓
┌─────────────────────────────────────────────────────────────┐
│              Trim to Final top_k = 5                        │
└─────────────────────────────────────────────────────────────┘
                           │
                           ↓
┌─────────────────────────────────────────────────────────────┐
│         LLM Generation (rag_pipeline.py)                    │
│  - First turn: Ranked list template                         │
│  - Follow-up: Conversational tone                           │
│  - Grounded in retrieved listings                           │
└─────────────────────────────────────────────────────────────┘
                           │
                           ↓
                   Final Response
```

## Key Functions

### `rag_search(user_query, top_k, chat_history, is_first_turn)`
Main entry point. Returns `(llm_output, matches, clarification)`.

### `extract_pinecone_filters(query)`
Tier 1: Extract simple numeric filters.
```python
from pinecone_filters import extract_pinecone_filters

filters = extract_pinecone_filters("2br under $3000")
# Returns: {"bedrooms": {"$eq": 2}, "price": {"$lt": 3000}}
```

### `parse_amenities(query)`
Tier 2: Extract amenities with synonym expansion.
```python
from post_filters import parse_amenities

amenities = parse_amenities("with laundry and doorman")
# Returns: ["laundry", "washer_dryer", "doorman", "full_time_doorman", "part_time_doorman"]
```

### `parse_neighborhoods(query)`
Tier 2: Extract neighborhoods, handle landmarks.
```python
from post_filters import parse_neighborhoods

neighborhoods = parse_neighborhoods("near NYU")
# Returns: ["east-village", "greenwich-village", "noho"]
```

### `parse_subway_preferences(query)`
Tier 2: Extract subway routes, lines, distances.
```python
from post_filters import parse_subway_preferences

subway = parse_subway_preferences("near F train within 0.3 miles")
# Returns: {"routes": ["f"], "lines": [], "max_distance": 0.3}
```

### `apply_post_retrieval_filters(matches, query, amenities, neighborhoods, subway_prefs)`
Apply all Tier 2 filters to matches.

## Configuration

### Over-Fetch Multiplier

Adjust in `rag_pipeline.py`:
```python
retrieval_k = top_k * 3  # Increase if too few results after filtering
```

### Allowable Values

Update `allowable_values.py` to add:
- New amenities
- New neighborhoods
- Amenity synonyms
- Neighborhood aliases

## Testing

Run individual components:

```python
# Test Tier 1
from pinecone_filters import extract_pinecone_filters
print(extract_pinecone_filters("2br under $3000"))

# Test Tier 2 - Amenities
from post_filters import parse_amenities
print(parse_amenities("with gym and parking"))

# Test Tier 2 - Neighborhoods
from post_filters import parse_neighborhoods
print(parse_neighborhoods("near Columbia University"))

# Test Tier 2 - Subway
from post_filters import parse_subway_preferences
print(parse_subway_preferences("within 0.5 miles of the A train"))

# Full pipeline
from rag_pipeline import rag_search
output, matches, clarification = rag_search(
    "2br in UES with gym under $5000",
    top_k=5,
    is_first_turn=True
)
print(f"Found {len(matches)} matches")
print(output)
```

## Logs

Monitor filtering effectiveness:
```
[INFO] Post-filter: 15 -> 5 matches
[INFO] Filters applied: amenities=['laundry', 'washer_dryer'], 
       neighborhoods=['east-village'], 
       subway={'routes': ['f'], 'max_distance': 0.5}
```

## See Also

- **`../TWO_TIER_FILTER_ARCHITECTURE.md`** - Detailed architecture docs
- **`../MIGRATION_GUIDE.md`** - Migration from old system
- **`../SEARCH_UPDATE_SCENARIOS.md`** - Multi-turn conversation examples (if exists)

