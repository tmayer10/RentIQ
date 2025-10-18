# filters.py
import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def build_filter_extraction_prompt(user_query: str) -> str:
    return f"""
You are an information extraction system for a real estate search engine.
Extract **only structured filters** from the given natural language rental search query for retrieval from a Pinecone vectorstore.

OUTPUT RULES:
- Format: Valid JSON object only — no comments, no explanations, no trailing commas.
- Only use fields present in the Pinecone metadata schema below:
    - listing_id (string)
    - price (number)
    - bedrooms (integer)
    - bathrooms (float)
    - sqft (integer)
    - borough (string, always lowercase)
    - neighborhood (string, always lowercase)
    - zipcode (string)
    - building_address (string)
    - amenities (array of lowercase strings)
    - subway_info (string)
    - subway_lines (array of lowercase strings)
    - subway_routes (array of lowercase strings)
    - description (string)
- All string values must be lowercase to match metadata.
- Arrays must use $in operator with a plain list of values, e.g. {{ "amenities": {{ "$in": ["elevator", "doorman"] }} }}
- Numeric comparisons: Use only $lt, $gt, $eq operators (single operator per field unless a range is given).
- Ignore descriptive text that doesn’t map to known metadata fields.
- Do not use fields not present in the metadata above.

EXAMPLES:

Query: "2 bedroom rental under $2000 in manhattan with elevator and doorman"
Output:
{{
    "price": {{"$lt": 2000}},
    "bedrooms": {{"$eq": 2}},
    "borough": {{"$eq": "manhattan"}},
    "amenities": {{"$in": ["elevator", "doorman"]}}
}}

Query: "No fee apartment near the f train under $3500 with 1.5 baths"
Output:
{{
    "subway_routes": {{"$in": ["f"]}},
    "price": {{"$lt": 3500}},
    "bathrooms": {{"$eq": 1.5}}
}}

Query: "Studio in manhattan near a train, pet friendly"
Output:
{{
    "borough": {{"$eq": "manhattan"}},
    "bedrooms": {{"$eq": 0}},
    "subway_routes": {{"$in": ["a"]}},
    "amenities": {{"$in": ["pet friendly"]}}
}}

USER QUERY:
{user_query}

Now output only the JSON filters.
"""

def process_user_query(user_query: str):
    prompt = build_filter_extraction_prompt(user_query)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except json.JSONDecodeError:
        print("[WARN] Invalid filter JSON. Using no filters.")
        return {}