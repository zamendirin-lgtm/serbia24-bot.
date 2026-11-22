"""Only event-related images from an organizer's own verified page.

MTS Dvorana serves its official event posters from the exact S3 host
kombank.s3.amazonaws.com, not from the mtsdvorana.rs domain. An arbitrary
image URL from that S3 bucket is NOT accepted without an MTS event source.
The full URL must also come from a parsed official event page.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


VENUE_IMAGE_HOSTS = {
    "mtsdvorana.rs": {
        "mtsdvorana.rs", "www.mtsdvorana.rs",
        "kombank.s3.amazonaws.com",
        "kombank.s3.eu-central-1.amazonaws.com",
    },
    "savacentar.rs": {"savacentar.rs", "www.savacentar.rs"},
    "arenabeograd.com": {"arenabeograd.com", "www.arenabeograd.com"},
    "lozionica.rs": {"lozionica.rs", "www.lozionica.rs"},
    "novisad.travel": {"novisad.travel", "www.novisad.travel"},
}
NO_POSTER = (
    "logo", "favicon", "placeholder", "default", "avatar",
    "payment", "mastercard", "visa-card", "credit-card",
)
EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def trusted_event_image(image_url: str, source_url: str = "") -> bool:
    """Strict HTTPS host check; S3 is allowed only for MTS's event pages."""
    if not isinstance(image_url, str):
        return False
    try:
        image = urlparse(image_url)
        source = urlparse(source_url) if source_url else None
    except ValueError:
        return False
    if (image.scheme != "https" or not image.hostname or image.username or image.password
        or not image.path.lower().endswith(EXTENSIONS)
        or any(word in image.path.casefold() for word in NO_POSTER)):
        return False
    if source is not None:
        if source.scheme != "https" or source.username or source.password:
            return False
        host = (source.hostname or "").removeprefix("www.")
        if host not in VENUE_IMAGE_HOSTS or image.hostname not in VENUE_IMAGE_HOSTS[host]:
            return False
        if host == "mtsdvorana.rs" and not source.path.startswith("/dogadjaj/"):
            return False
    else:
        # Backwards compatible recognition of same-site venues, but do not
        # trust the S3 bucket without the linked verified MTS event page.
        return image.hostname in {
            h for group in VENUE_IMAGE_HOSTS.values() for h in group
        } - {"kombank.s3.amazonaws.com", "kombank.s3.eu-central-1.amazonaws.com"}
    if image.hostname == "kombank.s3.amazonaws.com":
        # The first bucket uses year/month UUID filenames.
        if not re.fullmatch(
            r"/20\d\d/(?:0?[1-9]|1[0-2])/[A-Za-z0-9_.-]+\.(?:jpe?g|png|webp)",
            image.path, re.I,
        ):
            return False
    if image.hostname == "kombank.s3.eu-central-1.amazonaws.com":
        # The venue's newer regional bucket uses flat hex-encoded object keys,
        # e.g. /bbbd1cd601847.png on the BOŽO VREĆO event page.
        if not re.fullmatch(r"/[0-9a-f]{10,64}\.(?:jpe?g|png|webp)", image.path, re.I):
            return False
    return True


def _same_title(alt: str, title: str) -> bool:
    def words(value):
        return [p for p in re.findall(r"[\w]+", value.casefold()) if len(p) > 2]
    expected = words(title)
    actual = words(alt)
    if not expected or len(actual) < min(len(expected), 2):
        return False
    # Require multiple distinctive words, not just e.g. 'show'.
    overlap = len(set(expected) & set(actual))
    return overlap >= max(2, round(len(set(expected)) * .75))


def _image_attrs(node) -> list[str]:
    """Read common lazy-loading and responsive picture attributes."""
    candidates = []
    for attr in ("data-src", "data-lazy-src", "src", "content", "data-original"):
        raw = node.get(attr)
        if isinstance(raw, str) and raw.strip():
            candidates.append(raw.strip())
    for attr in ("data-srcset", "srcset"):
        raw = node.get(attr)
        if isinstance(raw, str):
            # Higher-resolution srcset entries normally come last.
            items = [item.strip().split()[0] for item in raw.split(",") if item.strip()]
            candidates.extend(reversed(items))
    return candidates


def find_official_event_poster(soup: BeautifulSoup, event_url: str, event_title: str) -> str:
    """Prefer the actual named poster; never confuse footer/payment logos with it."""
    candidates: list[str] = []
    # This is how MTS Dvorana presents its poster on the event page: an
    # img whose alt is exactly the event heading, BEFORE the h1 element.
    for img in soup.select("img[alt]"):
        if _same_title(str(img.get("alt", "")), event_title):
            candidates.extend(_image_attrs(img))
            parent = img.parent
            if parent and parent.name == "picture":
                for source in parent.select("source[srcset], source[data-srcset]"):
                    candidates.extend(_image_attrs(source))

    # Site-specific event hero; these are not generic page banners.
    for selector in (
        ".tribe-events-event-image img", ".event-image img",
        ".event-hero img", ".single-event img", ".event-banner img",
        "article .featured-image img",
    ):
        for img in soup.select(selector)[:3]:
            candidates.extend(_image_attrs(img))

    # Meta image on a detail page can be a real event poster; use only if
    # no actual named event photo was found and never use site logos.
    for meta in soup.select(
        'meta[property="og:image"], meta[property="og:image:secure_url"], '
        'meta[name="twitter:image"]'
    ):
        candidates.extend(_image_attrs(meta))

    # Some templates expose the poster in JSON-LD only.
    for script in soup.select('script[type="application/ld+json"]')[:5]:
        try:
            import json
            payload = json.loads(script.string or script.get_text() or "{}")
        except (ValueError, TypeError):
            continue
        objects = payload if isinstance(payload, list) else [payload]
        for obj in objects:
            if not isinstance(obj, dict) or "Event" not in str(obj.get("@type", "")):
                continue
            image = obj.get("image", "")
            if isinstance(image, dict):
                image = image.get("url") or image.get("contentUrl")
            if isinstance(image, list):
                image = image[0] if image else ""
            if isinstance(image, str):
                candidates.append(image)

    for raw in candidates:
        if not raw:
            continue
        link = urljoin(event_url, raw)
        if trusted_event_image(link, event_url):
            return link
    return ""
