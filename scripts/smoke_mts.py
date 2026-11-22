"""Read-only source smoke: only metadata, no images or Telegram publication."""
import requests
from urllib.robotparser import RobotFileParser
from datetime import datetime
from urllib.parse import urlparse

from mts_events import BASE, CALENDAR, list_event_urls, parse_detail
from afisha_bot import TZ, UA


def main():
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    try:
        robots = session.get(BASE + "/robots.txt", timeout=12)
        robots.raise_for_status()
        rules = RobotFileParser()
        rules.parse(robots.text.splitlines())
        if not rules.can_fetch(UA, CALENDAR):
            print("MTS SMOKE: source disallows discovery (robots); no attempts made.")
            return 0
        listing = session.get(CALENDAR, timeout=20)
        listing.raise_for_status()
        urls = list_event_urls(listing.text)
        print("MTS SMOKE: listing links=", len(urls))
        matched = []
        for url in urls[:12]:
            if not rules.can_fetch(UA, url):
                continue
            page = session.get(url, timeout=13)
            page.raise_for_status()
            parsed = parse_detail(page.text, url, datetime.now(TZ))
            if parsed:
                matched.append((parsed.title, parsed.start.isoformat(),
                                parsed.price, parsed.image))
            if len(matched) >= 3:
                break
        print("MTS SMOKE: parsed upcoming=", len(matched))
        for title, date, price, image in matched:
            print("MTS SMOKE: event", title[:55], date, price,
                  "real_poster=" + str(bool(image)))
        if not matched:
            print("MTS SMOKE WARNING: no parsable current events; investigate source.")
        # Specific owner-reported failure: venue shows a full official poster
        # for the 20 Dec 2026 New Year magic show; it must no longer be missed.
        sample = BASE + "/dogadjaj/igorov-novogodisnji-magicni-show"
        if sample in urls and rules.can_fetch(UA, sample):
            page = session.get(sample, timeout=13)
            page.raise_for_status()
            parsed = parse_detail(page.text, sample, datetime.now(TZ))
            if parsed:
                print("MTS SMOKE: Igor official poster found=", bool(parsed.image),
                      "poster_host=", urlparse(parsed.image).hostname)
                if not parsed.image:
                    print("MTS SMOKE WARNING: organizer has event poster, extraction failed.")
    except requests.RequestException as exc:
        print("MTS SMOKE ERROR:", type(exc).__name__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
