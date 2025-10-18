# app.py
import streamlit as st
from rag_pipeline import rag_search

st.set_page_config(page_title="RentIQ — Apartment Finder", layout="wide")
st.title("🏙️ RentIQ — NYC Apartment Finder")

# User Input
user_query = st.text_input("🔍 What kind of apartment are you looking for?")
top_k = st.slider("Number of top listings to consider", min_value=3, max_value=10, value=5)

if st.button("Search"):
    if user_query.strip():
        with st.spinner("Searching and analyzing..."):
            llm_output, matches = rag_search(user_query, top_k=top_k)

        # LLM Recommendation
        st.subheader("📋 Recommendations")
        st.markdown(llm_output)

        # Raw listings table (optional for transparency)
        st.subheader("📂 Retrieved Listings")
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
    else:
        st.warning("Please enter a search query!")
