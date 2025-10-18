# utils.py
from decimal import Decimal

def build_text(row):
    (
        listing_id, description, price, bedrooms, bathrooms, sqft,
        neighborhood, borough, zipcode, built_in, building_address,
        building_lat, building_lon, building_built_in, amenity_list,
        subway_info, subway_lines, subway_routes, subway_distances
    ) = row

    amenity_list = amenity_list or "No amenities listed"
    subway_info = subway_info or "No nearby subway stations"

    return f"""Listing ID: {listing_id}
{description}
Located at {building_address} in {neighborhood}, {borough} ({zipcode}).
Price: ${price}, {bedrooms} bedrooms, {bathrooms} bathrooms, {sqft} sqft.
Amenities: {amenity_list}.
Nearby subway stations: {subway_info}.
Built in {building_built_in}.
"""

def sanitize_metadata(metadata: dict) -> dict:
    clean = {}
    for k, v in metadata.items():
        if v is None:
            continue
        elif isinstance(v, (int, float, bool, str, list, dict)):
            clean[k] = v
        elif isinstance(v, Decimal):
            clean[k] = float(v)
        else:
            clean[k] = str(v)
    return clean

def deduplicate_matches(matches):
    seen_ids = set()
    unique_matches = []
    for match in matches:
        listing_id = match.metadata.get("listing_id")
        if listing_id not in seen_ids:
            seen_ids.add(listing_id)
            unique_matches.append(match)
    return unique_matches
