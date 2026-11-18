"""Persist Telegram welcome poll offsets; never store visitor identities."""
from __future__ import annotations
import json
import subprocess
import time
from pathlib import Path

STATE = Path("data/welcome_offsets.json")


def git(*args: str, check: bool = True):
    return subprocess.run(
        ["git", *args], text=True, check=check,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def parse(raw: str) -> dict[str, int]:
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        k: v for k, v in value.items()
        if isinstance(k, str) and k.isdecimal()
        and type(v) is int and v >= 0
    }


def main() -> None:
    if not STATE.exists():
        return
    local = parse(STATE.read_text(encoding="utf8"))
    if not local:
        return
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    for attempt in range(5):
        git("fetch", "origin", "main")
        previous = git("show", "origin/main:" + str(STATE), check=False)
        remote = parse(previous.stdout if previous.returncode == 0 else "{}")
        merged = dict(remote)
        for identity, offset in local.items():
            merged[identity] = max(remote.get(identity, 0), offset)
        if merged == remote:
            return
        git("reset", "--hard", "origin/main")
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf8")
        git("add", str(STATE))
        if git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return
        git("commit", "-m", "chore: record private bot command offsets [skip ci]")
        push = git("push", "origin", "HEAD:main", check=False)
        if push.returncode == 0:
            return
        print("Welcome state push conflict; will retry.")
        time.sleep(1 + attempt)
    raise RuntimeError("Welcome command offsets could not be persisted")


if __name__ == "__main__":
    main()
