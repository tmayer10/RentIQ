"""
Unit tests for chat_utils/utils.py
"""

import pytest
from decimal import Decimal
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import build_text, sanitize_metadata, deduplicate_matches


class TestBuildText:
    """Tests for build_text function."""

    def test_build_text_complete_row(self, sample_listing_row):
        """Test building text from a complete database row."""
        text = build_text(sample_listing_row)

        # Check that key information is included
        assert "4883693" in text  # listing_id
        assert "Beautiful 2BR apartment" in text  # description
        assert "$2800" in text  # price
        assert "2 bedrooms" in text
        assert "1.0 bathrooms" in text
        assert "850 sqft" in text
        assert "east-village" in text
        assert "manhattan" in text
        assert "10003" in text
        assert "123 Avenue A" in text
        assert "laundry, gym, elevator, hardwood_floors" in text
        assert "Lexington" in text or "subway" in text.lower()

    def test_build_text_missing_amenities(self):
        """Test with None amenity_list."""
        row = (
            "123", "Test listing", 2500, 1, 1.0, 600,
            "chelsea", "manhattan", "10001", 2015,
            "100 Main St", Decimal("40.75"), Decimal("-73.99"), 2015,
            None,  # amenity_list is None
            "1 train (0.2 miles)",
            ["broadway"], ["1"], [0.2]
        )
        text = build_text(row)
        assert "No amenities listed" in text

    def test_build_text_missing_subway(self):
        """Test with None subway_info."""
        row = (
            "123", "Test listing", 2500, 1, 1.0, 600,
            "chelsea", "manhattan", "10001", 2015,
            "100 Main St", Decimal("40.75"), Decimal("-73.99"), 2015,
            "gym, laundry",
            None,  # subway_info is None
            [], [], []
        )
        text = build_text(row)
        assert "No nearby subway stations" in text


class TestSanitizeMetadata:
    """Tests for sanitize_metadata function."""

    def test_sanitize_complete_metadata(self, sample_metadata):
        """Test sanitizing a complete metadata dict."""
        clean = sanitize_metadata(sample_metadata)

        # All fields should be present
        assert clean["listing_id"] == "4883693"
        assert clean["price"] == 2800
        assert clean["bedrooms"] == 2
        assert clean["neighborhood"] == "east-village"
        assert isinstance(clean["amenities"], list)
        assert len(clean["amenities"]) == 4

    def test_sanitize_removes_none_values(self):
        """Test that None values are removed."""
        metadata = {
            "listing_id": "123",
            "price": 2500,
            "sqft": None,
            "amenities": ["gym"],
        }
        clean = sanitize_metadata(metadata)

        assert "listing_id" in clean
        assert "price" in clean
        assert "sqft" not in clean
        assert "amenities" in clean

    def test_sanitize_converts_decimal(self):
        """Test that Decimal types are converted to float."""
        metadata = {
            "price": Decimal("2500.50"),
            "latitude": Decimal("40.7128"),
        }
        clean = sanitize_metadata(metadata)

        assert isinstance(clean["price"], float)
        assert clean["price"] == 2500.5
        assert isinstance(clean["latitude"], float)

    def test_sanitize_preserves_types(self):
        """Test that basic types are preserved."""
        metadata = {
            "listing_id": "123",
            "price": 2500,
            "sqft": 850.5,
            "no_fee": True,
            "amenities": ["gym", "laundry"],
            "route_distances": {"1": 0.2, "2": 0.3},
        }
        clean = sanitize_metadata(metadata)

        assert isinstance(clean["listing_id"], str)
        assert isinstance(clean["price"], int)
        assert isinstance(clean["sqft"], float)
        assert isinstance(clean["no_fee"], bool)
        assert isinstance(clean["amenities"], list)
        assert isinstance(clean["route_distances"], dict)

    def test_sanitize_converts_unknown_types_to_string(self):
        """Test that unknown types are converted to strings."""
        class CustomType:
            def __str__(self):
                return "custom_value"

        metadata = {
            "listing_id": "123",
            "custom_field": CustomType(),
        }
        clean = sanitize_metadata(metadata)

        assert isinstance(clean["custom_field"], str)
        assert clean["custom_field"] == "custom_value"


class TestDeduplicateMatches:
    """Tests for deduplicate_matches function."""

    def test_no_duplicates(self, create_match):
        """Test with unique matches."""
        matches = [
            create_match(listing_id="123"),
            create_match(listing_id="456"),
            create_match(listing_id="789"),
        ]

        unique = deduplicate_matches(matches)
        assert len(unique) == 3
        assert unique[0].metadata["listing_id"] == "123"
        assert unique[1].metadata["listing_id"] == "456"
        assert unique[2].metadata["listing_id"] == "789"

    def test_with_duplicates(self, create_match):
        """Test removing duplicate listing_ids."""
        matches = [
            create_match(listing_id="123", price=2500),
            create_match(listing_id="456", price=3000),
            create_match(listing_id="123", price=2600),  # duplicate
            create_match(listing_id="789", price=2800),
            create_match(listing_id="456", price=3100),  # duplicate
        ]

        unique = deduplicate_matches(matches)
        assert len(unique) == 3

        # Should keep first occurrence
        ids = [m.metadata["listing_id"] for m in unique]
        assert ids == ["123", "456", "789"]
        assert unique[0].metadata["price"] == 2500  # first 123
        assert unique[1].metadata["price"] == 3000  # first 456

    def test_empty_list(self):
        """Test with empty list."""
        matches = []
        unique = deduplicate_matches(matches)
        assert len(unique) == 0

    def test_all_duplicates(self, create_match):
        """Test with all duplicate IDs."""
        matches = [
            create_match(listing_id="123", price=2500),
            create_match(listing_id="123", price=2600),
            create_match(listing_id="123", price=2700),
        ]

        unique = deduplicate_matches(matches)
        assert len(unique) == 1
        assert unique[0].metadata["listing_id"] == "123"
        assert unique[0].metadata["price"] == 2500  # first occurrence


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
