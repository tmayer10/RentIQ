# rag_pipeline.py
import os
from openai import OpenAI
from vectorstore import hybrid_search
from rewriter import rewrite_query
from filters import process_user_query
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


def rag_search(user_query: str, top_k=5, chat_history=None):
    """Full RAG with optional chat history.

    Retrieves listings for the current user query and asks the LLM to provide
    recommendations, taking prior conversation turns into account when provided.
    """
    # Step 0: Rewrite follow-up into standalone query
    standalone_query = rewrite_query(user_query, chat_history or [])

    # Step 0.5: Extract any structured filters that can help retrieval
    try:
        filters, clarification = process_user_query(standalone_query)
    except Exception:
        filters, clarification = None, None

    # Step 1: Retrieve using the rewritten query and filters
    matches = hybrid_search(standalone_query, top_k=top_k, filters=filters or None, rerank=True)

    # Step 2: Build current-turn retrieval context
    context_block = format_listings(matches)

    # Step 3: Construct messages with conversation history
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

Output only the recommendation list and summary.
"""

    messages = [system_msg]
    messages.extend(history_messages)
    messages.append({"role": "user", "content": current_user_prompt})

    # Step 4: Call LLM
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.3,
    )
    llm_output = response.choices[0].message.content.strip()

    return llm_output, matches, clarification