"""
Unit tests for chat_utils/pinecone_filters.py (fallback functions only)

Note: This file tests only the fallback regex-based extraction functions that don't require API calls.
For full LLM-based extraction tests, use integration tests with mocked API responses.
"""

import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pinecone_filters import _fallback_extract_pinecone_filters, _normalize_pinecone_filters


class TestFallbackExtractPineconeFilters:
    """Tests for _fallback_extract_pinecone_filters function."""

    def test_extract_price_under(self):
        """Test extracting 'under' price constraint."""
        result = _fallback_extract_pinecone_filters("2br under $3000")

        assert "price" in result
        assert result["price"]["$lt"] == 3000.0

    def test_extract_price_max(self):
        """Test extracting 'max' price constraint."""
        result = _fallback_extract_pinecone_filters("max $2500")

        assert "price" in result
        assert result["price"]["$lt"] == 2500.0

    def test_extract_price_with_comma(self):
        """Test extracting price with comma separator."""
        result = _fallback_extract_pinecone_filters("under $5,000")

        assert "price" in result
        assert result["price"]["$lt"] == 5000.0

    def test_extract_price_dollar_only(self):
        """Test extracting just dollar amount (infers 'under')."""
        result = _fallback_extract_pinecone_filters("$2800 apartment")

        assert "price" in result
        assert result["price"]["$lt"] == 2800.0

    def test_extract_bedrooms(self):
        """Test extracting bedrooms."""
        queries = [
            ("2br apartment", 2),
            ("3 bedroom", 3),
            ("1 bedrooms needed", 1),
        ]

        for query, expected_beds in queries:
            result = _fallback_extract_pinecone_filters(query)
            assert "bedrooms" in result
            assert result["bedrooms"]["$eq"] == expected_beds

    def test_extract_studio(self):
        """Test extracting studio (0 bedrooms)."""
        result = _fallback_extract_pinecone_filters("studio apartment")

        assert "bedrooms" in result
        assert result["bedrooms"]["$eq"] == 0

    def test_extract_bathrooms(self):
        """Test extracting bathrooms."""
        queries = [
            ("2ba apartment", 2.0),
            ("1.5 bathrooms", 1.5),
            ("3 bath", 3.0),
        ]

        for query, expected_baths in queries:
            result = _fallback_extract_pinecone_filters(query)
            assert "bathrooms" in result
            assert result["bathrooms"]["$eq"] == expected_baths

    def test_extract_sqft(self):
        """Test extracting square footage."""
        queries = [
            ("800 sqft", 800),
            ("1000 sq ft", 1000),
            ("1200 square feet", 1200),
        ]

        for query, expected_sqft in queries:
            result = _fallback_extract_pinecone_filters(query)
            assert "sqft" in result
            assert result["sqft"]["$eq"] == expected_sqft

    def test_extract_zipcode(self):
        """Test extracting NYC zipcode."""
        result = _fallback_extract_pinecone_filters("apartment in 10001")

        assert "zipcode" in result
        assert result["zipcode"]["$eq"] == "10001"

    def test_extract_multiple_filters(self):
        """Test extracting multiple filters from one query."""
        result = _fallback_extract_pinecone_filters("2br 1ba under $3000 in 10003 at least 800 sqft")

        assert "bedrooms" in result
        assert result["bedrooms"]["$eq"] == 2

        assert "bathrooms" in result
        assert result["bathrooms"]["$eq"] == 1.0

        assert "price" in result
        assert result["price"]["$lt"] == 3000.0

        assert "zipcode" in result
        assert result["zipcode"]["$eq"] == "10003"

    def test_ignores_amenities(self):
        """Test that amenities are NOT extracted (Tier 2 filter)."""
        result = _fallback_extract_pinecone_filters("2br with gym and laundry under $3000")

        assert "bedrooms" in result
        assert "price" in result
        # Should NOT have amenities
        assert "amenities" not in result
        assert "gym" not in str(result)
        assert "laundry" not in str(result)

    def test_ignores_neighborhoods(self):
        """Test that neighborhoods are NOT extracted (Tier 2 filter)."""
        result = _fallback_extract_pinecone_filters("2br in Chelsea under $3000")

        assert "bedrooms" in result
        assert "price" in result
        # Should NOT have neighborhood
        assert "neighborhood" not in result
        assert "chelsea" not in str(result).lower()

    def test_empty_query(self):
        """Test with empty query."""
        result = _fallback_extract_pinecone_filters("")
        assert result == {}

    def test_no_filters_query(self):
        """Test query with no extractable filters."""
        result = _fallback_extract_pinecone_filters("show me apartments near NYU")
        assert result == {}


class TestNormalizePineconeFilters:
    """Tests for _normalize_pinecone_filters function."""

    def test_normalize_valid_filters(self):
        """Test normalizing valid filter dict."""
        filters = {
            "price": {"$lt": 3000},
            "bedrooms": {"$eq": 2},
            "bathrooms": {"$eq": 1.0},
            "sqft": {"$gte": 800},
            "zipcode": {"$eq": "10001"},
        }

        result = _normalize_pinecone_filters(filters)

        assert result["price"]["$lt"] == 3000.0
        assert result["bedrooms"]["$eq"] == 2
        assert result["bathrooms"]["$eq"] == 1.0
        assert result["sqft"]["$gte"] == 800.0
        assert result["zipcode"]["$eq"] == "10001"

    def test_filters_out_invalid_fields(self):
        """Test that non-allowed fields are filtered out."""
        filters = {
            "price": {"$lt": 3000},
            "amenities": ["gym"],  # not allowed in pinecone pre-filters
            "neighborhood": "chelsea",  # not allowed
        }

        result = _normalize_pinecone_filters(filters)

        assert "price" in result
        assert "amenities" not in result
        assert "neighborhood" not in result

    def test_converts_numeric_strings(self):
        """Test converting string numbers to proper types."""
        filters = {
            "price": {"$lt": "3000"},  # string
            "bedrooms": {"$eq": "2"},  # string
        }

        result = _normalize_pinecone_filters(filters)

        assert result["price"]["$lt"] == 3000.0
        assert isinstance(result["price"]["$lt"], float)
        assert result["bedrooms"]["$eq"] == 2
        assert isinstance(result["bedrooms"]["$eq"], int)

    def test_handles_invalid_numeric_values(self):
        """Test handling of invalid numeric values."""
        filters = {
            "price": {"$lt": "invalid"},
            "bedrooms": {"$eq": "not_a_number"},
        }

        result = _normalize_pinecone_filters(filters)

        # Invalid values should be skipped
        assert "price" not in result
        assert "bedrooms" not in result

    def test_preserves_multiple_operators(self):
        """Test preserving multiple operators on same field."""
        filters = {
            "price": {"$gte": 2000, "$lte": 5000},
        }

        result = _normalize_pinecone_filters(filters)

        assert result["price"]["$gte"] == 2000.0
        assert result["price"]["$lte"] == 5000.0

    def test_handles_simple_values(self):
        """Test converting simple values to operator dict."""
        filters = {
            "bedrooms": 2,  # simple value, not dict
            "zipcode": "10001",
        }

        result = _normalize_pinecone_filters(filters)

        assert result["bedrooms"] == {"$eq": 2}
        assert result["zipcode"] == {"$eq": "10001"}

    def test_empty_filters(self):
        """Test with empty filter dict."""
        result = _normalize_pinecone_filters({})
        assert result == {}

    def test_filters_invalid_operators(self):
        """Test that invalid operators are skipped."""
        filters = {
            "price": {"$invalid_op": 3000, "$lt": 2500},
        }

        result = _normalize_pinecone_filters(filters)

        # Should only keep valid operator
        assert result["price"] == {"$lt": 2500.0}
        assert "$invalid_op" not in result["price"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
