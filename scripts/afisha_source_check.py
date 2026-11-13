"""Live, no-credentials, no-publication test of the official Novi Sad event feed."""
import requests
from datetime import datetime
from afisha_bot import TZ, UA, collect_official_events, event_in_window

def main():
    now = datetime.now(TZ)
    with requests.Session() as session:
        session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
        items = collect_official_events(session, now)
    unique = {e.key: e for e in items if event_in_window(e, now)}
    print(f"Live events found via approved robots-aware source: {len(unique)}")
    for event in list(unique.values())[:4]:
        print(f"{event.start:%Y-%m-%d} | {event.city} | {event.title[:75]} | {event.price} | {event.url}")
    if not unique:
        print("No events parsed: check public source, JSON-LD and robots.txt before relying on automation.")

if __name__ == "__main__":
    main()
