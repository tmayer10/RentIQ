# db.py
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def running_in_docker() -> bool:
    try:
        with open('/proc/1/cgroup', 'rt') as f:
            content = f.read()
            return 'docker' in content or 'containerd' in content
    except FileNotFoundError:
        return False

def get_connection():
    if running_in_docker():
        resolved_host = "db"
    else:
        resolved_host = "localhost"

    return psycopg2.connect(
        dbname=os.getenv("DATABASE_NAME"),
        user=os.getenv("DATABASE_USER"),
        password=os.getenv("DATABASE_PASSWORD"),
        host=resolved_host,
        port=os.getenv("DATABASE_PORT", "5432")
    )

PG_QUERY = """
WITH subway_flat AS (
    SELECT
        ls.listing_id AS listing_pk,              -- FK to listings.id
        l.listing_id AS listing_id_str,           -- StreetEasy string id
        LOWER(s.line) AS line,
        LOWER(unnest(coalesce(s.routes, ARRAY[]::text[]))) AS route,
        ls.distance
    FROM listing_subway ls
    JOIN listings l
        ON l.id = ls.listing_id                   -- match FK to PK
    JOIN subway_stations s
        ON s.id = ls.subway_id                    -- match FK to PK
),
subway_grouped AS (
    SELECT
        listing_id_str,
        line,
        route,
        MIN(distance) AS min_distance
    FROM subway_flat
    GROUP BY listing_id_str, line, route
)
SELECT
    l.listing_id,       -- StreetEasy string id
    l.description,
    l.price,
    l.bedrooms,
    l.bathrooms,
    l.sqft,
    l.neighborhood,
    l.borough,
    l.zipcode,
    l.built_in,
    b.address AS building_address,
    b.latitude AS building_lat,
    b.longitude AS building_lon,
    b.built_in AS building_built_in,
    array_to_string(l.amenities, ', ') AS amenity_list,

    STRING_AGG(
        sg.line || ' (' || sg.route || ') Train (' || sg.min_distance || ' miles)',
        '; ' ORDER BY sg.min_distance ASC
    ) AS subway_info,

    ARRAY_AGG(DISTINCT sg.line) AS subway_lines,
    ARRAY_AGG(DISTINCT sg.route) AS subway_routes,
    ARRAY_AGG(sg.min_distance) AS subway_distances

FROM listings l
LEFT JOIN buildings b 
    ON b.id = l.building_id
LEFT JOIN subway_grouped sg 
    ON sg.listing_id_str = l.listing_id   -- StreetEasy string match
WHERE l.status = 'open'
GROUP BY
    l.listing_id, l.description, l.price, l.bedrooms,
    l.bathrooms, l.sqft, l.neighborhood, l.borough,
    l.zipcode, l.built_in, b.address, b.latitude,
    b.longitude, b.built_in, l.amenities;
"""

def fetch_listings():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(PG_QUERY)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows