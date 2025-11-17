# rag_pipeline.py
import os
from openai import OpenAI
from vectorstore import hybrid_search, parallel_hybrid_search
from rewriter import rewrite_query
from pinecone_filters import extract_pinecone_filters
from post_filters import (apply_post_retrieval_filters, parse_amenities, parse_neighborhoods, parse_subway_preferences,
                          build_pinecone_filter, combine_soft_with_hard)
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from rate_limiter import call_llm_with_limit
import asyncio
from response_router import decide_response_type
from filters_change import have_filters_changed
from scorer import score_listings
from pydantic import BaseModel, Field
from typing import List, Optional

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# Pydantic models for structured listing recommendations
class ListingRecommendation(BaseModel):
    """Structured representation of a single listing recommendation."""
    listing_id: str = Field(description="The listing ID (e.g., '4883693')")
    price: float = Field(description="The monthly rent price")
    bedrooms: int = Field(description="Number of bedrooms")
    bathrooms: float = Field(description="Number of bathrooms")
    neighborhood: str = Field(description="Neighborhood name")
    amenities: List[str] = Field(default_factory=list, description="List of amenities")
    summary: str = Field(description="Brief summary explaining why this listing matches the user's needs")


class StructuredListingResponse(BaseModel):
    """Structured response for new search queries with ranked listings."""
    listings: List[ListingRecommendation] = Field(
        default_factory=list,
        description="Ranked list of listing recommendations from most to least relevant"
    )
    final_recommendation: Optional[str] = Field(
        None,
        description="Brief final recommendation or summary (optional)"
    )


class ConversationalResponse(BaseModel):
    """Structured response for conversational follow-ups."""
    response: str = Field(description="Natural conversational response to the user's query")
    referenced_listing_ids: List[str] = Field(
        default_factory=list,
        description="List of listing IDs mentioned in the response (if any)"
    )


def format_listings(matches):
    """Convert matches from Pinecone into a neat text block for LLM context."""
    formatted = []
    for rank, m in enumerate(matches, start=1):
        md = m['metadata']
        formatted.append(
            f"{rank}. ID: {md.get('listing_id')}\n"
            f"   Price: ${md.get('price')}\n"
            f"   Bedrooms: {md.get('bedrooms')}, Bathrooms: {md.get('bathrooms')}\n"
            f"   Neighborhood: {md.get('neighborhood')}, Borough: {md.get('borough')}\n"
            f"   Amenities: {', '.join(md.get('amenities', []))}\n"
            f"   Description: {md.get('description')}\n"
        )
    return "\n".join(formatted)


def _detect_new_search_intent(user_query: str, chat_history) -> bool:
    """Detect if the user is requesting a new/updated search vs. asking about existing results."""
    if not chat_history:
        return True
    
    # Keywords that suggest the user wants NEW results (not discussing prior ones)
    new_search_indicators = [
        r'\b(change|switch|update|modify|instead|actually|new search|different|replace)\b',
        r'\b(show me|find|search for|look for|i want|i need)\b',
        r'\b(increase|decrease|raise|lower)\s+(budget|price|bedrooms?|baths?)',
        r'\bmake it\b',
    ]
    
    import re
    query_lower = user_query.lower()
    for pattern in new_search_indicators:
        if re.search(pattern, query_lower):
            return True
    
    return False


async def rag_search(
    user_query: str,
    top_k=5,
    chat_history=None,
    is_first_turn: bool = False,
    previous_filters: dict = None,
    previous_matches=None,
):
    """Full RAG with optional chat history.

    Retrieves listings for the current user query and asks the LLM to provide
    recommendations, taking prior conversation turns into account when provided.
    """
    # Step -1: Detect if user wants a new search (overrides is_first_turn for formatting)
    is_new_search = is_first_turn or _detect_new_search_intent(user_query, chat_history)
    
    # Step 0: Rewrite follow-up into standalone query
    standalone_query = rewrite_query(user_query, chat_history or [])

    # Step 1: Extract simple Pinecone pre-filters (price, bed, bath, sqft, zipcode ONLY)
    pinecone_filters = await extract_pinecone_filters(standalone_query)
    
    # Step 1.5: Decide response type (general vs index_query)
    response_type = decide_response_type(user_query)

    # Step 1.6: Determine if filters changed relative to previous
    filters_changed = have_filters_changed(previous_filters or {}, pinecone_filters or {})
    
    # Step 2: Parse post-retrieval filter criteria (neighborhoods, amenities, subway) concurrently
    try:
        amenities, neighborhoods, subway_prefs = await asyncio.gather(
            parse_amenities(standalone_query),
            parse_neighborhoods(standalone_query),
            parse_subway_preferences(standalone_query)
        )

        # Defaults if any come back as None
        amenities = amenities or []
        neighborhoods = neighborhoods or []
        subway_prefs = subway_prefs or {}

    except Exception as e:
        print(f"[WARN] Post-filter parsing error: {e}")
        # Fallback defaults
        amenities = []
        neighborhoods = []
        subway_prefs = {}

    # Step 3: Retrieve from Pinecone using simple pre-filters (fetch more for post-filtering)
    # Reuse prior matches if response is general and filters didn't change
    print(f"[DECISION] response_type={response_type}, filters_changed={filters_changed}, is_new_search={is_new_search}")

    if response_type == "general" and not filters_changed and previous_matches:
        print(f"[ACTION] REUSING {len(previous_matches)} previous matches")
        raw_matches = previous_matches
    else:
        print(f"[ACTION] RETRIEVING new matches from Pinecone")
        # Adaptive over-fetch: if we have both price and bedrooms, fetch less
        has_strong_filters = bool(pinecone_filters.get("price")) and bool(pinecone_filters.get("bedrooms"))
        retrieval_k = top_k * (2 if has_strong_filters else 3)
        
        # Compile soft filters 
        soft_filters = build_pinecone_filter(amenities, neighborhoods, subway_prefs)
        print("Soft Filters:", soft_filters)

        # Combine soft and hard filters
        filter_list = combine_soft_with_hard(soft_filters, pinecone_filters)

        # Perform parallel hybrid search
        retrieval_k = top_k * 3  # Over-fetch to allow for post-filtering
        raw_matches = parallel_hybrid_search(
            standalone_query, 
            filter_list[:2],
            top_k=retrieval_k, 
            rerank=True
            )
        print(f"Retrieved {len(raw_matches)} unique matches total.")
    
        ## ---- OLD METHOD: SINGLE HYBRID SEARCH ----
        # Increase top_k for retrieval since we'll filter down afterwards
        # raw_matches = hybrid_search(
        #     standalone_query, 
        #     top_k=retrieval_k, 
        #     rerank=True
        # )
        
        # # Step 4: Apply post-retrieval semantic filters
        # matches = await apply_post_retrieval_filters(
        #     raw_matches,
        #     standalone_query,
        #     hard_filters=pinecone_filters,
        #     amenities=amenities,
        #     neighborhoods=neighborhoods,
        #     subway_prefs=subway_prefs,
        #     boost_weight=1
        # )
        ## --- END OLD METHOD ----
    
    # Step 4.5: Score listings against criteria for ordering and compromises
    criteria = {
        "price": pinecone_filters.get("price") or {},
        "bedrooms": pinecone_filters.get("bedrooms") or {},
        "bathrooms": pinecone_filters.get("bathrooms") or {},
        "amenities": amenities or [],
        "neighborhoods": neighborhoods or [],
        "subway": subway_prefs or {},
    }
    scored = score_listings(raw_matches, criteria)
    # Reorder by score
    matches = [m for (m, _, _) in scored]
    
    # Step 5: Trim to requested top_k after filtering
    matches = matches[:top_k]
    
    # Build clarification only when zero results
    clarification = None
    if len(matches) == 0:
        missing = []
        if not pinecone_filters:
            missing.append("budget or bedroom count")
        if not neighborhoods and not amenities and not subway_prefs.get("routes"):
            missing.append("preferred neighborhood or subway line")
        if missing:
            clarification = f"I found no matches. Could you try specifying: {', '.join(missing)}?"
        else:
            clarification = "I found no matches with those criteria. Try expanding your budget, increasing bedroom count, or exploring different neighborhoods."

    # Step 6: Build current-turn retrieval context (include score/compromises inline)
    # Create a quick map for compromises
    id_to_score = {}
    id_to_comp = {}
    for m, s, comp in scored:
        mid = m.metadata.get("listing_id")
        id_to_score[mid] = s
        id_to_comp[mid] = comp

    def format_with_scores(ms):
        lines = []
        for rank, m in enumerate(ms, start=1):
            md = m.metadata
            lid = md.get('listing_id')
            score = id_to_score.get(lid)
            retrieval_score = m.score
            comp = id_to_comp.get(lid) or []
            lines.append(
                f"{rank}. ID: {lid} (score: {score}; retrieval score: {retrieval_score})\n"
                f"   Price: ${md.get('price')}\n"
                f"   Bedrooms: {md.get('bedrooms')}, Bathrooms: {md.get('bathrooms')}\n"
                f"   Neighborhood: {md.get('neighborhood')}, Borough: {md.get('borough')}\n"
                f"   Amenities: {', '.join(md.get('amenities', []))}\n"
                f"   Compromises: {', '.join(comp) if comp else 'None'}\n"
            )
        return "\n".join(lines)

    context_block = format_with_scores(matches)

    # Step 7: Construct messages with conversation history
    system_msg = {
        "role": "system",
        "content": (
            "You are RentIQ, a helpful assistant experienced in NYC rental markets. "
            "Use the conversation history to resolve pronouns and references like 'the first one' or 'the listing in Williamsburg'. "
            "Ground any recommendations strictly in the provided retrieved listings context for the current turn. "
            "If the user asks a follow-up that cannot be answered from context, ask a concise clarification question."
        ),
    }

    # Keep only the most recent turns to control token usage
    history_messages = []
    if chat_history:
        # Expecting a list of {role, content} items; filter to valid roles
        allowed_roles = {"user", "assistant", "system"}
        filtered = [m for m in chat_history if m.get("role") in allowed_roles and m.get("content")]
        # Trim to last 10 turns (approx 20 messages). Adjust as needed.
        history_messages = filtered[-10:]

    # Compose the current user prompt including retrieved context
    if is_new_search:
        current_user_prompt = f"""
The user asked: "{user_query}"
Rewritten standalone query used for retrieval: "{standalone_query}"

Here are the top {top_k} listings retrieved from our database for this turn:
{context_block}

TASK:
- Provide a ranked list from most to least relevant.
- For each listing: include the exact listing_id, price, bedrooms, bathrooms, neighborhood, amenities, and a summary explaining why it matches the user's needs.
- Be concise but informative in the summaries.
- Optionally include a final_recommendation with overall guidance.
- If this is an UPDATED search (user changed requirements), acknowledge what changed in the final_recommendation.

IMPORTANT: Use the exact listing_id values from the context above. Include all amenities from the listing data.
"""
        # Use structured output for new searches
        use_structured = True
        schema_model = StructuredListingResponse
    else:
        current_user_prompt = f"""
You are continuing an ongoing conversation. Answer naturally and concisely while grounding strictly in the retrieved listings for this turn.

User's latest message: "{user_query}"
Rewritten standalone query: "{standalone_query}"

Top {top_k} listings retrieved for this turn:
{context_block}

Guidelines:
- Keep a conversational tone. Avoid rigid ranking formatting unless explicitly requested.
- Reference prior preferences when relevant. If a referred listing is not in the current results, say so and suggest refining filters.
- Provide a succinct, helpful answer (2–5 sentences) and, when appropriate, suggest the next best question or adjustment.
- If you mention any listing IDs, include them in referenced_listing_ids.
"""
        # Use structured output for conversational responses too
        use_structured = True
        schema_model = ConversationalResponse

    messages = [system_msg]
    messages.extend(history_messages)
    messages.append({"role": "user", "content": current_user_prompt})

    # Step 8: Call LLM with structured output
    try:
        completion = await call_llm_with_limit(
            messages=messages,
            model_name="gpt-4o-mini",
            schema_model=schema_model if use_structured else None,
            temperature=0.3
        )
        
        if use_structured:
            parsed = completion.choices[0].message.parsed
            # Convert structured output to formatted text for display
            if isinstance(parsed, StructuredListingResponse):
                llm_output = _format_structured_listings(parsed)
                structured_data = parsed
            elif isinstance(parsed, ConversationalResponse):
                llm_output = parsed.response
                structured_data = {"referenced_listing_ids": parsed.referenced_listing_ids}
            else:
                # Fallback to text content if parsing failed
                llm_output = completion.choices[0].message.content.strip()
                structured_data = None
        else:
            llm_output = completion.choices[0].message.content.strip()
            structured_data = None
    except Exception as e:
        print(f"[WARN] Structured output failed: {e}. Falling back to text generation.")
        # Fallback to regular text generation
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.3,
        )
        llm_output = response.choices[0].message.content.strip()
        structured_data = None

    # Step 9: Package complete filter state (hard + soft filters)
    filter_state = {
        "hard": pinecone_filters,
        "amenities": amenities,
        "neighborhoods": neighborhoods,
        "subway": subway_prefs
    }

    return llm_output, matches, clarification, filter_state, structured_data


def _format_structured_listings(parsed: StructuredListingResponse) -> str:
    """Convert structured listing response to formatted text for display."""
    lines = []
    
    for listing in parsed.listings:
        lines.append(f"ID: {listing.listing_id}")
        lines.append(f"Price: ${listing.price}")
        lines.append(f"Bedrooms: {listing.bedrooms}, Bathrooms: {listing.bathrooms}")
        lines.append(f"Neighborhood: {listing.neighborhood}")
        lines.append(f"Amenities: {', '.join(listing.amenities)}")
        lines.append(f"Summary: {listing.summary}")
        lines.append("")  # Empty line between listings
    
    if parsed.final_recommendation:
        lines.append(parsed.final_recommendation)
    
    return "\n".join(lines)