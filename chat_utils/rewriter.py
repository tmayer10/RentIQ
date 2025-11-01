import os
from typing import List, Dict
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _build_rewrite_prompt(user_query: str, chat_history: List[Dict[str, str]]) -> str:
    history_text = []
    for msg in chat_history[-10:]:
        role = msg.get("role", "user")
        content = msg.get("content", "").strip()
        if not content:
            continue
        history_text.append(f"{role.upper()}: {content}")
    joined_history = "\n".join(history_text)

    return f"""
You are a query rewriter for a rental search RAG system.
Task: Rewrite the latest user message into a single, standalone search query that captures the user's current intent, resolving all pronouns and references using the conversation history.

Rules:
- Keep it concise, a single sentence if possible.
- Include specific constraints like price, bedrooms, bathrooms, neighborhoods/boroughs, amenities, proximity to subway lines/routes when mentioned.
- When the user mentions landmarks or universities (e.g., nyu, columbia), infer the most likely neighborhoods/areas and include them explicitly.
- If the user refers to "the first one" or similar, infer attributes (e.g., listing id, neighborhood, price, bedrooms) from the assistant's last reply and include them explicitly.
- CRITICAL: If the user explicitly replaces/changes a constraint (e.g., "change to 1br", "actually make it $4000", "switch to Manhattan"), REPLACE the old value with the new one. Do NOT keep both.
- If the user adds new constraints without replacing (e.g., "also needs elevator"), merge them.
- Do not include instructions to the assistant, only the search query content.

Conversation history (most recent first):
{joined_history}

Latest user message:
{user_query}

Now output only the rewritten standalone search query with no extra text.
"""


def rewrite_query(user_query: str, chat_history: List[Dict[str, str]] = None) -> str:
    if not chat_history:
        return user_query

    prompt = _build_rewrite_prompt(user_query, chat_history)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    content = resp.choices[0].message.content.strip()
    # Safety fallback
    return content or user_query



