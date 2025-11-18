# vectorstore.py
import os
from pinecone import Pinecone, ServerlessSpec
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModelForMaskedLM, AutoModelForSequenceClassification
import torch
from utils import build_text, sanitize_metadata, deduplicate_matches
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import deduplicate_matches

load_dotenv()

INDEX_DIM = 384

# Dense model
dense_model = SentenceTransformer('all-MiniLM-L6-v2')

# Sparse (SPLADE) model
splade_model_name = "naver/splade-cocondenser-ensembledistil"
splade_tokenizer = AutoTokenizer.from_pretrained(splade_model_name)
splade_model = AutoModelForMaskedLM.from_pretrained(splade_model_name)

# Reranker model
rerank_model_name = "BAAI/bge-reranker-v2-m3"
rerank_tokenizer = AutoTokenizer.from_pretrained(rerank_model_name)
rerank_model = AutoModelForSequenceClassification.from_pretrained(rerank_model_name)

def splade_encode(text: str):
    inputs = splade_tokenizer(text, return_tensors="pt", truncation=True, padding=True)
    with torch.no_grad():
        logits = splade_model(**inputs).logits
    weights = torch.log1p(torch.relu(logits)).max(dim=1).values.squeeze()
    indices = torch.nonzero(weights, as_tuple=True)[0].tolist()
    values = weights[indices].tolist()
    return {"indices": indices, "values": values}

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index_name = "listings-index-hybrid"

def get_index():
    if index_name not in [idx.name for idx in pc.list_indexes()]:
        pc.create_index(
            name=index_name,
            dimension=INDEX_DIM,
            metric="dotproduct",
            spec=ServerlessSpec(cloud="aws", region="us-east-1")
        )
    return pc.Index(index_name)

def hybrid_search_raw(query_text: str, alpha: float = 0.5, top_k: int = 20, filters: dict = None):
    dense_q = dense_model.encode(query_text).tolist()
    sparse_q = splade_encode(query_text)

    beta = 1 - alpha
    weighted_dense = [v * alpha for v in dense_q]
    weighted_sparse = {
        "indices": sparse_q["indices"],
        "values": [v * beta for v in sparse_q["values"]]
    }

    query_params = {
        "vector": weighted_dense,
        "sparse_vector": weighted_sparse,
        "top_k": top_k,
        "include_metadata": True,
        "include_values" : False
    }
    if filters:
        query_params["filter"] = filters

    try:
        results = get_index().query(**query_params)
        return results.matches
    except Exception as e:
        # Fallback: retry without filters if filter caused a failure
        print(f"[WARN] Pinecone query failed with filters: {e}")
        if "filter" in query_params:
            try:
                no_filter_params = dict(query_params)
                no_filter_params.pop("filter", None)
                results = get_index().query(**no_filter_params)
                return results.matches
            except Exception as e2:
                print(f"[ERROR] Pinecone query failed without filters as well: {e2}")
        return []

def rerank_results(query: str, matches):
    """Rerank matches using BGE Reranker."""
    # Handle both dict format (from Redis) and object format (from Pinecone)
    docs = []
    for m in matches:
        if isinstance(m, dict):
            md = m.get("metadata", {})
        else:
            md = m.metadata
        docs.append(md.get("description", ""))
    pairs = [(query, doc) for doc in docs]

    inputs = rerank_tokenizer(pairs, padding=True, truncation=True, return_tensors="pt")
    with torch.no_grad():
        scores = rerank_model(**inputs).logits.squeeze(1)  # Higher = more relevant

    # Attach scores and sort
    scored_matches = [
        (match, score.item()) for match, score in zip(matches, scores)
    ]
    scored_matches.sort(key=lambda x: x[1], reverse=True)

    # Return sorted matches
    return scored_matches

def hybrid_search(query_text: str, alpha: float = 0.5, top_k: int = 20, filters: dict = None, rerank: bool = True):
    # Step 1: Raw hybrid search
    matches = hybrid_search_raw(query_text, alpha=alpha, top_k=top_k, filters=filters)

    # Step 2: Deduplicate by listing_id
    matches = deduplicate_matches(matches)

    # Step 3: Optional rerank
    if rerank:
        matches_with_scores = rerank_results(query_text, matches)
        matches = [m for m, _ in matches_with_scores]

    # Final display
    for match in matches[:5]:  # show top 5 after rerank
        # Handle both dict format (from Redis) and object format (from Pinecone)
        if isinstance(match, dict):
            md = match.get("metadata", {})
            score = match.get("score", 0.0)
        else:
            md = match.metadata
            score = getattr(match, "score", 0.0)
        print(f"[Score: {score:.4f}] ID: {md.get('listing_id')}, "
              f"${md.get('price')}, {md.get('bedrooms')}BR/{md.get('bathrooms')}BA, "
              f"Neighborhood{md.get('neighborhood')}, Borough{md.get('borough')}")
        print(f"Amenities: {md.get('amenities')}")
        print("-----")

    return matches

def parallel_hybrid_search(query_text, filter_list, alpha=0.5, top_k=20, rerank=True):
    """
    Run multiple hybrid searches in parallel with different filters.

    Args:
        query_text (str): The user's query.
        alpha (float): Weight for dense vs sparse vector.
        top_k (int): Number of results per search.
        filter_list (list[dict]): A list of Pinecone filter dictionaries.
        rerank (bool): Whether to rerank individual result sets.

    Returns:
        list: Deduplicated matches from all searches combined.
    """
    results_all = []

    with ThreadPoolExecutor(max_workers=len(filter_list)) as executor:
        # Submit each filter as a separate future and store mapping
        future_to_filter = {
            executor.submit(
                hybrid_search,
                query_text,
                alpha=alpha,
                top_k=top_k,
                filters=flt,
                rerank=rerank
            ): flt
            for flt in filter_list
        }

        # Process results in actual finishing order but mapped to correct filter
        for future in as_completed(future_to_filter):
            flt = future_to_filter[future]
            try:
                matches = future.result()
                if matches:
                    print(f"[INFO] Retrieved {len(matches)} matches for filter: {flt}")
                    results_all.extend(matches)
                else:
                    print(f"[INFO] No results for filter: {flt} — skipping.")
            except Exception as e:
                print(f"[WARN] Filter {flt} caused an error: {e}")

    # Deduplicate matches by listing_id
    unique_matches = deduplicate_matches(results_all)
    return unique_matches