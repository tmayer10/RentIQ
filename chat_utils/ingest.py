# ingest.py
import os
from dotenv import load_dotenv
from chatdb import fetch_listings
from utils import build_text, sanitize_metadata
from vectorstore import splade_encode, dense_model, get_index, INDEX_DIM

load_dotenv()

BATCH_SIZE = 500

def ingest_listings():
    rows = fetch_listings()
    print(f"[INFO] Loaded {len(rows)} listings from Postgres")

    index = get_index()
    batch = []

    for i, row in enumerate(rows, start=1):
        text = build_text(row)

        # Dense
        dense_vec = dense_model.encode(text).tolist()

        # Sparse
        sparse_vec = splade_encode(text)

        (
            listing_id,
            description,
            price,
            bedrooms,
            bathrooms,
            sqft,
            neighborhood,
            borough,
            zipcode,
            built_in,
            building_address,
            building_lat,
            building_lon,
            building_built_in,
            amenity_list,
            subway_info,
            subway_lines,
            subway_routes,
            subway_distances
        ) = row

        # --- Safety defaults ---
        amenity_list = amenity_list or "No amenities listed"
        subway_info = subway_info or "No nearby subway stations"
        borough = borough.lower() if borough else "Not available"
        neighborhood = neighborhood.lower() if neighborhood else "Not available"

        # --- Subway distances map ---
        subway_dist_map = {}
        if subway_lines and subway_routes and subway_distances:
            for line, route, dist in zip(subway_lines, subway_routes, subway_distances):
                if line and route and dist is not None:
                    key = f"{line.lower()}_{route.lower()}"
                    subway_dist_map[key] = float(dist)

        subway_dist_list = [f"{key}:{dist}" for key, dist in subway_dist_map.items()]
        subway_min_distance = min(subway_dist_map.values()) if subway_dist_map else None

        # --- Metadata ---
        metadata = sanitize_metadata({
            "listing_id": listing_id,
            "price": price,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "sqft": sqft,
            "borough": borough,
            "neighborhood": neighborhood,
            "zipcode": zipcode,
            "building_address": building_address,
            "amenities": [a.strip().lower() for a in amenity_list.split(",")]
                if amenity_list and "no amenities" not in amenity_list.lower()
                else [],
            "subway_info": subway_info,
            "subway_lines": [line.lower() for line in subway_lines if line],
            "subway_routes": [route.lower() for route in subway_routes if route],
            "subway_min_distance": subway_min_distance,
            # You can enable subway_distances later for numeric filtering
            "description": description
        })

        batch.append({
            "id": listing_id,
            "values": dense_vec,
            "sparse_values": sparse_vec,
            "metadata": metadata
        })

        if len(batch) >= BATCH_SIZE:
            index.upsert(batch)
            print(f"[INFO] Upserted batch of {len(batch)} listings")
            batch.clear()

    # Final flush
    if batch:
        index.upsert(batch)
        print(f"[INFO] Final batch upserted ({len(batch)} listings)")

    print("[✅] Hybrid Pinecone ingestion complete.")

if __name__ == "__main__":
    ingest_listings()
