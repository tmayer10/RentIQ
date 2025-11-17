"""
Pytest configuration and fixtures for chat_utils tests.
"""

import pytest
from decimal import Decimal
from typing import Dict, Any, List


# ========== Mock Data Fixtures ==========

@pytest.fixture
def sample_listing_row():
    """Sample database row for testing build_text and ingest functions."""
    return (
        "4883693",  # listing_id
        "Beautiful 2BR apartment with modern amenities",  # description
        Decimal("2800.00"),  # price
        2,  # bedrooms
        1.0,  # bathrooms
        850,  # sqft
        "east-village",  # neighborhood
        "manhattan",  # borough
        "10003",  # zipcode
        2010,  # built_in
        "123 Avenue A",  # building_address
        Decimal("40.725"),  # building_lat
        Decimal("-73.985"),  # building_lon
        2010,  # building_built_in
        "laundry, gym, elevator, hardwood_floors",  # amenity_list
        "Lexington (4) Train (0.15 miles); Broadway (N) Train (0.25 miles)",  # subway_info
        ["lexington", "broadway"],  # subway_lines
        ["4", "n"],  # subway_routes
        [0.15, 0.25],  # subway_distances
    )


@pytest.fixture
def sample_metadata():
    """Sample Pinecone metadata for testing."""
    return {
        "listing_id": "4883693",
        "price": 2800,
        "bedrooms": 2,
        "bathrooms": 1.0,
        "sqft": 850,
        "borough": "manhattan",
        "neighborhood": "east-village",
        "zipcode": "10003",
        "building_address": "123 Avenue A",
        "amenities": ["laundry", "gym", "elevator", "hardwood_floors"],
        "subway_routes": ["4", "n"],
        "subway_lines": ["lexington", "broadway"],
        "subway_min_distance": 0.15,
        "route_distances": {"4": 0.15, "n": 0.25},
        "description": "Beautiful 2BR apartment with modern amenities",
    }


@pytest.fixture
def mock_match(sample_metadata):
    """Mock Pinecone match object."""
    class MockMatch:
        def __init__(self, metadata: Dict[str, Any], score: float = 0.85):
            self.metadata = metadata
            self.score = score
            self.id = metadata.get("listing_id", "test_id")

    return MockMatch(sample_metadata)


@pytest.fixture
def sample_chat_history():
    """Sample chat history for multi-turn testing."""
    return [
        {"role": "user", "content": "Show me 2br apartments under $3000"},
        {"role": "assistant", "content": "Here are 5 apartments matching your criteria..."},
        {"role": "user", "content": "Do any of them have a gym?"},
        {"role": "assistant", "content": "Yes, listings #4883693 and #4887234 have gyms."},
    ]


@pytest.fixture
def sample_filter_state():
    """Sample filter state (new format with hard + soft filters)."""
    return {
        "hard": {
            "price": {"$lt": 3000},
            "bedrooms": {"$eq": 2},
        },
        "amenities": ["gym", "laundry"],
        "neighborhoods": ["east-village", "greenwich-village"],
        "subway": {
            "routes": ["4", "6"],
            "lines": [],
            "min_distance": None,
            "max_distance": 0.5,
        },
    }


@pytest.fixture
def sample_criteria():
    """Sample search criteria for scorer tests."""
    return {
        "price": {"$lt": 3000},
        "bedrooms": {"$eq": 2},
        "bathrooms": {"$eq": 1.0},
        "amenities": ["gym", "laundry"],
        "neighborhoods": ["east-village"],
        "subway": {
            "routes": ["4", "6"],
            "lines": [],
            "max_distance": 0.5,
        },
    }


# ========== Helper Functions ==========

@pytest.fixture
def create_filter_dict():
    """Factory fixture for creating filter dictionaries."""
    def _create(price_lt=None, bedrooms=None, bathrooms=None, sqft_gte=None, zipcode=None):
        filters = {}
        if price_lt is not None:
            filters["price"] = {"$lt": price_lt}
        if bedrooms is not None:
            filters["bedrooms"] = {"$eq": bedrooms}
        if bathrooms is not None:
            filters["bathrooms"] = {"$eq": bathrooms}
        if sqft_gte is not None:
            filters["sqft"] = {"$gte": sqft_gte}
        if zipcode is not None:
            filters["zipcode"] = {"$eq": zipcode}
        return filters
    return _create


@pytest.fixture
def create_match():
    """Factory fixture for creating mock match objects."""
    def _create(
        listing_id: str = "test_id",
        price: float = 2500,
        bedrooms: int = 2,
        bathrooms: float = 1.0,
        neighborhood: str = "chelsea",
        amenities: List[str] = None,
        subway_routes: List[str] = None,
        subway_min_distance: float = 0.3,
        route_distances: Dict[str, float] = None,
        score: float = 0.85,
    ):
        amenities = amenities or []
        subway_routes = subway_routes or []
        route_distances = route_distances or {}

        class MockMatch:
            def __init__(self):
                self.metadata = {
                    "listing_id": listing_id,
                    "price": price,
                    "bedrooms": bedrooms,
                    "bathrooms": bathrooms,
                    "neighborhood": neighborhood,
                    "amenities": amenities,
                    "subway_routes": subway_routes,
                    "subway_min_distance": subway_min_distance,
                    "route_distances": route_distances,
                }
                self.score = score
                self.id = listing_id

        return MockMatch()
    return _create
