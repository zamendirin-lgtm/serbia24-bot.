"""Live source check, never publishes Telegram messages."""
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from afisha_bot import UA
from major_venues import collect_major_venues


def main():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "sr,en;q=0.8"})
    now = datetime.now(ZoneInfo("Europe/Belgrade"))
    events = collect_major_venues(s, now)
    arena = [x for x in events if "arena" in x.url]
    snp = [x for x in events if "snp.org.rs" in x.url]
    print(f"MAJOR_VENUES_SMOKE arena={len(arena)} snp={len(snp)}")
    for e in events[:16]:
        print("MAJOR_VENUES_EVENT:", e.start.date(), e.title[:75],
              "poster:", bool(e.image), "price:", e.price)
    if not arena or not snp:
        print("MAJOR_VENUES_FAILED: at least one official source did not produce usable event cards.")
        return 1
    print("MAJOR_VENUES_PASS: live official concerts and theatre accessible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
