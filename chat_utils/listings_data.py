# listing_data.py
"""
Utility module to load listing URLs and images from JSON files.
Provides lookup functions for hyperlinking and displaying images.
"""

import json
import os
from typing import Dict, List, Optional

# Paths to JSON files (relative to project root)
_LISTINGS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "EDA", "Datasets", "StreetEasy", "manhattan_listings.json"
)
_DETAILS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "EDA", "Datasets", "StreetEasy", "manhattan_details.json"
)

# Cache for loaded data
_listing_urls: Optional[Dict[str, str]] = None
_listing_images: Optional[Dict[str, List[str]]] = None


def _load_listing_urls() -> Dict[str, str]:
    """Load listing URLs from manhattan_listings.json."""
    global _listing_urls
    if _listing_urls is not None:
        return _listing_urls
    
    _listing_urls = {}
    try:
        with open(_LISTINGS_FILE, 'r', encoding='utf-8') as f:
            listings = json.load(f)
            for listing in listings:
                listing_id = str(listing.get('id', ''))
                url = listing.get('url', '')
                if listing_id and url:
                    _listing_urls[listing_id] = url
        print(f"[INFO] Loaded {len(_listing_urls)} listing URLs")
    except FileNotFoundError:
        print(f"[WARN] Could not find {_LISTINGS_FILE}")
    except Exception as e:
        print(f"[WARN] Error loading listing URLs: {e}")
    
    return _listing_urls


def _load_listing_images() -> Dict[str, List[str]]:
    """Load listing images from manhattan_details.json."""
    global _listing_images
    if _listing_images is not None:
        return _listing_images
    
    _listing_images = {}
    try:
        with open(_DETAILS_FILE, 'r', encoding='utf-8') as f:
            details = json.load(f)
            for detail in details:
                listing_id = str(detail.get('id', ''))
                images = detail.get('images', [])
                if listing_id and images:
                    # Filter out empty strings and ensure we have valid URLs
                    valid_images = [img for img in images if img and isinstance(img, str)]
                    if valid_images:
                        _listing_images[listing_id] = valid_images
        print(f"[INFO] Loaded images for {len(_listing_images)} listings")
    except FileNotFoundError:
        print(f"[WARN] Could not find {_DETAILS_FILE}")
    except Exception as e:
        print(f"[WARN] Error loading listing images: {e}")
    
    return _listing_images


def get_listing_url(listing_id: str) -> Optional[str]:
    """Get the URL for a listing by ID."""
    urls = _load_listing_urls()
    return urls.get(str(listing_id))


def get_listing_images(listing_id: str, max_images: int = 3) -> List[str]:
    """Get images for a listing by ID. Returns up to max_images URLs."""
    images = _load_listing_images()
    listing_images = images.get(str(listing_id), [])
    return listing_images[:max_images]


def get_listing_urls_batch(listing_ids: List[str]) -> Dict[str, str]:
    """Get URLs for multiple listings at once."""
    urls = _load_listing_urls()
    return {lid: urls.get(str(lid)) for lid in listing_ids if str(lid) in urls}


def get_listing_images_batch(listing_ids: List[str], max_images: int = 3) -> Dict[str, List[str]]:
    """Get images for multiple listings at once."""
    images = _load_listing_images()
    return {
        lid: images.get(str(lid), [])[:max_images]
        for lid in listing_ids
        if str(lid) in images
    }

