import streamlit as st
from rag_pipeline import rag_search

st.set_page_config(page_title="RentIQ — Apartment Finder", layout="wide")
st.title("🏙️ RentIQ — NYC Apartment Finder")

# Initialize chat state
if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {"role": "system", "content": "You are RentIQ, a helpful NYC apartment assistant."}
    ]

if "last_matches" not in st.session_state:
    st.session_state["last_matches"] = []

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

if user_query:
    # Echo user message
    st.session_state["messages"].append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)

    with st.spinner("Searching and analyzing..."):
        # Provide history excluding the system prolog which is already included in pipeline
        history_for_llm = [m for m in st.session_state["messages"] if m["role"] != "system"]
        prior_assistant_msgs = [m for m in history_for_llm if m["role"] == "assistant"]
        is_first_turn = len(prior_assistant_msgs) == 0
        llm_output, matches, clarification = rag_search(
            user_query,
            top_k=top_k,
            chat_history=history_for_llm,
            is_first_turn=is_first_turn,
        )

    st.session_state["last_matches"] = matches
    st.session_state["messages"].append({"role": "assistant", "content": llm_output})

    with st.chat_message("assistant"):
        st.markdown(llm_output)

    # Optional clarification follow-up when filters were sparse/empty
    if clarification:
        st.session_state["messages"].append({"role": "assistant", "content": clarification})
        with st.chat_message("assistant"):
            st.markdown(clarification)

    # Optional: collapsible raw listings from the latest turn
    with st.expander("Retrieved Listings (this turn)"):
        listings_data = [
            {
                "Rank": i+1,
                "Listing ID": m.metadata.get("listing_id"),
                "Price": m.metadata.get("price"),
                "Beds": m.metadata.get("bedrooms"),
                "Baths": m.metadata.get("bathrooms"),
                "Neighborhood": m.metadata.get("neighborhood"),
                "Borough": m.metadata.get("borough"),
                "Amenities": ", ".join(m.metadata.get("amenities", [])),
            }
            for i, m in enumerate(matches)
        ]
        st.table(listings_data)
