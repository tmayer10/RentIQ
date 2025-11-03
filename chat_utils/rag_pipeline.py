# rag_pipeline.py
import os
from openai import OpenAI
from vectorstore import hybrid_search
from rewriter import rewrite_query
from pinecone_filters import extract_pinecone_filters
from post_filters import apply_post_retrieval_filters, parse_amenities, parse_neighborhoods, parse_subway_preferences
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def format_listings(matches):
    """Convert matches from Pinecone into a neat text block for LLM context."""
    formatted = []
    for rank, m in enumerate(matches, start=1):
        md = m.metadata
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


def rag_search(user_query: str, top_k=5, chat_history=None, is_first_turn: bool = False):
    """Full RAG with optional chat history.

    Retrieves listings for the current user query and asks the LLM to provide
    recommendations, taking prior conversation turns into account when provided.
    """
    # Step -1: Detect if user wants a new search (overrides is_first_turn for formatting)
    is_new_search = is_first_turn or _detect_new_search_intent(user_query, chat_history)
    
    # Step 0: Rewrite follow-up into standalone query
    standalone_query = rewrite_query(user_query, chat_history or [])

    # Step 1: Extract simple Pinecone pre-filters (price, bed, bath, sqft, zipcode ONLY)
    pinecone_filters = extract_pinecone_filters(standalone_query)
    
    # Step 2: Parse post-retrieval filter criteria (neighborhoods, amenities, subway)
    amenities = parse_amenities(standalone_query)
    neighborhoods = parse_neighborhoods(standalone_query)
    subway_prefs = parse_subway_preferences(standalone_query)

    # Step 3: Retrieve from Pinecone using simple pre-filters (fetch more for post-filtering)
    # Increase top_k for retrieval since we'll filter down afterwards
    retrieval_k = top_k * 3  # Over-fetch to allow for post-filtering
    raw_matches = hybrid_search(
        standalone_query, 
        top_k=retrieval_k, 
        filters=pinecone_filters or None, 
        rerank=True
    )
    
    # Step 4: Apply post-retrieval semantic filters
    matches = apply_post_retrieval_filters(
        raw_matches,
        standalone_query,
        amenities=amenities,
        neighborhoods=neighborhoods,
        subway_prefs=subway_prefs
    )
    
    # Step 5: Trim to requested top_k after filtering
    matches = matches[:top_k]
    
    # Build clarification if results are sparse
    clarification = None
    if len(matches) < top_k // 2:
        missing = []
        if not pinecone_filters:
            missing.append("budget or bedroom count")
        if not neighborhoods and not amenities and not subway_prefs.get("routes"):
            missing.append("preferred neighborhood or subway line")
        if missing:
            clarification = f"I found {len(matches)} matches. For better results, could you specify: {', '.join(missing)}?"

    # Step 6: Build current-turn retrieval context
    context_block = format_listings(matches)

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
- For each listing: summarize key selling points and match with the user's needs (from history and this turn).
- Be concise but informative.
- End with a brief final recommendation.
- If this is an UPDATED search (user changed requirements), acknowledge what changed.

Output only the recommendation list and summary.
"""
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
"""

    messages = [system_msg]
    messages.extend(history_messages)
    messages.append({"role": "user", "content": current_user_prompt})

    # Step 8: Call LLM
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.3,
    )
    llm_output = response.choices[0].message.content.strip()

    return llm_output, matches, clarification