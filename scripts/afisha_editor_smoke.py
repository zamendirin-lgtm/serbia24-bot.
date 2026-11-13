"""Read-only live smoke of the Afisha editor. NEVER sends to Telegram."""
from __future__ import annotations

import os
import requests
from datetime import datetime

from afisha_bot import TZ, UA, collect_official_events, select
from afisha_editor import edit_event


def main() -> int:
    if not (os.getenv("GROQ_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        print("No AI editor credential present; add GROQ_API_KEY or GEMINI_API_KEY.")
        return 1
    now = datetime.now(TZ)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
    events = collect_official_events(session, now)
    candidates = select(events, {}, now)
    print(f"Live source candidates {len(events)}; top eligible {len(candidates)}.")
    if not candidates:
        print("No quality candidate in the source; no posts were sent.")
        return 0
    for e in candidates[:3]:
        edited = edit_event(e)
        if edited is None:
            print("AI passed over one candidate.")
            continue
        print(f"AI approved event: {e.start:%Y-%m-%d}, {e.city}, score={edited.interest_score}, provider={edited.provider}")
        print("TITLE: " + edited.title_ru)
        print("DESCRIPTION: " + edited.summary_ru)
        print("SOURCE: " + e.url)
        print("No Telegram post was sent.")
        return 0
    print("AI rejected top candidates or API was unavailable; no Telegram post was sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
