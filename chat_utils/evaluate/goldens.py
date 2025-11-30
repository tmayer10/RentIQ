from dotenv import load_dotenv
import os
import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any

import pandas as pd
from openai import OpenAI

# ------------------ CONFIG ------------------ #

BASE_DIR = Path(__file__).resolve().parent
load_dotenv()
DATA_PATH = BASE_DIR / "sampled_300_apartments.json"
OUTPUT_DIR = BASE_DIR / "goldens"
OUTPUT_DIR.mkdir(exist_ok=True)

# Use env var; make sure OPENAI_API_KEY is set
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

OPENAI_MODEL = "gpt-4.1-mini"

RENTIQ_SYSTEM_PROMPT = """
You are RentIQ, a helpful assistant experienced in NYC rental markets.
Use the conversation history to resolve pronouns and references like "the first one" or "the listing in Williamsburg".
Ground any recommendations strictly in the provided retrieved listings context for the current turn.
If the user asks a follow-up that cannot be answered from context, ask a concise clarification question.

TASK:
- Provide a ranked list from most to least relevant.
- For each listing: summarize key selling points and match with the user's needs (from history and this turn).
- Be concise but informative.
- End with a brief final recommendation.
"""


# ------------------ DATA CLASSES ------------------ #

@dataclass
class QuerySpec:
    key: str
    max_rent: int          # numeric budget used for scoring
    min_beds: int
    neighborhoods: Optional[List[str]] = None
    must_amenities: Optional[List[str]] = None
    prefer_lines: Optional[List[str]] = None
    description: str = ""

    def to_query_text(self) -> str:
        """Generate a natural-ish user query from the spec with realistic budget phrasing."""
        if self.neighborhoods:
            if len(self.neighborhoods) == 1:
                area_str = self.neighborhoods[0]
            else:
                area_str = ", ".join(self.neighborhoods[:-1]) + f" or {self.neighborhoods[-1]}"
        else:
            area_str = "Manhattan"

        beds_str = f"{self.min_beds} bedroom"
        if self.min_beds > 1:
            beds_str += "s"

        # Use a nicer display budget (rounded to nearest $100)
        display_budget = int(round(self.max_rent / 100.0) * 100)

        # Slight variation in wording
        if random.random() < 0.5:
            budget_phrase = f"with a budget up to ${display_budget}"
        else:
            budget_phrase = f"for around ${display_budget} a month"

        parts = [f"I'm looking for a {beds_str} apartment in {area_str} {budget_phrase}"]

        if self.must_amenities:
            parts.append("that has " + ", ".join(self.must_amenities))

        if self.prefer_lines:
            parts.append("near subway lines " + " or ".join(self.prefer_lines))

        query = ", ".join(parts) + "."
        if self.description:
            query += f" {self.description}"
        return query


# ------------------ LOAD APARTMENTS ------------------ #

def load_apartments(path: Path) -> List[Dict[str, Any]]:
    with path.open() as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Expected sampled_300_apartments.json to contain a list of listings.")
    return data


# ------------------ SCORING & RANKING ------------------ #

def score_listing_for_spec(apt: Dict[str, Any], spec: QuerySpec) -> int:
    """
    Returns an integer score.
    0 or below => listing is excluded by hard constraints.
    """
    price = apt.get("price")
    beds = apt.get("bedrooms") or apt.get("bedrooms_count") or 0
    nhood = apt.get("neighborhood_name") or apt.get("neighborhood")
    amenities_raw = apt.get("amenities", []) or []
    amenities = set(a.lower() for a in amenities_raw if isinstance(a, str))
    lines = set(apt.get("subway_lines", []) or [])

    score = 0

    # ---- Hard constraints ---- #
    if not isinstance(price, (int, float)) or price > spec.max_rent:
        return 0
    if beds < spec.min_beds:
        return 0
    if spec.must_amenities:
        for amen in spec.must_amenities:
            if amen.lower() not in amenities:
                return 0

    # ---- Soft constraints ---- #
    # Bedrooms: exact vs more
    if beds == spec.min_beds:
        score += 1
    elif beds > spec.min_beds:
        score += 2

    # Neighborhood match
    if spec.neighborhoods:
        if nhood in spec.neighborhoods:
            score += 3  # strong match

    # Preferred subway lines
    if spec.prefer_lines and lines:
        if lines.intersection(spec.prefer_lines):
            score += 2

    # Cheaper than budget is better
    price_bonus = max(0, int((spec.max_rent - price) / 500))
    score += price_bonus

    return score


def rank_apartments_for_spec(spec: QuerySpec, apartments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked = []
    for apt in apartments:
        s = score_listing_for_spec(apt, spec)
        if s > 0:
            ranked.append((s, apt))

    ranked.sort(
        key=lambda x: (
            -x[0],
            x[1].get("price", 9999999),
            -(x[1].get("bedrooms") or x[1].get("bedrooms_count") or 0),
            str(x[1].get("id")),
        )
    )
    return [apt for _, apt in ranked]


# ------------------ AUTO-BUILD SPECS FROM DATA ------------------ #

def _percentile(sorted_vals: List[float], p: float) -> float:
    """Simple percentile without numpy."""
    if not sorted_vals:
        raise ValueError("Empty list for percentile computation.")
    idx = int(round((p / 100.0) * (len(sorted_vals) - 1)))
    return sorted_vals[idx]


def build_specs_from_data(apartments: List[Dict[str, Any]], num_specs: int = 20) -> List[QuerySpec]:
    """
    Automatically generate a bunch of realistic QuerySpecs based on the dataset:
    - Uses price percentiles but clamps budgets to a renter-friendly band.
    - Budgets are rounded to nice numbers (nearest $100).
    - Only keeps specs that actually return at least one listing.
    """
    random.seed(42)

    # neighborhoods
    neighborhoods = [
        a.get("neighborhood_name") or a.get("neighborhood")
        for a in apartments
        if a.get("neighborhood_name") or a.get("neighborhood")
    ]
    nhood_counts = Counter(neighborhoods)
    popular_nhoods = [n for n, _ in nhood_counts.most_common(15)]

    # prices
    prices = [a.get("price") for a in apartments if isinstance(a.get("price"), (int, float))]
    if not prices:
        raise ValueError("No price data found in apartments.")
    prices_sorted = sorted(prices)

    # Use 10th–90th percentile as a base, but clamp to something like 2000–8000
    p10 = _percentile(prices_sorted, 10)
    p90 = _percentile(prices_sorted, 90)

    lower_cap = max(2000, p10)
    upper_cap = min(8000, p90)

    if lower_cap >= upper_cap:
        # Fall back to simple bands if data is weird
        lower_cap = 2000
        upper_cap = 8000

    # Build a few "nice" price candidates in that range (steps of $250)
    price_candidates = []
    step = 250
    val = lower_cap
    while val <= upper_cap:
        # round to nearest 100
        nice_val = int(round(val / 100.0) * 100)
        if nice_val not in price_candidates:
            price_candidates.append(nice_val)
        val += step

    # amenities + subway lines vocab
    amenity_counter = Counter()
    line_counter = Counter()
    for a in apartments:
        for amen in a.get("amenities", []) or []:
            if isinstance(amen, str):
                amenity_counter[amen.lower()] += 1
        for line in a.get("subway_lines", []) or []:
            line_counter[line] += 1

    common_amenities = [a for a, _ in amenity_counter.most_common(15)]
    common_lines = [l for l, _ in line_counter.most_common(10)]

    specs: List[QuerySpec] = []
    attempt_limit = num_specs * 5  # oversample attempts; many may be filtered out

    for _ in range(attempt_limit):
        max_rent = random.choice(price_candidates)
        min_beds = random.choice([1, 2, 3])
        nhood = random.choice(popular_nhoods) if popular_nhoods else None

        must_amenities: List[str] = []
        if common_amenities:
            if random.random() < 0.5:
                must_amenities.append(random.choice(common_amenities))
            if random.random() < 0.2:
                must_amenities.append(random.choice(common_amenities))

        prefer_lines: List[str] = []
        if common_lines and random.random() < 0.6:
            prefer_lines.append(random.choice(common_lines))

        key = f"auto_{(nhood or 'manhattan').replace(' ', '_').lower()}_{min_beds}br_{max_rent}"

        spec = QuerySpec(
            key=key,
            max_rent=max_rent,
            min_beds=min_beds,
            neighborhoods=[nhood] if nhood else None,
            must_amenities=must_amenities or None,
            prefer_lines=prefer_lines or None,
        )

        ranked = rank_apartments_for_spec(spec, apartments)
        if ranked:
            specs.append(spec)
        if len(specs) >= num_specs:
            break

    return specs


# ------------------ RENDER LISTINGS FOR LLM ------------------ #

def render_listing_for_llm(apt: Dict[str, Any]) -> str:
    amenities = apt.get("amenities") or []
    subway_lines = apt.get("subway_lines") or []
    images = apt.get("image_urls") or apt.get("images") or []

    lines = [
        f"ID: {apt.get('id')}",
        f"Price: ${apt.get('price')}",
        f"Bedrooms: {apt.get('bedrooms')}, Bathrooms: {apt.get('bathrooms')}",
        f"Neighborhood: {apt.get('neighborhood_name') or apt.get('neighborhood')}",
        "Amenities: " + ", ".join(amenities),
        "Subway: Routes: " + ", ".join(subway_lines),
    ]
    if images:
        lines.append("Images: " + ", ".join(images))
    if apt.get("summary"):
        lines.append("Summary: " + apt["summary"])
    return "\n".join(lines)


def build_context_block(apartments_ranked: List[Dict[str, Any]]) -> str:
    return "\n\n---\n\n".join(render_listing_for_llm(a) for a in apartments_ranked)


# ------------------ LLM HELPERS ------------------ #

def call_rentiq_llm(query_text: str, context_block: str, history: Optional[List[Dict[str, str]]] = None) -> str:
    """
    Generic helper:
    - system prompt
    - optional conversation history (list of {role, content})
    - user turn that includes query + context
    """
    user_content = (
        f"User's latest message: \"{query_text}\"\n\n"
        f"Top listings retrieved for this turn:\n\n{context_block}"
    )

    messages: List[Dict[str, str]] = [{"role": "system", "content": RENTIQ_SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_content})

    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0.0,
    )
    return resp.choices[0].message.content


# ------------------ GOLDEN GENERATION ------------------ #

def generate_single_turn_goldens(apartments: List[Dict[str, Any]], specs: List[QuerySpec]):
    retrieval_rows = []
    conversation_rows = []

    for spec in specs:
        ranked = rank_apartments_for_spec(spec, apartments)
        if not ranked:
            print(f"[WARN] No listings matched spec {spec.key}, skipping.")
            continue

        top_k = ranked[:5]
        query_text = spec.to_query_text()
        context_block = build_context_block(top_k)

        expected_output = call_rentiq_llm(query_text, context_block)

        listing_ids = [str(a.get("id")) for a in top_k]

        add_meta_retrieval = {
            "spec_key": spec.key,
            "max_rent": spec.max_rent,
            "min_beds": spec.min_beds,
            "listing_ids": listing_ids,
        }

        retrieval_rows.append(
            {
                "input": query_text,
                "retrieval_context": json.dumps(listing_ids),
                "additional_metadata": json.dumps(add_meta_retrieval),
                "comments": "",
            }
        )

        retrieval_context_texts = [render_listing_for_llm(a) for a in top_k]
        add_meta_conv = {
            "spec_key": spec.key,
            "max_rent": spec.max_rent,
            "min_beds": spec.min_beds,
            "listing_ids": listing_ids,
        }

        conversation_rows.append(
            {
                "input": query_text,
                "expected_output": expected_output,
                "retrieval_context": json.dumps(retrieval_context_texts),
                "context": json.dumps([]),  # no prior turns
                "additional_metadata": json.dumps(add_meta_conv),
                "comments": "",
            }
        )

    return retrieval_rows, conversation_rows


def generate_multi_turn_goldens(apartments: List[Dict[str, Any]], specs: List[QuerySpec]) -> List[Dict[str, Any]]:
    rows = []

    for spec in specs:
        ranked = rank_apartments_for_spec(spec, apartments)
        if not ranked:
            continue

        top_k = ranked[:5]
        base_query = spec.to_query_text()
        base_context_block = build_context_block(top_k)

        # Turn 1 assistant answer
        assistant_turn1 = call_rentiq_llm(base_query, base_context_block)

        # Follow-up: generic preference/refinement question
        follow_up_user = "Between these options, which one would you recommend for me and why?"

        history = [
            {"role": "user", "content": base_query},
            {"role": "assistant", "content": assistant_turn1},
        ]

        updated_context_block = base_context_block
        expected_output = call_rentiq_llm(follow_up_user, updated_context_block, history=history)

        retrieval_context_texts = [render_listing_for_llm(a) for a in top_k]
        listing_ids = [str(a.get("id")) for a in top_k]

        conversation_context = [
            f"User: {base_query}",
            f"Assistant: {assistant_turn1}",
        ]

        add_meta_conv = {
            "spec_key": f"{spec.key}_followup",
            "base_spec_key": spec.key,
            "listing_ids": listing_ids,
            "note": "Generic follow-up asking for recommendation given the same result set.",
        }

        rows.append(
            {
                "input": follow_up_user,
                "expected_output": expected_output,
                "retrieval_context": json.dumps(retrieval_context_texts),
                "context": json.dumps(conversation_context),
                "additional_metadata": json.dumps(add_meta_conv),
                "comments": "",
            }
        )

    return rows


# ------------------ MAIN ------------------ #

def main():
    apartments = load_apartments(DATA_PATH)

    # Auto-generate specs that actually match your data with realistic budgets
    specs = build_specs_from_data(apartments, num_specs=20)
    print(f"Built {len(specs)} query specs from data.")

    retrieval_rows, conv_rows_single = generate_single_turn_goldens(apartments, specs)
    conv_rows_multi = generate_multi_turn_goldens(apartments, specs)

    df_retrieval = pd.DataFrame(retrieval_rows)
    df_retrieval.to_csv(OUTPUT_DIR / "rentiq_retrieval_goldens.csv", index=False)

    df_conv = pd.DataFrame(conv_rows_single + conv_rows_multi)
    df_conv.to_csv(OUTPUT_DIR / "rentiq_conversation_goldens.csv", index=False)

    print(f"Wrote {len(df_retrieval)} retrieval goldens to {OUTPUT_DIR / 'rentiq_retrieval_goldens.csv'}")
    print(f"Wrote {len(df_conv)} conversation goldens to {OUTPUT_DIR / 'rentiq_conversation_goldens.csv'}")


if __name__ == "__main__":
    main()
