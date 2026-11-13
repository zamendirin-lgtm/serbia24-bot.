"""Save Afisha history independently of the news and property histories."""
from __future__ import annotations
import json
import subprocess
import time
from pathlib import Path

STATE = Path("data/afisha_seen.json")


def git(*args: str, check=True):
    return subprocess.run(["git", *args], text=True, check=check,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def state(raw: str) -> dict:
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except ValueError:
        return {}


def main() -> None:
    if not STATE.exists():
        return
    local = state(STATE.read_text(encoding="utf8"))
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    for attempt in range(5):
        git("fetch", "origin", "main")
        current = git("show", "origin/main:data/afisha_seen.json", check=False)
        remote = state(current.stdout if current.returncode == 0 else "{}")
        merged = dict(remote)
        for key, item in local.items():
            if key not in merged or str(item.get("published_at", "")) > str(
                merged[key].get("published_at", "")
            ):
                merged[key] = item
        if merged == remote:
            return
        git("reset", "--hard", "origin/main")
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf8")
        git("add", str(STATE))
        if git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return
        git("commit", "-m", "chore: record afisha event post history")
        pushed = git("push", "origin", "HEAD:main", check=False)
        if pushed.returncode == 0:
            return
        print(f"Afisha history conflict; retry {attempt + 1}")
        time.sleep(attempt + 1)
    raise RuntimeError("Could not persist Afisha post history")


if __name__ == "__main__":
    main()
