import streamlit as st
from rag_pipeline import rag_search
import asyncio
from concurrent.futures import ThreadPoolExecutor
from session_store import SessionStore, generate_search_id
import uuid

executor = ThreadPoolExecutor(max_workers=4)  # adjust parallelism

st.set_page_config(page_title="RentIQ — Apartment Finder", layout="wide")
st.title("🏙️ RentIQ — NYC Apartment Finder")

# Initialize Redis session store (with fallback to in-memory)
if "use_redis" not in st.session_state:
    try:
        store = SessionStore()
        if store.ping():
            st.session_state["use_redis"] = True
            st.session_state["store"] = store
            st.sidebar.success("✅ Redis connected")
        else:
            st.session_state["use_redis"] = False
            st.sidebar.warning("⚠️ Redis unavailable - using in-memory storage")
    except Exception as e:
        st.session_state["use_redis"] = False
        st.sidebar.warning(f"⚠️ Redis error: {str(e)[:50]} - using in-memory storage")

# Generate or retrieve session ID
if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())

session_id = st.session_state["session_id"]
use_redis = st.session_state.get("use_redis", False)
store = st.session_state.get("store") if use_redis else None

# Initialize chat state (in-memory fallback or Redis)
if use_redis and store:
    # Use Redis for session storage
    if "messages_loaded" not in st.session_state:
        # Load messages from Redis on first run
        messages = store.get_messages(session_id)
        if not messages:
            # Initialize with system message
            store.add_message(session_id, "system", "You are RentIQ, a helpful NYC apartment assistant.")
            messages = store.get_messages(session_id)
        st.session_state["messages"] = messages
        st.session_state["messages_loaded"] = True
else:
    # Fall back to in-memory session state
    if "messages" not in st.session_state:
        st.session_state["messages"] = [
            {"role": "system", "content": "You are RentIQ, a helpful NYC apartment assistant."}
        ]

    if "last_matches" not in st.session_state:
        st.session_state["last_matches"] = []

    if "previous_filters" not in st.session_state:
        st.session_state["previous_filters"] = None

# Sidebar controls
top_k = st.sidebar.slider("Number of top listings to consider", min_value=3, max_value=10, value=5)

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Start New Search", help="Clear conversation history and start fresh"):
    if use_redis and store:
        store.clear_session(session_id)
        store.add_message(session_id, "system", "You are RentIQ, a helpful NYC apartment assistant.")
        st.session_state["messages"] = store.get_messages(session_id)
    else:
        st.session_state["messages"] = [
            {"role": "system", "content": "You are RentIQ, a helpful NYC apartment assistant."}
        ]
        st.session_state["last_matches"] = []
        st.session_state["previous_filters"] = None
    st.rerun()

# Display conversation
for msg in st.session_state["messages"]:
    if msg["role"] == "system":
        continue
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Chat input
user_query = st.chat_input("Ask about apartments, neighborhoods, prices, or follow up...")

executor = ThreadPoolExecutor(max_workers=4)  # adjust parallelism

def run_rag_search_sync(user_query, top_k, chat_history, is_first_turn, previous_filters, previous_matches):
    """Run the async rag_search inside a background thread and return results."""
    return asyncio.run(
        rag_search(user_query, 
                   top_k=top_k, 
                   chat_history=chat_history, 
                   is_first_turn=is_first_turn,
                   previous_filters=previous_filters,
                   previous_matches=previous_matches)
    )

if user_query:
    # Echo user message
    st.session_state["messages"].append({"role": "user", "content": user_query})
    if use_redis and store:
        store.add_message(session_id, "user", user_query)

    with st.chat_message("user"):
        st.markdown(user_query)

    with st.spinner("Searching and analyzing..."):
        history_for_llm = [m for m in st.session_state["messages"] if m["role"] != "system"]
        prior_assistant_msgs = [m for m in history_for_llm if m["role"] == "assistant"]
        is_first_turn = len(prior_assistant_msgs) == 0

        # Get previous state (from Redis or in-memory)
        if use_redis and store:
            current_search = store.get_current_search(session_id)
            previous_filters = current_search["filter_state"] if current_search else None
            previous_matches = current_search["matches"] if current_search else None
        else:
            previous_filters = st.session_state.get("previous_filters")
            previous_matches = st.session_state.get("last_matches")

        # Submit background task with previous state
        future = executor.submit(
            run_rag_search_sync,
            user_query,
            top_k,
            history_for_llm,
            is_first_turn,
            previous_filters,  # Pass previous filters (complete state)
            previous_matches    # Pass previous matches
        )
        llm_output, matches, clarification, filter_state = future.result()

    # Store and show results
    if use_redis and store:
        # Save to Redis
        search_id = generate_search_id()
        store.save_search(
            session_id=session_id,
            search_id=search_id,
            query=user_query,
            filter_state=filter_state,
            matches=[{"metadata": m.metadata, "score": m.score} for m in matches] if matches else [],
        )
        store.set_current_search_id(session_id, search_id)
        store.add_message(session_id, "assistant", llm_output)
        st.session_state["messages"] = store.get_messages(session_id)
    else:
        # Fall back to in-memory
        st.session_state["last_matches"] = matches
        st.session_state["previous_filters"] = filter_state  # Store complete filter state for next turn
        st.session_state["messages"].append({"role": "assistant", "content": llm_output})

    with st.chat_message("assistant"):
        st.markdown(llm_output)

    if clarification:
        if use_redis and store:
            store.add_message(session_id, "assistant", clarification)
            st.session_state["messages"] = store.get_messages(session_id)
        else:
            st.session_state["messages"].append({"role": "assistant", "content": clarification})
        with st.chat_message("assistant"):
            st.markdown(clarification)

    with st.expander("Retrieved Listings (this turn)"):
        listings_data = [
            {
                "Rank": i+1,
                "Listing ID": m['metadata'].get("listing_id"),
                "Price": m['metadata'].get("price"),
                "Beds": m['metadata'].get("bedrooms"),
                "Baths": m['metadata'].get("bathrooms"),
                "Neighborhood": m['metadata'].get("neighborhood"),
                "Borough": m['metadata'].get("borough"),
                "Amenities": ", ".join(m['metadata'].get("amenities", [])),
            }
            for i, m in enumerate(matches)
        ]
        st.table(listings_data)
