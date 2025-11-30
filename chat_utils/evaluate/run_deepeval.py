"""
Evaluate RentIQ responses against the generated goldens using DeepEval.

Usage:
    python chat_utils/evaluate/run_deepeval.py \
        --goldens chat_utils/evaluate/goldens/rentiq_conversation_goldens.csv \
        --limit 10

By default we reuse the retrieval_context saved in the goldens to avoid
touching Pinecone. Pass --use-local-retriever to rebuild context from the
sampled_300_apartments.json file via the lightweight LocalVectorStore.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Dict, Iterable, List, Sequence

import pandas as pd
from deepeval import evaluate
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric
from deepeval.metrics.base_metric import BaseMetric
from deepeval.test_case import LLMTestCase

# Make local imports work when executed from repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.append(str(REPO_ROOT / "chat_utils"))

from evaluate.goldens import call_rentiq_llm, render_listing_for_llm  # type: ignore  # noqa: E402
from evaluate import local_vectorstore  # type: ignore  # noqa: E402


def _parse_list(cell) -> List[str]:
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return []
    if isinstance(cell, str):
        try:
            return list(json.loads(cell))
        except Exception:
            return []
    return list(cell)


def _parse_history(context: Sequence[str]) -> List[Dict[str, str]]:
    """Convert stored 'User: ...' / 'Assistant: ...' strings into chat history."""
    history = []
    for turn in context:
        if not isinstance(turn, str) or ":" not in turn:
            continue
        role_raw, content = turn.split(":", 1)
        role = role_raw.strip().lower()
        if role.startswith("user"):
            role = "user"
        elif role.startswith("assistant"):
            role = "assistant"
        else:
            continue
        history.append({"role": role, "content": content.strip()})
    return history


def _render_matches(matches: Iterable[local_vectorstore.LocalMatch]) -> List[str]:
    """Render LocalMatch objects in the same format used during golden creation."""
    rendered = []
    for m in matches:
        md = m.metadata
        apt_dict = {
            "id": md.get("listing_id"),
            "price": md.get("price"),
            "bedrooms": md.get("bedrooms"),
            "bathrooms": md.get("bathrooms"),
            "neighborhood": md.get("neighborhood"),
            "neighborhood_name": md.get("neighborhood"),
            "amenities": md.get("amenities"),
            "subway_lines": md.get("subway_lines") or md.get("subway_routes"),
            "summary": md.get("description"),
        }
        rendered.append(render_listing_for_llm(apt_dict))
    return rendered


def _maybe_str(cell):
    if cell is None:
        return None
    if isinstance(cell, float) and pd.isna(cell):
        return None
    return str(cell)


def _strip_images(context_blocks: List[str]) -> List[str]:
    """Drop image URL lines to reduce noise for evaluators."""
    cleaned = []
    for block in context_blocks:
        lines = []
        for line in block.splitlines():
            if line.strip().lower().startswith("images:"):
                continue
            lines.append(line)
        cleaned.append("\n".join(lines))
    return cleaned


def _filter_by_expected_ids(context_blocks: List[str], expected_output: str) -> List[str]:
    """Keep only context entries whose ID appears in expected_output."""
    if not expected_output:
        return context_blocks
    ids = set(re.findall(r"\bID[: ]\s*(\d+)\b", expected_output, flags=re.IGNORECASE))
    if not ids:
        return context_blocks
    filtered = []
    for block in context_blocks:
        m = re.search(r"\bID[: ]\s*(\d+)\b", block, flags=re.IGNORECASE)
        if m and m.group(1) in ids:
            filtered.append(block)
    return filtered or context_blocks


class ListingIdCoverageMetric(BaseMetric):
    """
    Simple retrieval check: score = fraction of expected listing IDs that appear in the model output.
    This replaces contextual relevancy to avoid penalizing extra context rows.
    """

    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold
        self.score = None
        self.reason = None
        self.success = None
        self.async_mode = False  # we implement only sync

    @staticmethod
    def _extract_ids(text: str) -> set:
        if not text:
            return set()
        return set(re.findall(r"\b(?:ID[: ]\s*)?(\d{5,8})\b", text, flags=re.IGNORECASE))

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        expected_text = test_case.expected_output or ""
        # no exact matches – skip strict ID coverage
        if re.search(r"None of the retrieved listings match your criteria",
                 expected_text, flags=re.IGNORECASE):
            self.score = 1.0
            self.success = True
            self.reason = (
                "No-match scenario: skipping strict listing ID coverage. "
                "Use faithfulness + answer quality to judge this case."
            )
            return self.score
        
        expected_ids = self._extract_ids(test_case.expected_output)
        actual_ids = self._extract_ids(test_case.actual_output)

        if not expected_ids:
            # If no IDs to check, treat as pass
            self.score = 1.0
            self.success = True
            self.reason = "No expected listing IDs provided; skipping coverage check."
            return self.score

        overlap = expected_ids & actual_ids
        coverage = len(overlap) / len(expected_ids)

        self.score = coverage
        self.success = coverage >= self.threshold
        missing = expected_ids - actual_ids
        extra = actual_ids - expected_ids
        self.reason = (
            f"Matched {len(overlap)}/{len(expected_ids)} expected IDs. "
            f"Missing: {sorted(missing) if missing else 'none'}. "
            f"Extra in output: {sorted(extra) if extra else 'none'}."
        )
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        # Delegate to sync implementation
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self):
        return "Listing ID Coverage"


def build_test_cases(
    df: pd.DataFrame,
    use_local_retriever: bool,
    apartments_path: Path,
    top_k: int = 5,
    strip_images: bool = False,
    filter_context_to_expected: bool = False,
) -> List[LLMTestCase]:
    if use_local_retriever:
        local_vectorstore.initialize_local_store(apartments_path)

    test_cases: List[LLMTestCase] = []
    for _, row in df.iterrows():
        history_raw = _parse_list(row.get("context"))
        history = _parse_history(history_raw)

        if use_local_retriever:
            matches = local_vectorstore.hybrid_search(
                row["input"], top_k=top_k, filters=None, rerank=True
            )
            retrieval_texts = _render_matches(matches)
        else:
            retrieval_texts = _parse_list(row.get("retrieval_context"))

        context_block = "\n\n---\n\n".join(retrieval_texts)
        actual_output = call_rentiq_llm(row["input"], context_block, history=history)

        # Optionally compact retrieval context for evaluation (not for generation)
        retrieval_texts_eval = list(retrieval_texts)
        expected_output = _maybe_str(row.get("expected_output"))
        if strip_images:
            retrieval_texts_eval = _strip_images(retrieval_texts_eval)
        if filter_context_to_expected:
            retrieval_texts_eval = _filter_by_expected_ids(retrieval_texts_eval, expected_output or "")

        additional_metadata = None
        add_meta_cell = row.get("additional_metadata")
        if isinstance(add_meta_cell, str) and add_meta_cell:
            try:
                additional_metadata = json.loads(add_meta_cell)
            except Exception:
                additional_metadata = {"raw_metadata": add_meta_cell}

        comments = _maybe_str(row.get("comments"))
        name = (
            additional_metadata.get("spec_key")
            if isinstance(additional_metadata, dict)
            else None
        )

        test_cases.append(
            LLMTestCase(
                input=row["input"],
                actual_output=actual_output,
                expected_output=expected_output,
                context=history_raw,
                retrieval_context=retrieval_texts_eval,
                additional_metadata=additional_metadata,
                comments=comments,
                name=name,
            )
        )

    return test_cases


def main():
    parser = argparse.ArgumentParser(description="Evaluate RentIQ RAG with DeepEval goldens.")
    parser.add_argument(
        "--goldens",
        type=Path,
        default=Path("chat_utils/evaluate/goldens/rentiq_conversation_goldens.csv"),
        help="Path to the conversation goldens CSV.",
    )
    parser.add_argument(
        "--apartments",
        type=Path,
        default=Path("chat_utils/evaluate/sampled_300_apartments.json"),
        help="Listings JSON used to rebuild a local vector store (only if --use-local-retriever).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional max rows to evaluate.")
    parser.add_argument(
        "--use-local-retriever",
        action="store_true",
        help="Rebuild retrieval context from sampled_300_apartments.json instead of using saved contexts.",
    )
    parser.add_argument(
        "--strip-images",
        action="store_true",
        help="Remove image URL lines from retrieval context before grading (reduces noise).",
    )
    parser.add_argument(
        "--filter-context-to-expected",
        action="store_true",
        help="Keep only retrieval entries whose IDs appear in the expected output (aligns context with answers).",
    )
    parser.add_argument(
        "--answer-threshold",
        type=float,
        default=0.5,
        help="Pass threshold for AnswerRelevancyMetric (default: 0.5).",
    )
    parser.add_argument(
        "--faithfulness-threshold",
        type=float,
        default=0.5,
        help="Pass threshold for FaithfulnessMetric (default: 0.5).",
    )
    parser.add_argument(
        "--id-coverage-threshold",
        type=float,
        default=0.7,
        help="Pass threshold for listing ID coverage metric (fraction of expected IDs present in answer).",
    )
    parser.add_argument(
        "--core-only",
        action="store_true",
        help="Only evaluate core correctness (faithfulness + ID coverage), skip answer relevancy.",
    )

    args = parser.parse_args()

    df = pd.read_csv(args.goldens)
    if args.limit:
        df = df.head(args.limit)

    test_cases = build_test_cases(
        df,
        use_local_retriever=args.use_local_retriever,
        apartments_path=args.apartments,
        strip_images=args.strip_images,
        filter_context_to_expected=args.filter_context_to_expected,
    )

    metrics: List[BaseMetric] = [
        FaithfulnessMetric(model="gpt-4o-mini", threshold=args.faithfulness_threshold),
        ListingIdCoverageMetric(threshold=args.id_coverage_threshold),
    ]

    if not args.core_only:
        metrics.append(
            AnswerRelevancyMetric(model="gpt-4o-mini", threshold=args.answer_threshold)
        )

    evaluate(test_cases=test_cases, metrics=metrics)


if __name__ == "__main__":
    main()
