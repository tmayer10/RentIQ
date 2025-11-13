# Multi-Turn Conversation Strategy

This document explains the simple, intuitive strategy implemented for managing multi-turn conversations in RentIQ.

## Overview

The multi-turn conversation system intelligently decides when to retrieve new listings from Pinecone vs. when to reuse existing results, based on:
1. **Query type** (general follow-up vs. new search)
2. **Filter changes** (both hard and soft filters)
3. **Natural language cues** (keywords like "change", "instead", "find", "show me")

## Implementation (3 Phases)

### Phase 1: Complete Filter State Tracking ✅

**Problem Solved:** Previously, only hard filters (price, bedrooms, bathrooms, sqft, zipcode) were tracked. Changes to amenities, neighborhoods, or subway preferences went undetected, causing the system to incorrectly reuse old results.

**Changes Made:**

1. **rag_pipeline.py** (lines 275-283)
   - Now returns complete filter state including soft filters:
   ```python
   filter_state = {
       "hard": pinecone_filters,        # price, beds, baths, sqft, zip
       "amenities": amenities,          # gym, doorman, laundry, etc.
       "neighborhoods": neighborhoods,  # east-village, williamsburg, etc.
       "subway": subway_prefs           # routes, lines, max_distance
   }
   ```

2. **filters_change.py** (lines 24-64)
   - Updated `have_filters_changed()` to compare **all** filters:
     - Hard filters (price, beds, baths, sqft, zip)
     - Amenities (as sets)
     - Neighborhoods (as sets)
     - Subway preferences (routes, lines, max_distance)
   - Backward compatible with old format (just hard filters)

3. **chat_app.py** (lines 78, 82)
   - Stores and passes complete filter state between turns

**Result:** System now correctly detects when user changes ANY filter type.

**Example:**
```
Turn 1: "2br under $3000 with gym"
Turn 2: "I prefer one with a doorman instead"
→ Before: Reused old "gym" results ❌
→ After:  Retrieves new "doorman" results ✅
```

---

### Phase 2: Redis Session Store ✅

**Problem Solved:** Streamlit's in-memory session state is lost on page refresh and doesn't support multiple searches per session.

**Changes Made:**

1. **session_store.py** (new file)
   - Redis-backed session storage with graceful fallback
   - Stores per session:
     - Conversation history (`messages`)
     - Search history with IDs (`searches`)
     - Current active search context
   - Automatic TTL (1 hour default)
   - Key API methods:
     - `get_messages()`, `add_message()`, `clear_messages()`
     - `save_search()`, `get_search()`, `get_all_searches()`, `get_latest_search()`
     - `set_current_search_id()`, `get_current_search()`
     - `clear_session()`, `session_exists()`, `ping()`

2. **chat_app.py** (lines 13-59, 65-76, 101-166)
   - Integrates Redis with fallback to in-memory storage
   - Session ID generated per user (UUID)
   - Connection status shown in sidebar (✅ Redis connected / ⚠️ Redis unavailable)
   - All messages and searches automatically persisted to Redis
   - Retrieves previous filters and matches from Redis

3. **requirements.txt** (line 15)
   - Added `redis>=5.0.0`

4. **.env.example** (lines 18-19)
   - Added `REDIS_URL=redis://localhost:6379/0`

**Result:** Users can now:
- Resume conversations after page refresh
- Reference previous searches ("go back to the gym apartments")
- Have persistent session history across interactions

**Example Redis Keys:**
```
session:abc123:messages                   # List of messages
session:abc123:searches                   # List of search IDs
session:abc123:search:20250112_143052_123 # Individual search data
session:abc123:current_search_id          # Active search ID
```

---

### Phase 3: Simplified Clarifications ✅

**Problem Solved:** Previously, clarifications were shown when results < top_k // 2, which was noisy and unnecessary.

**Changes Made:**

1. **rag_pipeline.py** (lines 173-184)
   - Changed condition from `len(matches) < top_k // 2` to `len(matches) == 0`
   - Only shows clarification when **zero results** found
   - Provides more helpful message with specific suggestions

**Result:** Cleaner UX - clarifications only appear when truly needed.

**Example:**
```
Query: "15br apartment for $500"
Response: "I found no matches. Could you try specifying: budget or bedroom count?"
```

---

## Retrieval Decision Logic

The system uses a **multi-signal approach** to decide when to retrieve:

```python
# Retrieve new listings if:
should_retrieve = (
    is_first_turn OR                    # First message in conversation
    response_type == "index_query" OR   # Keywords detected: "change", "find", "show me", "instead"
    filters_changed                      # ANY filter changed (hard OR soft)
)

if should_retrieve:
    # Fetch from Pinecone with hybrid search
else:
    # Reuse previous matches from session
```

### Signal Sources:

1. **response_type** (response_router.py)
   - Detects keywords: "change", "switch", "update", "find", "show me", "instead", "actually"
   - Returns: `"index_query"` (new search) or `"general"` (follow-up)

2. **filters_changed** (filters_change.py)
   - Compares previous vs. current filter state
   - Checks: hard filters, amenities, neighborhoods, subway preferences

3. **is_first_turn**
   - True if no prior assistant messages exist

### Debug Logging:

Added to rag_pipeline.py (line 109):
```python
print(f"[DECISION] response_type={response_type}, filters_changed={filters_changed}, is_new_search={is_new_search}")
print(f"[ACTION] REUSING {len(previous_matches)} previous matches")  # or "RETRIEVING new matches"
```

---

## Natural Conversation Examples

### ✅ Reuse Results (General Follow-Up)

```
User: "Show me 2br apartments under $3000"
→ [Retrieves 5 results]

User: "Tell me more about the first one"
→ response_type: "general"
→ filters_changed: False
→ [REUSES previous 5 results]
```

```
User: "What's the neighborhood like for the second listing?"
→ [REUSES previous results]
```

### ✅ Retrieve New Results (Filter Change)

```
User: "Show me 2br apartments with gym"
→ [Retrieves 5 results]

User: "Change to 3br instead"
→ response_type: "index_query" (keyword: "change", "instead")
→ filters_changed: True (bedrooms changed)
→ [RETRIEVES new results]
```

```
User: "I prefer one with a doorman"
→ response_type: "general" (no strong keywords)
→ filters_changed: True (amenities changed: gym → doorman)
→ [RETRIEVES new results]
```

```
User: "Make it $3500"
→ response_type: "index_query" (keyword: "make it")
→ filters_changed: True (price changed)
→ [RETRIEVES new results]
```

---

## Setup Instructions

### 1. Install Redis (Local Development)

**macOS:**
```bash
brew install redis
brew services start redis
```

**Ubuntu/Debian:**
```bash
sudo apt-get install redis-server
sudo systemctl start redis
```

**Docker:**
```bash
docker run -d -p 6379:6379 redis:alpine
```

### 2. Update Environment

Add to your `.env` file:
```bash
REDIS_URL=redis://localhost:6379/0
```

### 3. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 4. Test Connection

```bash
cd chat_utils
python session_store.py
```

Expected output:
```
✅ Connected to Redis
📝 Messages: 2
  user: Show me 2br apartments under $3000...
  assistant: Here are 5 apartments matching your criteria...
🔍 Current search: Show me 2br apartments under $3000
   Matches: 2
🧹 Session cleared
```

### 5. Run Streamlit App

```bash
cd chat_utils
streamlit run chat_app.py
```

Sidebar will show:
- ✅ Redis connected (if Redis is running)
- ⚠️ Redis unavailable - using in-memory storage (if Redis is down)

---

## Graceful Fallback

If Redis is unavailable, the system **automatically falls back** to Streamlit's in-memory session state:
- No errors or crashes
- Basic functionality preserved
- Warning shown in sidebar
- Session data lost on page refresh (standard Streamlit behavior)

---

## Future Enhancements (Optional)

1. **Search History Browser**
   - Add sidebar widget to view all searches in current session
   - Allow user to jump back to previous searches by clicking

2. **Search Comparison**
   - Compare two searches side-by-side
   - Show filter differences

3. **Advanced Routing**
   - Use `is_new_search` signal in retrieval decision (currently only used for prompt formatting)
   - Add LLM-based intent classification for edge cases

4. **Filter Override Command**
   - `/update_filters <new criteria>` - explicit filter change command
   - Useful for power users

5. **Session Analytics**
   - Track search patterns
   - Identify common filter combinations
   - Measure retrieval efficiency (reuse rate)

---

## Key Files Modified

| File | Lines | Changes |
|------|-------|---------|
| `rag_pipeline.py` | 109, 275-283 | Debug logging, return complete filter state |
| `filters_change.py` | 24-64 | Compare soft filters, backward compatible |
| `chat_app.py` | 1-166 | Redis integration with fallback |
| `session_store.py` | NEW | Redis client wrapper |
| `requirements.txt` | 15 | Added redis>=5.0.0 |
| `.env.example` | 18-19 | Added REDIS_URL config |

---

## Summary

This simple, three-phase strategy provides:
- ✅ **Accurate retrieval decisions** - detects all filter changes (hard + soft)
- ✅ **Persistent session storage** - Redis-backed with graceful fallback
- ✅ **Clean UX** - clarifications only when needed
- ✅ **Natural conversations** - keyword-based intent detection
- ✅ **Debug visibility** - logged retrieval decisions
- ✅ **Production-ready** - backward compatible, graceful degradation

The system now intelligently balances retrieval efficiency (reusing results when appropriate) with accuracy (fetching new results when filters change), providing a smooth multi-turn conversation experience.
