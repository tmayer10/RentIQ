import streamlit as st
from rag_pipeline import rag_search
import asyncio
from concurrent.futures import ThreadPoolExecutor
from session_store import SessionStore, generate_search_id
import uuid
import re
from listings_data import get_listing_url, get_listing_images, get_listing_urls_batch, get_listing_images_batch
from scorer import score_listings

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


def extract_subway_data_from_matches(matches) -> dict:
    """Extract subway data from match objects.
    
    Returns a dict mapping listing_id to subway info dict.
    """
    subway_data = {}
    if not matches:
        return subway_data
    
    for m in matches:
        # Handle both dict format and object format
        if isinstance(m, dict):
            md = m.get("metadata", {})
        else:
            md = m.metadata
        
        listing_id = md.get("listing_id")
        if not listing_id:
            continue
        
        listing_id = str(listing_id)
        subway_info = {
            'route_distances': md.get('route_distances', {}),
            'subway_lines': md.get('subway_lines', []),
            'subway_routes': md.get('subway_routes', []),
            'subway_min_distance': md.get('subway_min_distance'),
            'subway_info': md.get('subway_info')
        }
        
        # Only add if there's some subway data
        if (subway_info['route_distances'] or 
            subway_info['subway_lines'] or 
            subway_info['subway_routes'] or 
            subway_info['subway_info']):
            subway_data[listing_id] = subway_info
    
    return subway_data


def extract_compromises_from_matches(matches, scored_matches=None) -> dict:
    """Extract compromises from match objects.
    
    If scored_matches is provided (list of (match, score, compromises) tuples),
    use that. Otherwise, try to extract from match metadata.
    
    Returns a dict mapping listing_id to list of compromise strings.
    """
    compromises_data = {}
    
    # If we have scored matches with compromises, use those
    if scored_matches:
        for match, score, comp in scored_matches:
            if isinstance(match, dict):
                md = match.get("metadata", {})
            else:
                md = match.metadata
            listing_id = md.get("listing_id")
            if listing_id and comp:
                compromises_data[str(listing_id)] = comp
        return compromises_data
    
    # Otherwise, try to extract from match metadata (if stored there)
    if not matches:
        return compromises_data
    
    for m in matches:
        if isinstance(m, dict):
            md = m.get("metadata", {})
        else:
            md = m.metadata
        
        listing_id = md.get("listing_id")
        if listing_id:
            # Compromises might be stored in metadata
            comp = md.get("compromises", [])
            if comp:
                compromises_data[str(listing_id)] = comp
    
    return compromises_data


def format_title_case(text: str) -> str:
    """Convert text to proper title case, handling special cases like hyphens."""
    if not text:
        return text
    # Split by hyphens, title case each part, then rejoin
    parts = text.split('-')
    return '-'.join([part.title() for part in parts])


def format_amenity_title_case(amenity: str) -> str:
    """Convert amenity to proper title case, handling underscores."""
    if not amenity:
        return amenity
    # Replace underscores with spaces, title case each word
    parts = amenity.split('_')
    return ' '.join([part.title() for part in parts])


def display_with_images(text: str, structured_data, listing_ids: list, images_data: dict, 
                       subway_data: dict = None, compromises_data: dict = None):
    """
    Display LLM output with expandable image sections for each listing.
    Uses structured data if available, otherwise falls back to text parsing.
    Handles both Pydantic models and dict-based structured data (from stored messages).
    
    Args:
        text: LLM output text
        structured_data: Structured listing data (Pydantic model or dict)
        listing_ids: List of listing IDs
        images_data: Dict mapping listing_id to list of image URLs
        subway_data: Dict mapping listing_id to subway info dict with keys: route_distances, subway_lines, subway_routes
        compromises_data: Dict mapping listing_id to list of compromise strings
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
            
            # Format neighborhood in title case
            neighborhood_formatted = format_title_case(neighborhood) if neighborhood else ""
            st.markdown(f"**Neighborhood:** {neighborhood_formatted}", unsafe_allow_html=False)
            
            # Format amenities in title case
            amenities_formatted = [format_amenity_title_case(amenity) for amenity in amenities] if amenities else []
            st.markdown(f"**Amenities:** {', '.join(amenities_formatted)}", unsafe_allow_html=False)
            
            # Display subway information if available
            if subway_data and listing_id in subway_data:
                subway_info = subway_data[listing_id]
                route_distances = subway_info.get('route_distances', {})
                subway_lines = subway_info.get('subway_lines', [])
                subway_routes = subway_info.get('subway_routes', [])
                
                subway_display_parts = []
                
                # Show routes with distances if available
                if route_distances:
                    # Sort routes by distance and show top 3 closest
                    sorted_routes = sorted(route_distances.items(), key=lambda x: x[1])[:3]
                    route_parts = [f"{route.upper()} train ({dist:.2f} mi)" for route, dist in sorted_routes]
                    subway_display_parts.extend(route_parts)
                
                # Also show subway lines if available (without distances, as we don't have line-specific distances)
                if subway_lines and not route_distances:
                    # Format lines in title case
                    lines_formatted = [format_title_case(line) for line in subway_lines[:3]]
                    subway_display_parts.append(f"Lines: {', '.join(lines_formatted)}")
                elif subway_lines and len(subway_display_parts) < 3:
                    # Add lines info if we have space
                    lines_formatted = [format_title_case(line) for line in subway_lines[:2]]
                    subway_display_parts.append(f"Lines: {', '.join(lines_formatted)}")
                
                # Fallback: show routes without distances
                if not subway_display_parts and subway_routes:
                    if subway_info.get('subway_min_distance') is not None:
                        min_dist = subway_info.get('subway_min_distance')
                        routes_str = ', '.join([r.upper() for r in subway_routes[:3]])
                        subway_display_parts.append(f"{routes_str} ({min_dist:.2f} mi)")
                    else:
                        routes_str = ', '.join([r.upper() for r in subway_routes[:3]])
                        subway_display_parts.append(routes_str)
                
                # Final fallback: use subway_info string
                if not subway_display_parts and subway_info.get('subway_info'):
                    subway_display_parts.append(subway_info.get('subway_info'))
                
                if subway_display_parts:
                    st.markdown(f"**Subway:** {' | '.join(subway_display_parts)}", unsafe_allow_html=False)
            
            # Display compromises if available
            if compromises_data and listing_id in compromises_data:
                compromises = compromises_data[listing_id]
                if compromises:
                    compromises_str = ', '.join(compromises)
                    st.markdown(f"**Compromises:** {compromises_str}", unsafe_allow_html=False)
            
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
                    msg["subway_data"] = metadata.get("subway_data", {})
                    msg["compromises_data"] = metadata.get("compromises_data", {})
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
filter_provider = st.sidebar.selectbox("Filter extraction provider", ["google", "openai"], index=0, help="Choose which LLM provider to use for filter extraction")

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
            subway_data = msg.get("subway_data", {})
            compromises_data = msg.get("compromises_data", {})
            images_data = {}
            if listing_ids:
                images_data = get_listing_images_batch(listing_ids, max_images=5)
            display_with_images(msg["content"], structured_data, listing_ids, images_data,
                              subway_data=subway_data, compromises_data=compromises_data)
        elif msg.get("role") == "assistant":
            # Assistant message without structured_data - try to extract listing IDs and display properly
            # Extract listing IDs from content for potential image display
            listing_ids = extract_listing_ids_from_text(msg["content"])
            subway_data = msg.get("subway_data", {})
            compromises_data = msg.get("compromises_data", {})
            if listing_ids:
                images_data = get_listing_images_batch(listing_ids, max_images=5)
                display_with_images(msg["content"], None, listing_ids, images_data,
                                  subway_data=subway_data, compromises_data=compromises_data)
            else:
                # Regular message - render markdown properly (tables, formatting, etc.)
                st.markdown(msg["content"], unsafe_allow_html=False)
        else:
            # Regular message - use unsafe_allow_html=False to prevent markdown interpretation issues
            st.markdown(msg["content"], unsafe_allow_html=False)

# Chat input
user_query = st.chat_input("Ask about apartments, neighborhoods, prices, or follow up...")

executor = ThreadPoolExecutor(max_workers=8)  # adjust parallelism

def run_rag_search_sync(user_query, top_k, chat_history, is_first_turn, previous_filters, previous_matches, filter_provider="google"):
    """Run the async rag_search inside a background thread and return results."""
    return asyncio.run(
        rag_search(user_query, 
                   top_k=top_k, 
                   chat_history=chat_history, 
                   is_first_turn=is_first_turn,
                   previous_filters=previous_filters,
                   previous_matches=previous_matches,
                   filter_provider=filter_provider)
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
        previous_matches,  # Pass previous matches
        filter_provider    # Pass filter provider selection
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
    
    # Extract subway data from matches
    subway_data = extract_subway_data_from_matches(matches)
    
    # Calculate compromises using scorer
    compromises_data = {}
    if matches and filter_state:
        # filter_state structure: {"hard": {...}, "amenities": [...], "neighborhoods": [...], "subway": {...}}
        hard_filters = filter_state.get("hard", {})
        criteria = {
            "price": hard_filters.get("price") or {},
            "bedrooms": hard_filters.get("bedrooms") or {},
            "bathrooms": hard_filters.get("bathrooms") or {},
            "amenities": filter_state.get("amenities") or [],
            "neighborhoods": filter_state.get("neighborhoods") or [],
            "subway": filter_state.get("subway") or {},
        }
        scored_matches = score_listings(matches, criteria)
        compromises_data = extract_compromises_from_matches(matches, scored_matches)
    
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
        "listing_ids": all_listing_ids,
        "subway_data": subway_data,
        "compromises_data": compromises_data
    }
    
    if use_redis and store:
        # Save to Redis
        search_id = generate_search_id()
        # Convert matches to dict format, handling both dict and object formats
        matches_dict = []
        if matches:
            for m in matches:
                if isinstance(m, dict):
                    # Already a dict, use as-is
                    matches_dict.append(m)
                else:
                    # Object with metadata and score attributes
                    matches_dict.append({"metadata": m.metadata, "score": m.score})
        store.save_search(
            session_id=session_id,
            search_id=search_id,
            query=user_query,
            filter_state=filter_state,
            matches=matches_dict,
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
            "listing_ids": all_listing_ids,
            "subway_data": subway_data,
            "compromises_data": compromises_data
        }
        # Reload messages from Redis and merge metadata back
        messages = store.get_messages(session_id)
        for i, msg in enumerate(messages):
            if msg.get("role") == "assistant" and i in st.session_state["message_metadata"]:
                metadata = st.session_state["message_metadata"][i]
                msg["structured_data"] = metadata.get("structured_data")
                msg["listing_ids"] = metadata.get("listing_ids", [])
                msg["subway_data"] = metadata.get("subway_data", {})
                msg["compromises_data"] = metadata.get("compromises_data", {})
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
        display_with_images(llm_output_with_links, structured_data, all_listing_ids, images_data, 
                          subway_data=subway_data, compromises_data=compromises_data)

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
