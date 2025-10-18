# rag_pipeline.py
import os
from openai import OpenAI
from vectorstore import hybrid_search
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

def rag_search(user_query: str, top_k=5):
    """Full RAG: retrieve listings, then use LLM to produce ranked recommendations."""
    # Step 1: Retrieve
    matches = hybrid_search(user_query, top_k=top_k, rerank=True)

    # Step 2: Build context
    context_block = format_listings(matches)

    # Step 3: LLM prompt
    prompt = f"""
You are RentIQ, a highly knowledgeable NYC apartment search assistant.
A user has asked: "{user_query}"

Here are the top {top_k} listings retrieved from our database:
{context_block}

TASK:
- Provide a ranked list from most to least relevant.
- For each listing: summarize key selling points and match with user's needs.
- Be concise but informative.
- End with a brief final recommendation.

Output only the recommendation list and summary.
"""

    # Step 4: Call LLM
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant experienced in NYC rental markets."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3
    )
    llm_output = response.choices[0].message.content.strip()

    return llm_output, matches