"""Persist independent real estate history without touching news state."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

PATH = Path("data/estate_seen.json")


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], check=check, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )


def state_from(text: str) -> dict:
    try:
        loaded = json.loads(text)
        return loaded if isinstance(loaded, dict) else {}
    except (TypeError, ValueError):
        return {}


def persist() -> None:
    if not PATH.exists():
        print("No property history to save.")
        return
    local = state_from(PATH.read_text(encoding="utf8"))
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    for i in range(5):
        git("fetch", "origin", "main")
        remote_file = git("show", "origin/main:data/estate_seen.json", check=False)
        remote = state_from(remote_file.stdout if remote_file.returncode == 0 else "{}")
        merged = dict(remote)
        for key, item in local.items():
            if key not in merged or str(item.get("posted_at", "")) > str(
                merged[key].get("posted_at", "")
            ):
                merged[key] = item
        if merged == remote:
            print("Property history already saved.")
            return
        git("reset", "--hard", "origin/main")
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
        git("add", str(PATH))
        if git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return
        git("commit", "-m", "chore: remember published properties")
        pushed = git("push", "origin", "HEAD:main", check=False)
        if pushed.returncode == 0:
            print("Property history saved.")
            return
        print(f"State conflict, retry {i+1}/5")
        time.sleep(i + 1)
    raise RuntimeError("Unable to persist property history")


if __name__ == "__main__":
    persist()
