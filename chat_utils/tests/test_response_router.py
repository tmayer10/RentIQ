"""
Unit tests for chat_utils/response_router.py
"""

import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from response_router import decide_response_type


class TestDecideResponseType:
    """Tests for decide_response_type function."""

    # ========== Index Query Tests (new/updated search) ==========

    def test_change_keywords(self):
        """Test queries with 'change' keywords."""
        queries = [
            "change to 1br",
            "switch to Manhattan",
            "update the price to $4000",
            "modify the search",
            "make it under $3000",
        ]

        for query in queries:
            assert decide_response_type(query) == "index_query", f"Failed for: {query}"

    def test_budget_modifications(self):
        """Test queries modifying budget/price."""
        queries = [
            "under $3000",
            "$2500 max",
            "between $2000 and $3000",
            "raise the budget to $5000",
            "lower the price to $2000",
        ]

        for query in queries:
            assert decide_response_type(query) == "index_query", f"Failed for: {query}"

    def test_room_specifications(self):
        """Test queries with bedroom/bathroom specifications."""
        queries = [
            "2br apartment",
            "3 bedrooms",
            "1 bath minimum",
            "2ba required",
            "studio apartment",
        ]

        for query in queries:
            assert decide_response_type(query) == "index_query", f"Failed for: {query}"

    def test_size_specifications(self):
        """Test queries with sqft specifications."""
        queries = [
            "at least 800 sqft",
            "1000 sq ft minimum",
            "900 square feet",
        ]

        for query in queries:
            assert decide_response_type(query) == "index_query", f"Failed for: {query}"

    def test_zipcode_specifications(self):
        """Test queries with zipcode."""
        queries = [
            "in zipcode 10001",
            "near 10003",
            "apartments in 10011",
        ]

        for query in queries:
            assert decide_response_type(query) == "index_query", f"Failed for: {query}"

    def test_subway_specifications(self):
        """Test queries with subway preferences."""
        queries = [
            "near F train",
            "close to the 1 train",
            "within walking distance of subway",
            "near the Lexington line",
        ]

        for query in queries:
            assert decide_response_type(query) == "index_query", f"Failed for: {query}"

    def test_add_remove_requirements(self):
        """Test queries adding/removing requirements."""
        queries = [
            "add laundry to requirements",
            "also needs elevator",
            "remove the gym requirement",
            "must have parking",
            "require doorman",
        ]

        for query in queries:
            assert decide_response_type(query) == "index_query", f"Failed for: {query}"

    # ========== General Query Tests (follow-up questions) ==========

    def test_clarification_questions(self):
        """Test general clarification questions."""
        queries = [
            "What does this listing include?",
            "Can you explain more about the first one?",
            "Why did you recommend this apartment?",
            "How do these compare?",
        ]

        for query in queries:
            assert decide_response_type(query) == "general", f"Failed for: {query}"

    def test_information_requests(self):
        """Test requests for information about results."""
        queries = [
            "Tell me about the neighborhood",
            "What are the schools like?",
            "Is this area safe?",
            "How's the nightlife?",
        ]

        for query in queries:
            assert decide_response_type(query) == "general", f"Failed for: {query}"

    def test_comparison_questions(self):
        """Test comparison questions."""
        queries = [
            "Which one is better?",
            "How do these two compare?",
            "What's the difference between them?",
        ]

        for query in queries:
            assert decide_response_type(query) == "general", f"Failed for: {query}"

    def test_specific_listing_questions(self):
        """Test questions about specific listings."""
        queries = [
            "Tell me more about the first one",
            "Does #4883693 have parking?",
            "Show me the second listing",
            "What about listing 3?",
        ]

        for query in queries:
            assert decide_response_type(query) == "general", f"Failed for: {query}"

    # ========== Edge Cases ==========

    def test_empty_query(self):
        """Test with empty query."""
        assert decide_response_type("") == "general"

    def test_none_query(self):
        """Test with None query."""
        assert decide_response_type(None) == "general"

    def test_mixed_keywords(self):
        """Test query with both types of keywords."""
        # When both present, should detect index_query (priority)
        query = "Tell me about apartments with 2br under $3000"
        assert decide_response_type(query) == "index_query"

    def test_case_insensitive(self):
        """Test that detection is case-insensitive."""
        queries = [
            "CHANGE to 2BR",
            "Under $3000",
            "NEAR F TRAIN",
        ]

        for query in queries:
            assert decide_response_type(query) == "index_query", f"Failed for: {query}"

    def test_partial_word_matches(self):
        """Test that partial word matches don't trigger false positives."""
        # These should NOT trigger index_query
        queries = [
            "I exchanged messages with the landlord",  # contains "change"
            "The apartment has been undergoing renovations",  # contains "under"
        ]

        # Note: Current regex uses \b word boundaries, so these should be caught correctly
        for query in queries:
            result = decide_response_type(query)
            assert result == "general", f"Failed for: {query}"
            # "exchanged" won't match \b(change)\b
            # "undergoing" won't match \bunder\s*$\d+
            # So these should be "general"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
