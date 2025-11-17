"""
Unit tests for chat_utils/scorer.py
"""

import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scorer import score_listing, score_listings


class TestScoreListing:
    """Tests for score_listing function."""

    def test_perfect_match(self, mock_match, sample_criteria):
        """Test scoring a perfect match."""
        # mock_match has all the criteria from sample_criteria
        score, compromises = score_listing(mock_match, sample_criteria)

        # Should have high score and no compromises
        assert score > 80
        assert len(compromises) == 0

    def test_bedrooms_mismatch(self, create_match):
        """Test scoring when bedrooms don't match."""
        match = create_match(bedrooms=3)
        criteria = {"bedrooms": {"$eq": 2}}

        score, compromises = score_listing(match, criteria)

        assert any("bedrooms" in c for c in compromises)

    def test_bathrooms_mismatch(self, create_match):
        """Test scoring when bathrooms don't match."""
        match = create_match(bathrooms=2.0)
        criteria = {"bathrooms": {"$eq": 1.0}}

        score, compromises = score_listing(match, criteria)

        assert any("bathrooms" in c for c in compromises)

    def test_price_under_budget(self, create_match):
        """Test scoring with price under budget."""
        match = create_match(price=2500)
        criteria = {"price": {"$lt": 3000}}

        score, compromises = score_listing(match, criteria)

        # Should get points for being under budget
        assert score > 0
        assert not any("budget" in c for c in compromises)

    def test_price_over_budget(self, create_match):
        """Test scoring with price over budget."""
        match = create_match(price=3500)
        criteria = {"price": {"$lt": 3000}}

        score, compromises = score_listing(match, criteria)

        assert any("budget" in c for c in compromises)

    def test_neighborhood_match(self, create_match):
        """Test scoring with matching neighborhood."""
        match = create_match(neighborhood="chelsea")
        criteria = {"neighborhoods": ["chelsea", "east-village"]}

        score, compromises = score_listing(match, criteria)

        assert score > 0
        assert not any("neighborhood" in c for c in compromises)

    def test_neighborhood_mismatch(self, create_match):
        """Test scoring with non-matching neighborhood."""
        match = create_match(neighborhood="harlem")
        criteria = {"neighborhoods": ["chelsea", "east-village"]}

        score, compromises = score_listing(match, criteria)

        assert any("neighborhood" in c for c in compromises)

    def test_amenities_full_coverage(self, create_match):
        """Test scoring with all desired amenities present."""
        match = create_match(amenities=["gym", "laundry", "elevator", "parking"])
        criteria = {"amenities": ["gym", "laundry"]}

        score, compromises = score_listing(match, criteria)

        # Should get full amenities score
        assert score > 0
        assert not any("amenities" in c for c in compromises)

    def test_amenities_partial_coverage(self, create_match):
        """Test scoring with only some amenities present."""
        match = create_match(amenities=["gym"])
        criteria = {"amenities": ["gym", "laundry", "parking"]}

        score, compromises = score_listing(match, criteria)

        # Should have compromise for missing amenities
        assert any("amenities" in c for c in compromises)
        assert "laundry" in compromises[0] or "parking" in compromises[0]

    def test_amenities_no_coverage(self, create_match):
        """Test scoring with no desired amenities."""
        match = create_match(amenities=["elevator"])
        criteria = {"amenities": ["gym", "laundry"]}

        score, compromises = score_listing(match, criteria)

        assert any("amenities" in c for c in compromises)

    def test_subway_route_match(self, create_match):
        """Test scoring with matching subway route."""
        match = create_match(
            subway_routes=["4", "6"],
            route_distances={"4": 0.15, "6": 0.25},
            subway_min_distance=0.15,
        )
        criteria = {"subway": {"routes": ["4"], "lines": [], "max_distance": 0.5}}

        score, compromises = score_listing(match, criteria)

        assert score > 0
        assert not any("subway" in c.lower() for c in compromises)

    def test_subway_route_mismatch(self, create_match):
        """Test scoring with non-matching subway route."""
        match = create_match(
            subway_routes=["a", "c"],
            subway_min_distance=0.2,
        )
        criteria = {"subway": {"routes": ["4", "6"], "lines": [], "max_distance": None}}

        score, compromises = score_listing(match, criteria)

        assert any("route" in c.lower() for c in compromises)

    def test_subway_distance_within_limit(self, create_match):
        """Test scoring with subway within distance limit."""
        match = create_match(subway_min_distance=0.3)
        criteria = {"subway": {"routes": [], "lines": [], "max_distance": 0.5}}

        score, compromises = score_listing(match, criteria)

        assert not any("farther" in c for c in compromises)

    def test_subway_distance_exceeds_limit(self, create_match):
        """Test scoring with subway exceeding distance limit."""
        match = create_match(subway_min_distance=0.8)
        criteria = {"subway": {"routes": [], "lines": [], "max_distance": 0.5}}

        score, compromises = score_listing(match, criteria)

        assert any("farther" in c for c in compromises)

    def test_empty_criteria(self, mock_match):
        """Test scoring with no criteria."""
        score, compromises = score_listing(mock_match, {})

        # Should return 0 score with no criteria
        assert score == 0
        assert len(compromises) == 0

    def test_score_range(self, mock_match, sample_criteria):
        """Test that score is within valid range."""
        score, compromises = score_listing(mock_match, sample_criteria)

        assert 0 <= score <= 100


class TestScoreListings:
    """Tests for score_listings function."""

    def test_score_multiple_listings(self, create_match, sample_criteria):
        """Test scoring multiple listings."""
        matches = [
            create_match(listing_id="1", price=2500, bedrooms=2, amenities=["gym", "laundry"]),
            create_match(listing_id="2", price=2800, bedrooms=2, amenities=["gym"]),
            create_match(listing_id="3", price=3200, bedrooms=3, amenities=[]),
        ]

        scored = score_listings(matches, sample_criteria)

        assert len(scored) == 3
        # Each result should be (match, score, compromises)
        assert all(len(item) == 3 for item in scored)

    def test_sorted_by_score_descending(self, create_match):
        """Test that results are sorted by score (highest first)."""
        criteria = {"price": {"$lt": 3000}, "bedrooms": {"$eq": 2}}

        matches = [
            create_match(listing_id="low", price=3500, bedrooms=3),  # worst match
            create_match(listing_id="high", price=2500, bedrooms=2),  # best match
            create_match(listing_id="mid", price=2800, bedrooms=2),  # good match
        ]

        scored = score_listings(matches, criteria)

        # Should be sorted high -> mid -> low
        assert scored[0][0].metadata["listing_id"] == "high"
        assert scored[1][0].metadata["listing_id"] == "mid"
        assert scored[2][0].metadata["listing_id"] == "low"

        # Scores should be descending
        assert scored[0][1] >= scored[1][1] >= scored[2][1]

    def test_empty_matches_list(self):
        """Test with empty matches list."""
        scored = score_listings([], {"price": {"$lt": 3000}})
        assert len(scored) == 0

    def test_return_structure(self, create_match, sample_criteria):
        """Test the structure of returned data."""
        matches = [create_match()]
        scored = score_listings(matches, sample_criteria)

        assert len(scored) == 1
        match, score, compromises = scored[0]

        # Check types
        assert hasattr(match, "metadata")
        assert isinstance(score, (int, float))
        assert isinstance(compromises, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
