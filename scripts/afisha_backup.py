"""Backup scheduler for Afisha using the established news schedule.

The news bot's existing 15-minute cron is reliable in this repository; use only
six short daytime time windows as a fallback for the separate Afisha schedule.
No new API services or extra paid subscription are required.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Belgrade")
SLOTS = frozenset((8, 10, 12, 15, 18, 20))


def due(now: datetime) -> bool:
    local = now.astimezone(TZ)
    # Two 15-minute news ticks may occur in a window; the Afisha bot's
    # independent 90-minute spacing and five-per-day cap prevent overposting.
    return local.hour in SLOTS and local.minute < 30


def main() -> int:
    now = datetime.now(TZ)
    if not due(now):
        print("No Afisha backup check due at this local hour/minute.")
        return 0
    print("Afisha backup check via known-working news cron.")
    subprocess.run([sys.executable, "afisha_bot.py"], check=True)
    subprocess.run([sys.executable, "scripts/persist_afisha.py"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
