"""Source health smoke check, read only; never publish to Telegram."""
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from urllib.parse import urlparse
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
        from local_culture_events import LOZ, LOZ_CALENDAR, AFISHA, AFISHA_CATEGORIES, loz_links, loz_detail, afisha_cards, robots_allowed
        for base, urls in ((LOZ, [LOZ_CALENDAR]), (AFISHA, [AFISHA + x for x in AFISHA_CATEGORIES])):
            try:
                robot_resp = session.get(base + "/robots.txt", timeout=12)
                print("SMALL_CULTURE_DIAG robots", base, robot_resp.status_code,
                      "bytes", len(robot_resp.content))
                good = robots_allowed(session, base, urls, UA)
                print("SMALL_CULTURE_DIAG robots_allow", base, len(good),
                      "of", len(urls))
                for uri in good[:2]:
                    r = session.get(uri, timeout=16)
                    print("SMALL_CULTURE_DIAG page", uri, r.status_code,
                          "bytes", len(r.content),
                          "links", len(loz_links(r.text)) if base==LOZ else "n/a",
                          "cards", len(afisha_cards(r.text, now, urlparse(uri).path)) if base==AFISHA else "n/a")
                    if base==LOZ:
                        for u in loz_links(r.text)[:3]:
                            d = session.get(u, timeout=12)
                            event = loz_detail(d.text, u, now)
                            print("SMALL_CULTURE_DIAG detail", d.status_code, u,
                                  "event", event.title if event else None,
                                  "bytes", len(d.content))
                            if not event:
                                from bs4 import BeautifulSoup
                                soup=BeautifulSoup(d.text, "html.parser")
                                h=[x.get_text(" ", strip=True)[:90] for x in soup.select("h1,h2,h3")[:12]]
                                m=soup.select_one("meta[property='og:title']")
                                print("SMALL_CULTURE_DIAG head", h[:8],
                                      "og", m.get("content","")[:95] if m else "",
                                      "tribe", len(soup.select(".tribe-events-schedule")),
                                      "elem_text", len(soup.select(".elementor-widget-text-editor")))
            except requests.RequestException as err:
                print("SMALL_CULTURE_DIAG network_exception", base, type(err).__name__)
        print("SMALL_CULTURE_ERROR: no verified live events from any new source")
        return 1
    print("SMALL_CULTURE_PASS: at least one new active source yielded verified events")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

# Official Ložionica OG event title reconciliation.
