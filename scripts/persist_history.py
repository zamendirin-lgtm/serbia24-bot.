"""Safely persist bot state even if somebody updates the GitHub repo mid-run.

This script runs after successful news publishing. It never overwrites other
files and merges independent state updates rather than losing either side.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

STATE_PATH = Path("data/seen.json")
FIELDS = ("seen", "photos", "phashes")


def normalize_state(value: dict | None) -> dict:
    value = value or {}
    return {
        **{field: dict(value.get(field, {})) for field in FIELDS},
        "posted": list(value.get("posted", [])),
    }


def merge_states(current: dict, remote: dict) -> dict:
    a = normalize_state(current)
    b = normalize_state(remote)
    out = normalize_state({})
    for field in FIELDS:
        merged = dict(b[field])
        for key, stamp in a[field].items():
            if key not in merged or float(stamp) > float(merged[key]):
                merged[key] = stamp
        out[field] = merged

    combined = b["posted"] + a["posted"]
    unique = {}
    for row in combined:
        if not isinstance(row, dict):
            continue
        key = (str(row.get("title_norm", "")), str(row.get("source", "")),
               str(row.get("ts", 0)))
        unique[key] = row
    out["posted"] = sorted(unique.values(), key=lambda row: float(row.get("ts", 0)))
    return out


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def read_remote() -> dict:
    result = git("show", "origin/main:data/seen.json", check=False)
    if result.returncode != 0:
        return normalize_state({})
    return json.loads(result.stdout)


def persist() -> None:
    local = normalize_state(json.loads(STATE_PATH.read_text(encoding="utf8")))
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")

    for attempt in range(5):
        git("fetch", "origin", "main")
        remote = read_remote()
        merged = merge_states(local, remote)
        if merged == normalize_state(remote):
            print("Publication history already persisted.")
            return

        # The job's checkout is disposable. Reset it to current remote HEAD
        # so source code never gets force-pushed or overwritten by stale code.
        git("reset", "--hard", "origin/main")
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
            encoding="utf8",
        )
        git("add", str(STATE_PATH))
        if git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return
        git("commit", "-m", "chore: record published headlines")
        pushed = git("push", "origin", "HEAD:main", check=False)
        if pushed.returncode == 0:
            print("Merged publication history successfully.")
            return
        print(f"History push conflict, retrying ({attempt + 1}/5).")
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("Could not persist publication history after 5 attempts")


if __name__ == "__main__":
    try:
        persist()
    except Exception as exc:
        print(f"State save failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
