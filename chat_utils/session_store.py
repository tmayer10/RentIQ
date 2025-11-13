"""Redis-based session store for managing multi-turn conversation state.

This module provides a simple interface to store and retrieve:
- Conversation history (messages)
- Search history (queries, filters, matches)
- Current search context

Each session is isolated by session_id to support multiple concurrent users.
"""

import os
import json
import redis
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()


class SessionStore:
    """Redis-backed session storage for RentIQ chat conversations."""

    def __init__(self, redis_url: Optional[str] = None, session_ttl: int = 3600):
        """Initialize Redis connection.

        Args:
            redis_url: Redis connection URL (default: from REDIS_URL env var)
            session_ttl: Session time-to-live in seconds (default: 1 hour)
        """
        redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.client = redis.from_url(redis_url, decode_responses=True)
        self.session_ttl = session_ttl

    def _key(self, session_id: str, suffix: str) -> str:
        """Generate Redis key with session prefix."""
        return f"session:{session_id}:{suffix}"

    def _extend_ttl(self, session_id: str, key: str):
        """Extend TTL on key to keep session active."""
        self.client.expire(key, self.session_ttl)

    # ========== Conversation History ==========

    def get_messages(self, session_id: str) -> List[Dict[str, str]]:
        """Retrieve conversation history for a session.

        Returns:
            List of message dicts with 'role' and 'content' keys
        """
        key = self._key(session_id, "messages")
        messages_json = self.client.lrange(key, 0, -1)
        self._extend_ttl(session_id, key)
        return [json.loads(msg) for msg in messages_json]

    def add_message(self, session_id: str, role: str, content: str):
        """Append a message to conversation history.

        Args:
            session_id: Session identifier
            role: Message role ('user', 'assistant', 'system')
            content: Message content
        """
        key = self._key(session_id, "messages")
        message = {"role": role, "content": content}
        self.client.rpush(key, json.dumps(message))
        self._extend_ttl(session_id, key)

    def clear_messages(self, session_id: str):
        """Clear conversation history for a session."""
        key = self._key(session_id, "messages")
        self.client.delete(key)

    # ========== Search History ==========

    def save_search(
        self,
        session_id: str,
        search_id: str,
        query: str,
        filter_state: Dict[str, Any],
        matches: List[Dict[str, Any]],
    ):
        """Save a search to history.

        Args:
            session_id: Session identifier
            search_id: Unique search identifier (e.g., timestamp or UUID)
            query: User query string
            filter_state: Complete filter state (hard + soft filters)
            matches: List of retrieved matches (metadata dicts)
        """
        search_data = {
            "id": search_id,
            "query": query,
            "filter_state": filter_state,
            "matches": matches,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Store search data
        search_key = self._key(session_id, f"search:{search_id}")
        self.client.set(search_key, json.dumps(search_data), ex=self.session_ttl)

        # Add search ID to search history list
        searches_key = self._key(session_id, "searches")
        self.client.rpush(searches_key, search_id)
        self._extend_ttl(session_id, searches_key)

    def get_search(self, session_id: str, search_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific search by ID.

        Returns:
            Search data dict or None if not found
        """
        search_key = self._key(session_id, f"search:{search_id}")
        search_json = self.client.get(search_key)
        if search_json:
            self._extend_ttl(session_id, search_key)
            return json.loads(search_json)
        return None

    def get_all_searches(self, session_id: str) -> List[Dict[str, Any]]:
        """Retrieve all searches for a session.

        Returns:
            List of search data dicts, ordered chronologically
        """
        searches_key = self._key(session_id, "searches")
        search_ids = self.client.lrange(searches_key, 0, -1)
        self._extend_ttl(session_id, searches_key)

        searches = []
        for search_id in search_ids:
            search_data = self.get_search(session_id, search_id)
            if search_data:
                searches.append(search_data)
        return searches

    def get_latest_search(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the most recent search for a session.

        Returns:
            Search data dict or None if no searches exist
        """
        searches_key = self._key(session_id, "searches")
        search_ids = self.client.lrange(searches_key, -1, -1)
        if search_ids:
            return self.get_search(session_id, search_ids[0])
        return None

    # ========== Current Search Context ==========

    def set_current_search_id(self, session_id: str, search_id: str):
        """Set the active search ID for the session."""
        key = self._key(session_id, "current_search_id")
        self.client.set(key, search_id, ex=self.session_ttl)

    def get_current_search_id(self, session_id: str) -> Optional[str]:
        """Get the active search ID for the session."""
        key = self._key(session_id, "current_search_id")
        search_id = self.client.get(key)
        if search_id:
            self._extend_ttl(session_id, key)
        return search_id

    def get_current_search(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the current active search data."""
        search_id = self.get_current_search_id(session_id)
        if search_id:
            return self.get_search(session_id, search_id)
        return None

    # ========== Session Management ==========

    def clear_session(self, session_id: str):
        """Clear all data for a session (messages, searches, current search)."""
        # Get all search IDs to delete individual search keys
        searches_key = self._key(session_id, "searches")
        search_ids = self.client.lrange(searches_key, 0, -1)

        # Delete all keys
        keys_to_delete = [
            self._key(session_id, "messages"),
            self._key(session_id, "searches"),
            self._key(session_id, "current_search_id"),
        ]
        for search_id in search_ids:
            keys_to_delete.append(self._key(session_id, f"search:{search_id}"))

        self.client.delete(*keys_to_delete)

    def session_exists(self, session_id: str) -> bool:
        """Check if a session has any stored data."""
        messages_key = self._key(session_id, "messages")
        return self.client.exists(messages_key) > 0

    def ping(self) -> bool:
        """Test Redis connection.

        Returns:
            True if connection is alive, False otherwise
        """
        try:
            return self.client.ping()
        except Exception:
            return False


# ========== Helper Functions ==========


def generate_search_id() -> str:
    """Generate a unique search ID based on timestamp."""
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")


# ========== Example Usage ==========

if __name__ == "__main__":
    # Example: Basic usage
    store = SessionStore()

    # Check connection
    if not store.ping():
        print("ERROR: Cannot connect to Redis")
        exit(1)

    print("✅ Connected to Redis")

    # Create a test session
    session_id = "test_session_123"

    # Store messages
    store.add_message(session_id, "user", "Show me 2br apartments under $3000")
    store.add_message(session_id, "assistant", "Here are 5 apartments matching your criteria...")

    # Save a search
    search_id = generate_search_id()
    store.save_search(
        session_id=session_id,
        search_id=search_id,
        query="Show me 2br apartments under $3000",
        filter_state={"hard": {"bedrooms": 2, "price": {"$lt": 3000}}, "amenities": [], "neighborhoods": [], "subway": {}},
        matches=[{"id": "apt_1", "price": 2800}, {"id": "apt_2", "price": 2900}],
    )
    store.set_current_search_id(session_id, search_id)

    # Retrieve
    messages = store.get_messages(session_id)
    print(f"\n📝 Messages: {len(messages)}")
    for msg in messages:
        print(f"  {msg['role']}: {msg['content'][:50]}...")

    current_search = store.get_current_search(session_id)
    print(f"\n🔍 Current search: {current_search['query']}")
    print(f"   Matches: {len(current_search['matches'])}")

    # Cleanup
    store.clear_session(session_id)
    print(f"\n🧹 Session cleared")
