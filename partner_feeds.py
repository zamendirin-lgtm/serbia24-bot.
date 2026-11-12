"""Fetch authorized property-partner JSON feeds (NOT scraping portals).

Feed operators must explicitly license text and optional images for Telegram
redistribution. A public API alone never implies syndication rights.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlparse

import requests
from estate_cards import safe_https_url


def configured_feed_urls() -> list[str]:
    if os.getenv("PROPERTY_PARTNER_FEEDS_ENABLED", "") != "1":
        return []
    if os.getenv("PROPERTY_PARTNER_LICENSE_CONFIRMED", "") != "1":
        print("Partner feeds disabled: license confirmation not configured.")
        return []
    raw = os.getenv("PROPERTY_PARTNER_FEEDS", "")
    urls = []
    for entry in raw.split(",")[:5]:
        url = entry.strip()
        if not url:
            continue
        if not safe_https_url(url) or urlparse(url).port not in (None, 443):
            print("Skipped invalid partner feed URL.")
            continue
        if url not in urls:
            urls.append(url)
    return urls


def fetch_partner_entries(session: requests.Session) -> list[dict]:
    """Pull up to five approved JSON feeds with a max response body.

    Contract: {"listings": [{approved:true, permission_to_publish:true, ...}]}.
    No redirects, HTML scraping, data discovery or leaked Authorization headers.
    """
    urls = configured_feed_urls()
    entries: list[dict] = []
    auth = os.getenv("PROPERTY_PARTNER_FEED_TOKEN", "").strip()
    headers = {"Accept": "application/json"}
    if auth:
        headers["Authorization"] = "Bearer " + auth
    for url in urls:
        try:
            with session.get(
                url, headers=headers, timeout=18, allow_redirects=False, stream=True
            ) as response:
                if response.status_code != 200:
                    print(f"Partner feed returned HTTP {response.status_code}, skipped.")
                    continue
                if "application/json" not in response.headers.get("Content-Type", "").lower():
                    print("Partner feed returned non-JSON response.")
                    continue
                # 512 kB is sufficient for structured metadata. Images must be URLs.
                body = bytearray()
                for chunk in response.iter_content(8192):
                    body.extend(chunk)
                    if len(body) > 524288:
                        raise ValueError("Partner feed exceeds the 512 kB size limit")
                payload = json.loads(body)
                items = payload.get("listings", []) if isinstance(payload, dict) else []
                if not isinstance(items, list):
                    continue
                entries.extend(item for item in items[:100] if isinstance(item, dict))
        except (requests.RequestException, ValueError, OSError):
            print("Partner feed request or JSON parsing failed; source skipped.")
    print(f"Partner-feed candidate records: {len(entries)}")
    return entries
