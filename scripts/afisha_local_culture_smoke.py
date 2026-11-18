"""Source health smoke check, read only; never publish to Telegram."""
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from afisha_bot import UA
from local_culture_events import collect_local_culture

def main():
    now = datetime.now(ZoneInfo("Europe/Belgrade"))
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "sr,en;q=0.8"})
    events = collect_local_culture(session, now)
    loz = [e for e in events if "lozionica.rs" in e.url]
    local = [e for e in events if "afisha.rs" in e.url]
    print(f"SMALL_CULTURE_SUMMARY official_lozionica={len(loz)} russian_local={len(local)}")
    for e in events[:28]:
        print(f"SMALL_CULTURE_EVENT {e.start:%Y-%m-%d} {e.title[:85]} | "
              f"{e.category} | photo={bool(e.image)} | {e.price}")
    if not loz and not local:
        print("SMALL_CULTURE_ERROR: no verified live events from any new source")
        return 1
    print("SMALL_CULTURE_PASS: at least one new active source yielded verified events")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
