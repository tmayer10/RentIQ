"""
Unit tests for chat_utils/session_store.py

Tests Redis session storage for multi-turn conversations using fakeredis.
"""

import pytest
import sys
import os
import time
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import fakeredis for mocking Redis
try:
    import fakeredis
except ImportError:
    pytest.skip("fakeredis not installed. Run: pip install fakeredis", allow_module_level=True)

from session_store import SessionStore, generate_search_id


@pytest.fixture
def fake_redis():
    """Create a fake Redis server for testing."""
    return fakeredis.FakeStrictRedis(decode_responses=True)


@pytest.fixture
def session_store(fake_redis):
    """Create SessionStore with fake Redis client."""
    store = SessionStore(session_ttl=3600)
    store.client = fake_redis  # Replace real Redis with fake
    return store


@pytest.fixture
def sample_filter_state():
    """Sample filter state for testing."""
    return {
        "hard": {
            "price": {"$lt": 3000},
            "bedrooms": {"$eq": 2},
        },
        "amenities": ["gym", "laundry"],
        "neighborhoods": ["east-village"],
        "subway": {
            "routes": ["4", "6"],
            "lines": [],
            "min_distance": None,
            "max_distance": 0.5,
        },
    }


@pytest.fixture
def sample_matches():
    """Sample search matches for testing."""
    return [
        {"metadata": {"listing_id": "123", "price": 2800, "bedrooms": 2}},
        {"metadata": {"listing_id": "456", "price": 2900, "bedrooms": 2}},
        {"metadata": {"listing_id": "789", "price": 2950, "bedrooms": 2}},
    ]


class TestSessionStoreBasics:
    """Basic functionality tests for SessionStore."""

    def test_ping(self, session_store):
        """Test Redis connection check."""
        assert session_store.ping() is True

    def test_key_generation(self, session_store):
        """Test Redis key generation."""
        key = session_store._key("test_session", "messages")
        assert key == "session:test_session:messages"

    def test_session_exists_empty(self, session_store):
        """Test session_exists returns False for new session."""
        assert session_store.session_exists("new_session") is False

    def test_session_exists_after_message(self, session_store):
        """Test session_exists returns True after adding message."""
        session_store.add_message("test_session", "user", "Hello")
        assert session_store.session_exists("test_session") is True


class TestConversationHistory:
    """Tests for conversation message storage and retrieval."""

    def test_add_single_message(self, session_store):
        """Test adding a single message."""
        session_store.add_message("session_1", "user", "Show me apartments")

        messages = session_store.get_messages("session_1")
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Show me apartments"

    def test_add_multiple_messages(self, session_store):
        """Test adding multiple messages in order."""
        session_store.add_message("session_1", "user", "Message 1")
        session_store.add_message("session_1", "assistant", "Message 2")
        session_store.add_message("session_1", "user", "Message 3")

        messages = session_store.get_messages("session_1")
        assert len(messages) == 3
        assert messages[0]["content"] == "Message 1"
        assert messages[1]["content"] == "Message 2"
        assert messages[2]["content"] == "Message 3"

    def test_messages_preserve_order(self, session_store):
        """Test that messages maintain chronological order."""
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            session_store.add_message("session_1", role, f"Message {i}")

        messages = session_store.get_messages("session_1")
        assert len(messages) == 10
        for i, msg in enumerate(messages):
            assert msg["content"] == f"Message {i}"

    def test_messages_isolated_by_session(self, session_store):
        """Test that messages are isolated between sessions."""
        session_store.add_message("session_a", "user", "Message A")
        session_store.add_message("session_b", "user", "Message B")

        messages_a = session_store.get_messages("session_a")
        messages_b = session_store.get_messages("session_b")

        assert len(messages_a) == 1
        assert len(messages_b) == 1
        assert messages_a[0]["content"] == "Message A"
        assert messages_b[0]["content"] == "Message B"

    def test_get_messages_empty_session(self, session_store):
        """Test getting messages from empty session."""
        messages = session_store.get_messages("nonexistent_session")
        assert messages == []

    def test_clear_messages(self, session_store):
        """Test clearing message history."""
        session_store.add_message("session_1", "user", "Message 1")
        session_store.add_message("session_1", "user", "Message 2")

        session_store.clear_messages("session_1")

        messages = session_store.get_messages("session_1")
        assert len(messages) == 0


class TestSearchHistory:
    """Tests for search history storage and retrieval."""

    def test_save_single_search(self, session_store, sample_filter_state, sample_matches):
        """Test saving a single search."""
        search_id = generate_search_id()
        session_store.save_search(
            session_id="session_1",
            search_id=search_id,
            query="2br under $3000",
            filter_state=sample_filter_state,
            matches=sample_matches,
        )

        search = session_store.get_search("session_1", search_id)
        assert search is not None
        assert search["id"] == search_id
        assert search["query"] == "2br under $3000"
        assert search["filter_state"] == sample_filter_state
        assert len(search["matches"]) == 3

    def test_save_multiple_searches(self, session_store, sample_filter_state, sample_matches):
        """Test saving multiple searches."""
        search_id_1 = "search_1"
        search_id_2 = "search_2"

        session_store.save_search("session_1", search_id_1, "Query 1", sample_filter_state, sample_matches)
        session_store.save_search("session_1", search_id_2, "Query 2", sample_filter_state, [])

        all_searches = session_store.get_all_searches("session_1")
        assert len(all_searches) == 2
        assert all_searches[0]["query"] == "Query 1"
        assert all_searches[1]["query"] == "Query 2"

    def test_get_latest_search(self, session_store, sample_filter_state, sample_matches):
        """Test retrieving the most recent search."""
        session_store.save_search("session_1", "search_1", "Query 1", {}, [])
        session_store.save_search("session_1", "search_2", "Query 2", {}, [])
        session_store.save_search("session_1", "search_3", "Query 3", sample_filter_state, sample_matches)

        latest = session_store.get_latest_search("session_1")
        assert latest is not None
        assert latest["query"] == "Query 3"
        assert latest["filter_state"] == sample_filter_state

    def test_get_search_nonexistent(self, session_store):
        """Test getting nonexistent search returns None."""
        search = session_store.get_search("session_1", "nonexistent_search")
        assert search is None

    def test_get_all_searches_empty(self, session_store):
        """Test getting searches from session with no searches."""
        searches = session_store.get_all_searches("new_session")
        assert searches == []

    def test_get_latest_search_empty(self, session_store):
        """Test getting latest search when no searches exist."""
        latest = session_store.get_latest_search("new_session")
        assert latest is None

    def test_search_timestamp_format(self, session_store):
        """Test that search includes valid ISO timestamp."""
        search_id = generate_search_id()
        session_store.save_search("session_1", search_id, "Test query", {}, [])

        search = session_store.get_search("session_1", search_id)
        assert "timestamp" in search
        # Should be able to parse as datetime
        timestamp = datetime.fromisoformat(search["timestamp"])
        assert isinstance(timestamp, datetime)


class TestCurrentSearchContext:
    """Tests for current search context management."""

    def test_set_and_get_current_search_id(self, session_store):
        """Test setting and getting current search ID."""
        session_store.set_current_search_id("session_1", "search_123")

        current_id = session_store.get_current_search_id("session_1")
        assert current_id == "search_123"

    def test_get_current_search(self, session_store, sample_filter_state, sample_matches):
        """Test getting current search data."""
        search_id = "search_active"
        session_store.save_search("session_1", search_id, "Current query", sample_filter_state, sample_matches)
        session_store.set_current_search_id("session_1", search_id)

        current = session_store.get_current_search("session_1")
        assert current is not None
        assert current["id"] == search_id
        assert current["query"] == "Current query"

    def test_get_current_search_id_nonexistent(self, session_store):
        """Test getting current search ID when none set."""
        current_id = session_store.get_current_search_id("new_session")
        assert current_id is None

    def test_get_current_search_nonexistent(self, session_store):
        """Test getting current search when none set."""
        current = session_store.get_current_search("new_session")
        assert current is None

    def test_update_current_search(self, session_store):
        """Test updating current search ID."""
        session_store.set_current_search_id("session_1", "search_1")
        session_store.set_current_search_id("session_1", "search_2")

        current_id = session_store.get_current_search_id("session_1")
        assert current_id == "search_2"


class TestMultiTurnConversation:
    """Tests simulating realistic multi-turn conversation flows."""

    def test_simple_multi_turn_flow(self, session_store, sample_filter_state, sample_matches):
        """Test a simple multi-turn conversation."""
        session_id = "conversation_1"

        # Turn 1: Initial query
        session_store.add_message(session_id, "user", "Show me 2br under $3000")
        search_id_1 = "search_1"
        session_store.save_search(session_id, search_id_1, "2br under $3000", sample_filter_state, sample_matches)
        session_store.set_current_search_id(session_id, search_id_1)
        session_store.add_message(session_id, "assistant", "Here are 3 apartments...")

        # Turn 2: Follow-up question (reuses matches)
        session_store.add_message(session_id, "user", "Do any have a gym?")
        session_store.add_message(session_id, "assistant", "Yes, listing #123 has a gym.")

        # Turn 3: Modify search
        session_store.add_message(session_id, "user", "Change to under $2500")
        modified_filters = sample_filter_state.copy()
        modified_filters["hard"]["price"] = {"$lt": 2500}
        search_id_2 = "search_2"
        session_store.save_search(session_id, search_id_2, "2br under $2500", modified_filters, sample_matches[:2])
        session_store.set_current_search_id(session_id, search_id_2)
        session_store.add_message(session_id, "assistant", "Here are 2 apartments under $2500...")

        # Verify conversation history
        messages = session_store.get_messages(session_id)
        assert len(messages) == 6

        # Verify search history
        all_searches = session_store.get_all_searches(session_id)
        assert len(all_searches) == 2

        # Verify current search is the latest
        current = session_store.get_current_search(session_id)
        assert current["id"] == search_id_2
        assert current["filter_state"]["hard"]["price"]["$lt"] == 2500

    def test_filter_state_preservation(self, session_store):
        """Test that filter states are preserved correctly across turns."""
        session_id = "session_filters"

        # Turn 1: Initial filters
        filters_1 = {
            "hard": {"price": {"$lt": 3000}, "bedrooms": {"$eq": 2}},
            "amenities": ["gym"],
            "neighborhoods": ["chelsea"],
            "subway": {"routes": ["1"], "lines": [], "min_distance": None, "max_distance": 0.5},
        }
        session_store.save_search(session_id, "search_1", "Query 1", filters_1, [])

        # Turn 2: Modified filters (changed price, added amenity)
        filters_2 = {
            "hard": {"price": {"$lt": 4000}, "bedrooms": {"$eq": 2}},
            "amenities": ["gym", "doorman"],
            "neighborhoods": ["chelsea"],
            "subway": {"routes": ["1"], "lines": [], "min_distance": None, "max_distance": 0.5},
        }
        session_store.save_search(session_id, "search_2", "Query 2", filters_2, [])

        # Turn 3: Modified filters (changed neighborhood)
        filters_3 = {
            "hard": {"price": {"$lt": 4000}, "bedrooms": {"$eq": 2}},
            "amenities": ["gym", "doorman"],
            "neighborhoods": ["east-village"],
            "subway": {"routes": ["1"], "lines": [], "min_distance": None, "max_distance": 0.5},
        }
        session_store.save_search(session_id, "search_3", "Query 3", filters_3, [])

        # Verify each search preserved its filter state
        all_searches = session_store.get_all_searches(session_id)
        assert len(all_searches) == 3

        assert all_searches[0]["filter_state"]["hard"]["price"]["$lt"] == 3000
        assert all_searches[0]["filter_state"]["amenities"] == ["gym"]

        assert all_searches[1]["filter_state"]["hard"]["price"]["$lt"] == 4000
        assert all_searches[1]["filter_state"]["amenities"] == ["gym", "doorman"]

        assert all_searches[2]["filter_state"]["neighborhoods"] == ["east-village"]

    def test_matches_preservation(self, session_store):
        """Test that matches are preserved correctly across turns."""
        session_id = "session_matches"

        matches_1 = [{"listing_id": "123"}, {"listing_id": "456"}]
        matches_2 = [{"listing_id": "789"}]

        session_store.save_search(session_id, "search_1", "Query 1", {}, matches_1)
        session_store.save_search(session_id, "search_2", "Query 2", {}, matches_2)

        search_1 = session_store.get_search(session_id, "search_1")
        search_2 = session_store.get_search(session_id, "search_2")

        assert len(search_1["matches"]) == 2
        assert search_1["matches"][0]["listing_id"] == "123"

        assert len(search_2["matches"]) == 1
        assert search_2["matches"][0]["listing_id"] == "789"

    def test_concurrent_sessions(self, session_store):
        """Test multiple concurrent user sessions."""
        # Session 1
        session_store.add_message("user_a", "user", "2br in Chelsea")
        session_store.save_search("user_a", "search_a1", "Query A1", {}, [])

        # Session 2
        session_store.add_message("user_b", "user", "3br in Tribeca")
        session_store.save_search("user_b", "search_b1", "Query B1", {}, [])

        # Continue Session 1
        session_store.add_message("user_a", "assistant", "Response A1")
        session_store.add_message("user_a", "user", "Under $4000")

        # Continue Session 2
        session_store.add_message("user_b", "assistant", "Response B1")

        # Verify isolation
        messages_a = session_store.get_messages("user_a")
        messages_b = session_store.get_messages("user_b")

        assert len(messages_a) == 3
        assert len(messages_b) == 2
        assert messages_a[0]["content"] == "2br in Chelsea"
        assert messages_b[0]["content"] == "3br in Tribeca"


class TestSessionManagement:
    """Tests for session cleanup and management."""

    def test_clear_session(self, session_store, sample_filter_state, sample_matches):
        """Test clearing all session data."""
        session_id = "session_to_clear"

        # Add data
        session_store.add_message(session_id, "user", "Message 1")
        session_store.add_message(session_id, "user", "Message 2")
        session_store.save_search(session_id, "search_1", "Query 1", sample_filter_state, sample_matches)
        session_store.save_search(session_id, "search_2", "Query 2", {}, [])
        session_store.set_current_search_id(session_id, "search_2")

        # Verify data exists
        assert len(session_store.get_messages(session_id)) == 2
        assert len(session_store.get_all_searches(session_id)) == 2
        assert session_store.get_current_search_id(session_id) is not None

        # Clear session
        session_store.clear_session(session_id)

        # Verify all data cleared
        assert len(session_store.get_messages(session_id)) == 0
        assert len(session_store.get_all_searches(session_id)) == 0
        assert session_store.get_current_search_id(session_id) is None
        assert session_store.session_exists(session_id) is False

    def test_clear_session_doesnt_affect_other_sessions(self, session_store):
        """Test that clearing one session doesn't affect others."""
        session_store.add_message("session_a", "user", "Message A")
        session_store.add_message("session_b", "user", "Message B")

        session_store.clear_session("session_a")

        # Session B should still exist
        messages_b = session_store.get_messages("session_b")
        assert len(messages_b) == 1
        assert messages_b[0]["content"] == "Message B"


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_generate_search_id_format(self):
        """Test search ID generation format."""
        search_id = generate_search_id()

        # Should be timestamp format: YYYYMMDD_HHMMSS_ffffff
        assert len(search_id) >= 21  # Minimum length
        assert "_" in search_id
        parts = search_id.split("_")
        assert len(parts) == 3
        assert len(parts[0]) == 8  # YYYYMMDD
        assert len(parts[1]) == 6  # HHMMSS

    def test_generate_search_id_uniqueness(self):
        """Test that generated search IDs are unique."""
        id1 = generate_search_id()
        time.sleep(0.001)  # Small delay to ensure different microsecond
        id2 = generate_search_id()

        assert id1 != id2


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_message_content(self, session_store):
        """Test storing message with empty content."""
        session_store.add_message("session_1", "user", "")

        messages = session_store.get_messages("session_1")
        assert len(messages) == 1
        assert messages[0]["content"] == ""

    def test_special_characters_in_messages(self, session_store):
        """Test messages with special characters."""
        special_message = "Test with \"quotes\", 'apostrophes', and symbols: $@#%"
        session_store.add_message("session_1", "user", special_message)

        messages = session_store.get_messages("session_1")
        assert messages[0]["content"] == special_message

    def test_large_match_list(self, session_store):
        """Test storing large number of matches."""
        large_matches = [{"id": str(i), "price": 2000 + i} for i in range(100)]

        session_store.save_search("session_1", "search_1", "Query", {}, large_matches)

        search = session_store.get_search("session_1", "search_1")
        assert len(search["matches"]) == 100

    def test_complex_filter_state(self, session_store):
        """Test storing complex nested filter state."""
        complex_filters = {
            "hard": {
                "price": {"$gte": 2000, "$lte": 5000},
                "bedrooms": {"$eq": 2},
                "bathrooms": {"$gte": 1.5},
            },
            "amenities": ["gym", "doorman", "elevator", "laundry", "parking"],
            "neighborhoods": ["chelsea", "tribeca", "soho", "noho"],
            "subway": {
                "routes": ["1", "2", "3", "a", "c", "e"],
                "lines": ["broadway", "8th avenue"],
                "min_distance": 0.1,
                "max_distance": 0.8,
            },
        }

        session_store.save_search("session_1", "search_1", "Complex query", complex_filters, [])

        search = session_store.get_search("session_1", "search_1")
        assert search["filter_state"] == complex_filters


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
