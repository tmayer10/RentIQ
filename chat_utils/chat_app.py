import streamlit as st
from rag_pipeline import rag_search
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=4)  # adjust parallelism

st.set_page_config(page_title="RentIQ — Apartment Finder", layout="wide")
st.title("🏙️ RentIQ — NYC Apartment Finder")

# Initialize chat state
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
    st.session_state["messages"] = [
        {"role": "system", "content": "You are RentIQ, a helpful NYC apartment assistant."}
    ]
    st.session_state["last_matches"] = []
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
    with st.chat_message("user"):
        st.markdown(user_query)

    with st.spinner("Searching and analyzing..."):
        history_for_llm = [m for m in st.session_state["messages"] if m["role"] != "system"]
        prior_assistant_msgs = [m for m in history_for_llm if m["role"] == "assistant"]
        is_first_turn = len(prior_assistant_msgs) == 0

        # Submit background task with previous state
        future = executor.submit(
            run_rag_search_sync, 
            user_query, 
            top_k, 
            history_for_llm, 
            is_first_turn,
            st.session_state.get("previous_filters"),  # Pass previous filters
            st.session_state.get("last_matches")        # Pass previous matches
        )
        llm_output, matches, clarification, pinecone_filters = future.result()

    # Store and show results   
    st.session_state["last_matches"] = matches
    st.session_state["previous_filters"] = pinecone_filters  # Store for next turn
    st.session_state["messages"].append({"role": "assistant", "content": llm_output})

    with st.chat_message("assistant"):
        st.markdown(llm_output)

    if clarification:
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
