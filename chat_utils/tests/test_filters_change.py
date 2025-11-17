"""
Unit tests for chat_utils/filters_change.py
"""

import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from filters_change import normalize_filter_dict, have_filters_changed


class TestNormalizeFilterDict:
    """Tests for normalize_filter_dict function."""

    def test_normalize_empty_dict(self):
        """Test normalizing an empty dict."""
        result = normalize_filter_dict({})
        assert result == {}

    def test_normalize_none(self):
        """Test normalizing None."""
        result = normalize_filter_dict(None)
        assert result == {}

    def test_normalize_simple_filters(self):
        """Test normalizing simple filter dict."""
        filters = {
            "price": {"$lt": 3000},
            "bedrooms": {"$eq": 2},
        }
        result = normalize_filter_dict(filters)

        assert "price" in result
        assert "bedrooms" in result
        assert result["price"]["$lt"] == 3000.0
        assert result["bedrooms"]["$eq"] == 2.0

    def test_normalize_converts_numeric_types(self):
        """Test that int/float values are normalized to float."""
        filters = {
            "price": {"$lt": 3000},  # int
            "sqft": {"$gte": 800.5},  # float
        }
        result = normalize_filter_dict(filters)

        assert isinstance(result["price"]["$lt"], float)
        assert isinstance(result["sqft"]["$gte"], float)
        assert result["price"]["$lt"] == 3000.0
        assert result["sqft"]["$gte"] == 800.5

    def test_normalize_sorts_keys(self):
        """Test that keys are sorted for consistent comparison."""
        filters = {
            "zipcode": {"$eq": "10001"},
            "bedrooms": {"$eq": 2},
            "price": {"$lt": 3000},
        }
        result = normalize_filter_dict(filters)
        keys = list(result.keys())

        assert keys == ["bedrooms", "price", "zipcode"]

    def test_normalize_nested_operators(self):
        """Test that nested operators are also sorted."""
        filters = {
            "price": {"$lte": 5000, "$gte": 2000},
        }
        result = normalize_filter_dict(filters)
        ops = list(result["price"].keys())

        assert ops == ["$gte", "$lte"]


class TestHaveFiltersChanged:
    """Tests for have_filters_changed function."""

    # ========== Old Format Tests (backward compatibility) ==========

    def test_no_change_old_format(self):
        """Test no change with old format (just hard filters)."""
        prev = {
            "price": {"$lt": 3000},
            "bedrooms": {"$eq": 2},
        }
        curr = {
            "price": {"$lt": 3000},
            "bedrooms": {"$eq": 2},
        }

        assert not have_filters_changed(prev, curr)

    def test_price_changed_old_format(self):
        """Test price change detection (old format)."""
        prev = {"price": {"$lt": 3000}}
        curr = {"price": {"$lt": 4000}}

        assert have_filters_changed(prev, curr)

    def test_bedrooms_changed_old_format(self):
        """Test bedrooms change detection (old format)."""
        prev = {"bedrooms": {"$eq": 2}}
        curr = {"bedrooms": {"$eq": 3}}

        assert have_filters_changed(prev, curr)

    def test_operator_changed_old_format(self):
        """Test operator change detection (old format)."""
        prev = {"price": {"$lt": 3000}}
        curr = {"price": {"$lte": 3000}}

        assert have_filters_changed(prev, curr)

    def test_filter_added_old_format(self):
        """Test adding a new filter (old format)."""
        prev = {"price": {"$lt": 3000}}
        curr = {"price": {"$lt": 3000}, "bedrooms": {"$eq": 2}}

        assert have_filters_changed(prev, curr)

    def test_filter_removed_old_format(self):
        """Test removing a filter (old format)."""
        prev = {"price": {"$lt": 3000}, "bedrooms": {"$eq": 2}}
        curr = {"price": {"$lt": 3000}}

        assert have_filters_changed(prev, curr)

    # ========== New Format Tests ==========

    def test_no_change_new_format(self, sample_filter_state):
        """Test no change with new format (hard + soft filters)."""
        prev = sample_filter_state.copy()
        curr = sample_filter_state.copy()

        assert not have_filters_changed(prev, curr)

    def test_hard_filter_changed_new_format(self):
        """Test hard filter change in new format."""
        prev = {
            "hard": {"price": {"$lt": 3000}, "bedrooms": {"$eq": 2}},
            "amenities": ["gym"],
            "neighborhoods": [],
            "subway": {},
        }
        curr = {
            "hard": {"price": {"$lt": 4000}, "bedrooms": {"$eq": 2}},  # price changed
            "amenities": ["gym"],
            "neighborhoods": [],
            "subway": {},
        }

        assert have_filters_changed(prev, curr)

    def test_amenities_changed_new_format(self):
        """Test amenities change detection."""
        prev = {
            "hard": {"price": {"$lt": 3000}},
            "amenities": ["gym", "laundry"],
            "neighborhoods": [],
            "subway": {},
        }
        curr = {
            "hard": {"price": {"$lt": 3000}},
            "amenities": ["gym", "doorman"],  # amenities changed
            "neighborhoods": [],
            "subway": {},
        }

        assert have_filters_changed(prev, curr)

    def test_amenities_order_doesnt_matter(self):
        """Test that amenities order doesn't trigger change."""
        prev = {
            "hard": {},
            "amenities": ["gym", "laundry", "parking"],
            "neighborhoods": [],
            "subway": {},
        }
        curr = {
            "hard": {},
            "amenities": ["parking", "gym", "laundry"],  # same, different order
            "neighborhoods": [],
            "subway": {},
        }

        assert not have_filters_changed(prev, curr)

    def test_neighborhoods_changed_new_format(self):
        """Test neighborhoods change detection."""
        prev = {
            "hard": {},
            "amenities": [],
            "neighborhoods": ["chelsea", "east-village"],
            "subway": {},
        }
        curr = {
            "hard": {},
            "amenities": [],
            "neighborhoods": ["chelsea", "west-village"],  # neighborhoods changed
            "subway": {},
        }

        assert have_filters_changed(prev, curr)

    def test_subway_routes_changed(self):
        """Test subway routes change detection."""
        prev = {
            "hard": {},
            "amenities": [],
            "neighborhoods": [],
            "subway": {"routes": ["1", "2"], "lines": [], "max_distance": 0.5},
        }
        curr = {
            "hard": {},
            "amenities": [],
            "neighborhoods": [],
            "subway": {"routes": ["a", "c"], "lines": [], "max_distance": 0.5},  # routes changed
        }

        assert have_filters_changed(prev, curr)

    def test_subway_distance_changed(self):
        """Test subway max_distance change detection."""
        prev = {
            "hard": {},
            "amenities": [],
            "neighborhoods": [],
            "subway": {"routes": ["1"], "lines": [], "max_distance": 0.5},
        }
        curr = {
            "hard": {},
            "amenities": [],
            "neighborhoods": [],
            "subway": {"routes": ["1"], "lines": [], "max_distance": 1.0},  # distance changed
        }

        assert have_filters_changed(prev, curr)

    def test_subway_lines_changed(self):
        """Test subway lines change detection."""
        prev = {
            "hard": {},
            "amenities": [],
            "neighborhoods": [],
            "subway": {"routes": [], "lines": ["lexington"], "max_distance": None},
        }
        curr = {
            "hard": {},
            "amenities": [],
            "neighborhoods": [],
            "subway": {"routes": [], "lines": ["broadway"], "max_distance": None},  # lines changed
        }

        assert have_filters_changed(prev, curr)

    # ========== Mixed Format Tests ==========

    def test_old_to_new_format_transition(self):
        """Test comparing old format to new format."""
        prev = {"price": {"$lt": 3000}, "bedrooms": {"$eq": 2}}  # old format
        curr = {  # new format
            "hard": {"price": {"$lt": 3000}, "bedrooms": {"$eq": 2}},
            "amenities": [],
            "neighborhoods": [],
            "subway": {},
        }

        # Should not detect change (hard filters are same)
        assert not have_filters_changed(prev, curr)

    def test_old_to_new_format_with_hard_change(self):
        """Test old->new format with hard filter change."""
        prev = {"price": {"$lt": 3000}}  # old format
        curr = {  # new format with different price
            "hard": {"price": {"$lt": 4000}},
            "amenities": [],
            "neighborhoods": [],
            "subway": {},
        }

        assert have_filters_changed(prev, curr)

    # ========== Edge Cases ==========

    def test_empty_to_filters(self):
        """Test transition from no filters to some filters."""
        prev = {}
        curr = {"price": {"$lt": 3000}}

        assert have_filters_changed(prev, curr)

    def test_filters_to_empty(self):
        """Test clearing all filters."""
        prev = {"price": {"$lt": 3000}}
        curr = {}

        assert have_filters_changed(prev, curr)

    def test_both_none(self):
        """Test both filters are None."""
        assert not have_filters_changed(None, None)

    def test_prev_none(self):
        """Test prev is None."""
        curr = {"price": {"$lt": 3000}}
        assert have_filters_changed(None, curr)

    def test_curr_none(self):
        """Test curr is None."""
        prev = {"price": {"$lt": 3000}}
        assert have_filters_changed(prev, None)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
