import streamlit as st
from rag_pipeline import rag_search
import asyncio
from concurrent.futures import ThreadPoolExecutor
from session_store import SessionStore, generate_search_id
import uuid
import re
from listings_data import get_listing_url, get_listing_images, get_listing_urls_batch, get_listing_images_batch

executor = ThreadPoolExecutor(max_workers=4)  # adjust parallelism

st.set_page_config(page_title="RentIQ — Apartment Finder", layout="wide")


def add_hyperlinks_to_text(text: str, listing_ids: list) -> str:
    """
    Replace listing IDs in text with hyperlinks.
    Looks for patterns like "ID: 123456" or just "123456" when it's a listing ID.
    """
    if not listing_ids:
        return text
    
    # Get URLs for all listing IDs
    urls = get_listing_urls_batch(listing_ids)
    
    # Pattern to match listing IDs (numbers, typically 6-7 digits)
    # Match patterns like "ID: 123456", "listing 123456", or standalone "123456"
    for listing_id in listing_ids:
        if listing_id not in urls:
            continue
        
        url = urls[listing_id]
        # Create hyperlink markdown
        hyperlink = f"[{listing_id}]({url})"
        
        # Replace various patterns:
        # 1. "ID: 123456" -> "ID: [123456](url)"
        text = re.sub(
            rf'\bID:\s*{re.escape(str(listing_id))}\b',
            f'ID: {hyperlink}',
            text,
            flags=re.IGNORECASE
        )
        # 2. "listing 123456" -> "listing [123456](url)"
        text = re.sub(
            rf'\blisting\s+{re.escape(str(listing_id))}\b',
            f'listing {hyperlink}',
            text,
            flags=re.IGNORECASE
        )
        # 3. Standalone ID (but be careful not to replace IDs that are already hyperlinked)
        # Only replace if it's not already part of a markdown link
        text = re.sub(
            rf'(?<!\[)\b{re.escape(str(listing_id))}\b(?!\])',
            hyperlink,
            text
        )
    
    return text


def extract_listing_ids_from_text(text: str) -> list:
    """Extract potential listing IDs from LLM output text."""
    # Look for patterns like "ID: 123456" or numbers that might be listing IDs
    # Listing IDs are typically 6-7 digit numbers
    patterns = [
        r'\bID:\s*(\d{6,8})\b',  # "ID: 123456"
        r'\blisting\s+(\d{6,8})\b',  # "listing 123456"
        r'\*\*ID:\s*(\d{6,8})\*\*',  # "**ID: 123456**"
    ]
    
    found_ids = set()
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        found_ids.update(matches)
    
    return list(found_ids)


def extract_listing_ids_from_matches(matches) -> list:
    """Extract listing IDs from match objects.
    
    Handles both dict format (from Redis) and object format (from Pinecone).
    """
    if not matches:
        return []
    result = []
    for m in matches:
        # Handle both dict format and object format
        if isinstance(m, dict):
            md = m.get("metadata", {})
        else:
            md = m.metadata
        listing_id = md.get("listing_id")
        if listing_id:
            result.append(str(listing_id))
    return result


def display_with_images(text: str, structured_data, listing_ids: list, images_data: dict):
    """
    Display LLM output with expandable image sections for each listing.
    Uses structured data if available, otherwise falls back to text parsing.
    Handles both Pydantic models and dict-based structured data (from stored messages).
    """
    # Check if structured_data is a dict (from stored messages) or Pydantic model
    listings = None
    final_recommendation = None
    
    if structured_data:
        if isinstance(structured_data, dict) and structured_data.get("type") == "StructuredListingResponse":
            # Dict-based structured data from stored messages
            listings = structured_data.get("listings", [])
            final_recommendation = structured_data.get("final_recommendation")
        elif hasattr(structured_data, 'listings'):
            # Pydantic model
            listings = structured_data.listings
            final_recommendation = structured_data.final_recommendation if hasattr(structured_data, 'final_recommendation') else None
    
    # If we have structured listings data, use it directly
    if listings:
        for listing in listings:
            # Handle both dict and Pydantic model access
            if isinstance(listing, dict):
                listing_id = listing.get("listing_id", "")
                price = listing.get("price", 0)
                bedrooms = listing.get("bedrooms", 0)
                bathrooms = listing.get("bathrooms", 0)
                neighborhood = listing.get("neighborhood", "")
                amenities = listing.get("amenities", [])
                summary = listing.get("summary", "")
            else:
                listing_id = listing.listing_id
                price = listing.price
                bedrooms = listing.bedrooms
                bathrooms = listing.bathrooms
                neighborhood = listing.neighborhood
                amenities = listing.amenities
                summary = listing.summary
            
            listing_url = get_listing_url(listing_id)
            
            # Display listing info with hyperlinked ID
            if listing_url:
                st.markdown(f"**ID:** [{listing_id}]({listing_url})", unsafe_allow_html=False)
            else:
                st.markdown(f"**ID:** {listing_id}", unsafe_allow_html=False)
            
            st.markdown(f"**Price:** ${price}", unsafe_allow_html=False)
            st.markdown(f"**Bedrooms:** {bedrooms}, **Bathrooms:** {bathrooms}", unsafe_allow_html=False)
            st.markdown(f"**Neighborhood:** {neighborhood}", unsafe_allow_html=False)
            st.markdown(f"**Amenities:** {', '.join(amenities)}", unsafe_allow_html=False)
            
            # Add expander with images right after amenities
            if listing_id in images_data and images_data[listing_id]:
                with st.expander(f"📸 View Images for Listing {listing_id}", expanded=False):
                    if listing_url:
                        st.markdown(f"[View Full Listing →]({listing_url})", unsafe_allow_html=False)
                    
                    # Display all available images
                    for img_url in images_data[listing_id]:
                        try:
                            st.image(img_url, use_container_width=True)
                        except Exception as e:
                            st.error(f"Could not load image: {str(e)[:50]}")
            
            st.markdown(f"**Summary:** {summary}", unsafe_allow_html=False)
            st.markdown("---")  # Separator between listings
        
        # Display final recommendation if present
        if final_recommendation:
            st.markdown(final_recommendation, unsafe_allow_html=False)
    else:
        # Fallback to text parsing (for backward compatibility or when structured output fails)
        if not listing_ids or not images_data:
            # No images to show, just display the text
            st.markdown(text, unsafe_allow_html=False)
        else:
            _parse_and_display_text_with_images(text, listing_ids, images_data)


def _parse_and_display_text_with_images(text: str, listing_ids: list, images_data: dict):
    """
    Fallback: Parse LLM output text and display it with expandable image sections.
    Only used when structured output is not available.
    """
    # Track which listing we're currently in as we parse through the text
    lines = text.split('\n')
    current_listing_id = None
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Check if this line contains a listing ID (at the start of a listing block)
        listing_id_match = re.search(r'(?:^|\*\*|^[\d]+\.\s*)(?:ID:\s*|Listing\s+ID:\s*)(\d{6,8})', line, re.IGNORECASE)
        if listing_id_match:
            found_id = listing_id_match.group(1)
            if found_id in listing_ids:
                current_listing_id = found_id
        
        # Check if this is the Amenities line for the current listing
        if current_listing_id and re.search(r'Amenities:', line, re.IGNORECASE):
            st.markdown(line, unsafe_allow_html=False)
            # Add expander right after amenities if we have images
            if current_listing_id in images_data and images_data[current_listing_id]:
                with st.expander(f"📸 View Images for Listing {current_listing_id}", expanded=False):
                    listing_url = get_listing_url(current_listing_id)
                    if listing_url:
                        st.markdown(f"[View Full Listing →]({listing_url})", unsafe_allow_html=False)
                    
                    for img_url in images_data[current_listing_id]:
                        try:
                            st.image(img_url, use_container_width=True)
                        except Exception as e:
                            st.error(f"Could not load image: {str(e)[:50]}")
            i += 1
            continue
        
        # Check if we've moved to a new listing or out of listing context
        if current_listing_id and line.strip() == '':
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if not re.search(r'(Price|Bedrooms|Bathrooms|Neighborhood|Amenities|Summary|Description):', next_line, re.IGNORECASE):
                    if not re.search(r'(?:^|\*\*|^[\d]+\.\s*)(?:ID:\s*|Listing\s+ID:\s*)(\d{6,8})', next_line, re.IGNORECASE):
                        current_listing_id = None
        
        st.markdown(line, unsafe_allow_html=False)
        i += 1

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
        # Merge metadata back into messages if available
        if "message_metadata" in st.session_state:
            for i, msg in enumerate(messages):
                if msg.get("role") == "assistant" and i in st.session_state["message_metadata"]:
                    metadata = st.session_state["message_metadata"][i]
                    msg["structured_data"] = metadata.get("structured_data")
                    msg["listing_ids"] = metadata.get("listing_ids", [])
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
        # Check if this message has structured data for proper re-rendering
        if msg.get("role") == "assistant" and "structured_data" in msg:
            # Re-render with images if structured data is available
            structured_data = msg.get("structured_data")
            listing_ids = msg.get("listing_ids", [])
            images_data = {}
            if listing_ids:
                images_data = get_listing_images_batch(listing_ids, max_images=5)
            display_with_images(msg["content"], structured_data, listing_ids, images_data)
        elif msg.get("role") == "assistant":
            # Assistant message without structured_data - try to extract listing IDs and display properly
            # Extract listing IDs from content for potential image display
            listing_ids = extract_listing_ids_from_text(msg["content"])
            if listing_ids:
                images_data = get_listing_images_batch(listing_ids, max_images=5)
                display_with_images(msg["content"], None, listing_ids, images_data)
            else:
                # Regular message - render markdown properly (tables, formatting, etc.)
                st.markdown(msg["content"], unsafe_allow_html=False)
        else:
            # Regular message - use unsafe_allow_html=False to prevent markdown interpretation issues
            st.markdown(msg["content"], unsafe_allow_html=False)

# Chat input
user_query = st.chat_input("Ask about apartments, neighborhoods, prices, or follow up...")

executor = ThreadPoolExecutor(max_workers=8)  # adjust parallelism

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
        st.markdown(user_query, unsafe_allow_html=False)

    # Use a simple text placeholder instead of spinner to avoid overlay
    status_placeholder = st.empty()
    status_placeholder.info("🔍 Searching and analyzing...")
    
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
    llm_output, matches, clarification, filter_state, structured_data = future.result()

    # Clear status placeholder after search completes
    status_placeholder.empty()

    # Extract listing IDs from matches and structured data (preferred) or LLM output
    match_listing_ids = extract_listing_ids_from_matches(matches)
    
    # Use structured data if available, otherwise fall back to text parsing
    if structured_data:
        if isinstance(structured_data, dict) and "referenced_listing_ids" in structured_data:
            # Conversational response
            structured_listing_ids = structured_data["referenced_listing_ids"]
        else:
            # Structured listing response
            structured_listing_ids = [listing.listing_id for listing in structured_data.listings]
    else:
        structured_listing_ids = []
    
    # Fallback to text parsing if no structured data
    if not structured_listing_ids:
        text_listing_ids = extract_listing_ids_from_text(llm_output)
        structured_listing_ids = text_listing_ids
    
    # Combine and deduplicate
    all_listing_ids = list(set(match_listing_ids + structured_listing_ids))
    
    # Add hyperlinks to LLM output
    llm_output_with_links = add_hyperlinks_to_text(llm_output, all_listing_ids)
    if clarification:
        clarification_with_links = add_hyperlinks_to_text(clarification, all_listing_ids)
    else:
        clarification_with_links = None

    # Store and show results
    # Prepare structured data for storage (convert Pydantic models to dicts)
    structured_data_dict = None
    if structured_data:
        if hasattr(structured_data, 'listings'):
            # StructuredListingResponse - convert Pydantic models to dicts
            # Handle both Pydantic v1 (.dict()) and v2 (.model_dump())
            def to_dict(obj):
                if hasattr(obj, 'model_dump'):
                    return obj.model_dump()  # Pydantic v2
                elif hasattr(obj, 'dict'):
                    return obj.dict()  # Pydantic v1
                else:
                    return obj  # Already a dict
            
            structured_data_dict = {
                "type": "StructuredListingResponse",
                "listings": [to_dict(listing) for listing in structured_data.listings],
                "final_recommendation": structured_data.final_recommendation
            }
        elif isinstance(structured_data, dict) and "referenced_listing_ids" in structured_data:
            # ConversationalResponse (already a dict)
            structured_data_dict = structured_data
    
    # Store message with metadata for proper re-rendering
    assistant_message = {
        "role": "assistant",
        "content": llm_output_with_links,
        "structured_data": structured_data_dict,
        "listing_ids": all_listing_ids
    }
    
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
        # Store message with metadata - need to extend add_message or store separately
        # For now, store as JSON string in content and parse later, or extend SessionStore
        # We'll store it in session state for now and extend Redis storage if needed
        store.add_message(session_id, "assistant", llm_output_with_links)
        # Also store structured data separately in session state
        if "message_metadata" not in st.session_state:
            st.session_state["message_metadata"] = {}
        msg_index = len(store.get_messages(session_id)) - 1
        st.session_state["message_metadata"][msg_index] = {
            "structured_data": structured_data_dict,
            "listing_ids": all_listing_ids
        }
        # Reload messages from Redis and merge metadata back
        messages = store.get_messages(session_id)
        for i, msg in enumerate(messages):
            if msg.get("role") == "assistant" and i in st.session_state["message_metadata"]:
                metadata = st.session_state["message_metadata"][i]
                msg["structured_data"] = metadata.get("structured_data")
                msg["listing_ids"] = metadata.get("listing_ids", [])
        st.session_state["messages"] = messages
    else:
        # Fall back to in-memory
        st.session_state["last_matches"] = matches
        st.session_state["previous_filters"] = filter_state  # Store complete filter state for next turn
        st.session_state["messages"].append(assistant_message)

    with st.chat_message("assistant"):
        # Get images data for listings
        images_data = {}
        if matches and all_listing_ids:
            images_data = get_listing_images_batch(all_listing_ids, max_images=5)
        
        # Display LLM output with embedded image expanders using structured data
        display_with_images(llm_output_with_links, structured_data, all_listing_ids, images_data)

    if clarification_with_links:
        clarification_message = {
            "role": "assistant",
            "content": clarification_with_links
        }
        if use_redis and store:
            store.add_message(session_id, "assistant", clarification_with_links)
            st.session_state["messages"] = store.get_messages(session_id)
        else:
            st.session_state["messages"].append(clarification_message)
        with st.chat_message("assistant"):
            st.markdown(clarification_with_links, unsafe_allow_html=False)
