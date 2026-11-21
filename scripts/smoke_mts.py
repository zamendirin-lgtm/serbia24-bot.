"""Read-only source smoke: only metadata, no images or Telegram publication."""
import requests
from urllib.robotparser import RobotFileParser
from datetime import datetime

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
                matched.append((parsed.title, parsed.start.isoformat(), parsed.price))
            if len(matched) >= 3:
                break
        print("MTS SMOKE: parsed upcoming=", len(matched))
        for title, date, price in matched:
            print("MTS SMOKE: event", title[:55], date, price)
        if not matched:
            print("MTS SMOKE WARNING: no parsable current events; investigate source.")
    except requests.RequestException as exc:
        print("MTS SMOKE ERROR:", type(exc).__name__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
