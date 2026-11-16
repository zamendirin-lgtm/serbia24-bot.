"""Real-read smoke check for official Sava Centar events, without Telegram posting."""
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from sava_events import collect_sava_events
from afisha_bot import UA, select, load_seen

def main() -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "sr,en;q=0.8"})
    now = datetime.now(ZoneInfo("Europe/Belgrade"))
    events = collect_sava_events(session, now)
    print("SAVA_SMOKE: found", len(events), "future cultural event records")
    for e in events[:24]:
        print("SAVA_SMOKE_EVENT:", e.start.isoformat(), e.title[:85],
              "poster:", bool(e.image), "tickets:", bool(e.ticket_url))
    nutcracker = [e for e in events if (
        ("krcko" in e.title.casefold() or "oraš" in e.title.casefold())
        and e.start.year == 2026 and e.start.month == 12 and e.start.day == 20
    )]
    if nutcracker:
        print("SAVA_SMOKE_NUTCRACKER: FOUND", [(e.start.isoformat(), bool(e.image)) for e in nutcracker])
    else:
        print("SAVA_SMOKE_NUTCRACKER: MISSING")
    if not events or not nutcracker:
        print("SAVA_SMOKE_FAILED: official source missing the important holiday show.")
        return 1
    print("SAVA_SMOKE_PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
