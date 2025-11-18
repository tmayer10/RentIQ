from typing import List, Optional, Tuple, Any, Dict
from dataclasses import dataclass
from pathlib import Path
import os
import json
import numpy as np
import pickle

"""
Utilities to generate dense (neural) and sparse (TF-IDF) embeddings locally,
and simple save/load helpers for FAISS (dense) and pickle (vectorizer).
"""


# Dense model deps (try sentence-transformers first, fallback to transformers)
try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    _HAS_SENTENCE_TRANSFORMERS = True
except Exception:  # pragma: no cover - handled at runtime when deps missing
    _HAS_SENTENCE_TRANSFORMERS = False

try:
    from transformers import AutoTokenizer, AutoModel  # type: ignore
    import torch  # type: ignore
    _HAS_TRANSFORMERS = True
except Exception:  # pragma: no cover - handled at runtime
    _HAS_TRANSFORMERS = False

# Sparse deps
try:
    from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
    _HAS_SKLEARN = True
except Exception:  # pragma: no cover - handled at runtime
    _HAS_SKLEARN = False

# Faiss optional
try:
    import faiss  # type: ignore
    _HAS_FAISS = True
except Exception:  # pragma: no cover - handled at runtime
    _HAS_FAISS = False


def dense_embeddings(
    texts: List[str],
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    batch_size: int = 32,
    normalize: bool = True,
    device: Optional[str] = None,
) -> np.ndarray:
    """
    Produce dense embeddings for a list of texts.
    Prefers sentence-transformers if available, otherwise uses transformers+mean pooling.
    Returns a numpy array (n_texts, dim).
    """
    if device is None:
        device = "cuda" if _HAS_TRANSFORMERS and torch.cuda.is_available() else "cpu"

    if _HAS_SENTENCE_TRANSFORMERS:
        model = SentenceTransformer(model_name, device=device)
        embs = model.encode(texts, batch_size=batch_size, convert_to_numpy=True, normalize_embeddings=normalize)
        return embs

    if _HAS_TRANSFORMERS:
        tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=True)
        model = AutoModel.from_pretrained(model_name).to(device)
        model.eval()
        all_embs = []
        with torch.no_grad():
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                toks = tokenizer(batch, padding=True, truncation=True, return_tensors="pt")
                input_ids = toks["input_ids"].to(device)
                attention_mask = toks["attention_mask"].to(device)
                out = model(input_ids=input_ids, attention_mask=attention_mask)
                last = out.last_hidden_state  # (b, seq, dim)
                mask = attention_mask.unsqueeze(-1)
                summed = (last * mask).sum(1)
                counts = mask.sum(1).clamp(min=1)
                pooled = summed / counts
                emb = pooled.cpu().numpy()
                all_embs.append(emb)
        embs = np.vstack(all_embs)
        if normalize:
            norms = np.linalg.norm(embs, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            embs = embs / norms
        return embs

    raise RuntimeError("No suitable model available. Install sentence-transformers or transformers + torch.")


def save_dense_index(
    embeddings: np.ndarray,
    path: str,
    ids: Optional[List[int]] = None,
    use_faiss: bool = True,
) -> None:
    """
    Save dense embeddings. If faiss is available and use_faiss=True, create and write a FAISS IndexFlatIP
    (assumes embeddings are normalized for inner product). Otherwise saves embeddings and ids as .npz.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if use_faiss and _HAS_FAISS:
        dim = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings.astype(np.float32))
        faiss.write_index(index, path)
        # Save ids separately if provided
        if ids is not None:
            with open(path + ".ids.pkl", "wb") as f:
                pickle.dump(ids, f)
        return

    # Fallback: save numpy arrays
    data = {"embeddings": embeddings}
    if ids is not None:
        data["ids"] = np.array(ids)
    np.savez_compressed(path, **data)


def load_dense_index(path: str) -> Tuple[Any, Optional[np.ndarray]]:
    """
    Load dense index. Returns (index_or_embeddings, ids_or_None).
    If FAISS file exists and faiss is available, returns a faiss index. Otherwise returns numpy arrays.
    """
    if _HAS_FAISS and os.path.exists(path):
        try:
            index = faiss.read_index(path)
            ids = None
            ids_path = path + ".ids.pkl"
            if os.path.exists(ids_path):
                with open(ids_path, "rb") as f:
                    ids = pickle.load(f)
            return index, ids
        except Exception:
            pass

    # Try numpy .npz
    if os.path.exists(path):
        try:
            arr = np.load(path, allow_pickle=True)
            emb = arr.get("embeddings", None)
            ids = arr.get("ids", None)
            return emb, ids
        except Exception:
            raise RuntimeError("Failed to load dense index from path: " + path)

    raise FileNotFoundError("Dense index not found at: " + path)


def sparse_embeddings(
    texts: List[str],
    ngram_range: Tuple[int, int] = (1, 2),
    max_features: int = 50000,
    norm: str = "l2",
    sublinear_tf: bool = True,
) -> Tuple[Any, Any]:
    """
    Fit a TF-IDF vectorizer and transform texts. Returns (vectorizer, sparse_matrix).
    Requires scikit-learn.
    """
    if not _HAS_SKLEARN:
        raise RuntimeError("scikit-learn is required for sparse embeddings (TfidfVectorizer).")

    vectorizer = TfidfVectorizer(ngram_range=ngram_range, max_features=max_features, norm=norm, sublinear_tf=sublinear_tf)
    mat = vectorizer.fit_transform(texts)
    return vectorizer, mat


def save_vectorizer(vectorizer: Any, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(vectorizer, f)


def load_vectorizer(path: str) -> Any:
    with open(path, "rb") as f:
        return pickle.load(f)


# ---------------------------------------------------------------------------
# Simple in-memory vector store built from test_apartments.json
# ---------------------------------------------------------------------------

LOCAL_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@dataclass
class LocalMatch:
    """Lightweight match object to mimic Pinecone results."""

    metadata: Dict[str, Any]
    score: float

    @property
    def id(self) -> Optional[str]:
        return self.metadata.get("listing_id")


class LocalVectorStore:
    def __init__(self, records: List[Dict[str, Any]], model_name: str = LOCAL_MODEL_NAME):
        if not _HAS_SENTENCE_TRANSFORMERS:
            raise RuntimeError("sentence-transformers is required for LocalVectorStore")

        self.model_name = model_name
        self.encoder = SentenceTransformer(model_name)
        self.metadata: List[Dict[str, Any]] = [self._build_metadata(r) for r in records]
        self.texts: List[str] = [self._build_text(md) for md in self.metadata]
        self.embeddings = self.encoder.encode(
            self.texts,
            batch_size=64,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )

    @staticmethod
    def _normalize_token(value: Any) -> str:
        return str(value).strip().lower().replace(" ", "_")

    @classmethod
    def _build_metadata(cls, record: Dict[str, Any]) -> Dict[str, Any]:
        amenities_raw = [a for a in (record.get("amenities") or []) if a]
        amenities: List[str] = []
        for amenity in amenities_raw:
            token = cls._normalize_token(amenity)
            amenities.append(token)
            if "_" in token:
                amenities.append(token.replace("_", " "))
        # Deduplicate while preserving order
        seen = set()
        amenities = [a for a in amenities if not (a in seen or seen.add(a))]

        borough = (record.get("borough") or "").strip().lower()
        neighborhood = (record.get("neighborhood") or "").strip().lower()
        subway_list = record.get("subways") or []
        subway_lines = []
        subway_routes = []
        subway_distances = []
        for sub in subway_list:
            line = (sub.get("name") or sub.get("line") or "").strip().lower()
            if line:
                subway_lines.append(line)
            for route in sub.get("routes") or []:
                if route:
                    subway_routes.append(str(route).strip().lower())
            dist = sub.get("distance")
            if dist is not None:
                subway_distances.append(float(dist))

        metadata = {
            "listing_id": str(record.get("id")),
            "price": record.get("price"),
            "bedrooms": record.get("bedrooms"),
            "bathrooms": record.get("bathrooms"),
            "sqft": record.get("sqft"),
            "borough": borough,
            "neighborhood": neighborhood,
            "zipcode": record.get("zipcode"),
            "address": record.get("address"),
            "amenities": amenities,
            "subway_lines": subway_lines,
            "subway_routes": subway_routes,
            "subway_min_distance": min(subway_distances) if subway_distances else None,
            "description": record.get("description", ""),
            "status": record.get("status"),
        }
        return metadata

    @staticmethod
    def _build_text(metadata: Dict[str, Any]) -> str:
        parts = [
            f"Listing {metadata.get('listing_id')} at {metadata.get('address') or 'unknown address'}",
            f"Located in {metadata.get('neighborhood') or 'unknown neighborhood'}, {metadata.get('borough') or 'borough'}",
            f"Price ${metadata.get('price')} for {metadata.get('bedrooms')} bedrooms and {metadata.get('bathrooms')} baths",
            "Amenities: " + ", ".join(metadata.get("amenities", [])) if metadata.get("amenities") else "",
            metadata.get("description", ""),
        ]
        return "\n".join([p for p in parts if p])

    def _encode_query(self, text: str) -> np.ndarray:
        vec = self.encoder.encode([text], convert_to_numpy=True, normalize_embeddings=True)
        return vec[0]

    def _passes_filters(self, metadata: Dict[str, Any], filters: Optional[Dict[str, Any]]) -> bool:
        if not filters:
            return True

        for key, condition in filters.items():
            value = metadata.get(key)
            if isinstance(condition, dict):
                if not self._evaluate_condition(value, condition):
                    return False
            else:
                if value != condition:
                    return False
        return True

    @staticmethod
    def _normalize_scalar(val: Any) -> str:
        return str(val).strip().lower().replace(" ", "_")

    @classmethod
    def _evaluate_condition(cls, value: Any, condition: Dict[str, Any]) -> bool:
        if value is None:
            return False

        for op, expected in condition.items():
            if op == "$eq":
                if cls._normalize_scalar(value) != cls._normalize_scalar(expected):
                    return False
            elif op == "$lt":
                if float(value) >= float(expected):
                    return False
            elif op == "$lte":
                if float(value) > float(expected):
                    return False
            elif op == "$gt":
                if float(value) <= float(expected):
                    return False
            elif op == "$gte":
                if float(value) < float(expected):
                    return False
            elif op == "$in":
                expected_vals = [cls._normalize_scalar(e) for e in (expected if isinstance(expected, list) else [expected])]
                if isinstance(value, list):
                    value_lower = [cls._normalize_scalar(v) for v in value]
                    if not any(v in value_lower for v in expected_vals):
                        return False
                else:
                    if cls._normalize_scalar(value) not in expected_vals:
                        return False
            else:
                # Unknown operator; default to False to avoid false positives
                return False
        return True

    def hybrid_search(self, query_text: str, top_k: int = 20, filters: Optional[Dict[str, Any]] = None) -> List[LocalMatch]:
        query_vec = self._encode_query(query_text)
        scores = self.embeddings @ query_vec
        ranked = np.argsort(scores)[::-1]
        matches: List[LocalMatch] = []
        for idx in ranked:
            md = self.metadata[idx]
            if not self._passes_filters(md, filters):
                continue
            matches.append(LocalMatch(metadata=md, score=float(scores[idx])))
            if len(matches) >= top_k:
                break
        return matches


_LOCAL_STORE: Optional[LocalVectorStore] = None


def initialize_local_store(json_path: Path, model_name: str = LOCAL_MODEL_NAME) -> LocalVectorStore:
    """Load listings from JSON and build an in-memory vector store."""
    global _LOCAL_STORE
    records = json.loads(Path(json_path).read_text())
    _LOCAL_STORE = LocalVectorStore(records, model_name=model_name)
    return _LOCAL_STORE


def _require_store() -> LocalVectorStore:
    if _LOCAL_STORE is None:
        raise RuntimeError("Local vector store not initialized. Call initialize_local_store() first.")
    return _LOCAL_STORE


def hybrid_search(query_text: str, alpha: float = 0.5, top_k: int = 20, filters: Optional[Dict[str, Any]] = None, rerank: bool = True):
    store = _require_store()
    return store.hybrid_search(query_text, top_k=top_k, filters=filters)


def parallel_hybrid_search(query_text, filter_list, alpha: float = 0.5, top_k: int = 20, rerank: bool = True):
    store = _require_store()
    filters_to_run = filter_list or [{}]
    results: List[LocalMatch] = []
    seen = set()
    for flt in filters_to_run:
        matches = store.hybrid_search(query_text, top_k=top_k, filters=flt)
        for match in matches:
            lid = match.metadata.get("listing_id")
            if lid in seen:
                continue
            seen.add(lid)
            results.append(match)
    return results


def reset_local_store():
    global _LOCAL_STORE
    _LOCAL_STORE = None
