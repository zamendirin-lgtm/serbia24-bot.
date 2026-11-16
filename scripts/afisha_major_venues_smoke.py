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
    if not arena:
        print("MAJOR_VENUES_FAILED: Arena official feed yielded no dated cultural events.")
        return 1
    if not snp:
        print("MAJOR_VENUES_NOTICE: SNP site denied or did not provide machine-readable records; no unverified entries were published.")
    print("MAJOR_VENUES_PASS: official Arena concert calendar works, SNP access checked conservatively.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
