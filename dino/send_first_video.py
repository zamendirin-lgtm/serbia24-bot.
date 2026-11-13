"""Publish one licensed, actual, inline-playable dinosaur stop-motion video."""
import os
import subprocess
import tempfile
from pathlib import Path

import requests
from bot import CHAT_ID, BOT_TOKEN, ROOT, load_state, save_state, telegram_send

VIDEO_URL = "https://upload.wikimedia.org/wikipedia/commons/1/16/Naughty_dino_gets_a_surprise.webm"
SOURCE_PAGE = "https://commons.wikimedia.org/wiki/File:Naughty_dino_gets_a_surprise.webm"
LICENSE = "https://creativecommons.org/licenses/by/3.0/"
KEY = "commons-naughty-dino-2016"


def main():
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Missing Telegram secrets")
    state = load_state()
    if KEY in state.get("video_posts", {}):
        print("VIDEO_ALREADY_POSTED", state["video_posts"][KEY])
        return
    chat = telegram_send("getChat", data={"chat_id": CHAT_ID})
    if chat.get("type") not in ("group", "supergroup"):
        raise RuntimeError("Refusing to post outside the group")
    me = telegram_send("getMe")
    member = telegram_send("getChatMember", data={"chat_id": CHAT_ID, "user_id": me["id"]})
    if member.get("status") not in ("administrator", "creator"):
        raise RuntimeError("Bot must be an administrator")

    with tempfile.TemporaryDirectory() as tmp:
        webm = Path(tmp) / "original.webm"
        mp4 = Path(tmp) / "dino.mp4"
        response = requests.get(
            VIDEO_URL,
            timeout=40,
            headers={"User-Agent": "DinoDvijPublisher/1.0 (https://t.me/AVQ_GO)"},
        )
        response.raise_for_status()
        if not 100_000 < len(response.content) < 20_000_000:
            raise RuntimeError("Unexpected video size")
        webm.write_bytes(response.content)
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(webm),
             "-vf", "scale='min(1080,iw)':-2",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
             "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k",
             "-movflags", "+faststart", str(mp4)],
            timeout=100,
            check=True,
        )
        caption = (
            "🦖 Маленький динозаврик и неожиданный сюрприз! 😂\n\n"
            "Короткая стоп-моушен анимация. Как вам такой динозавр? 🐾\n\n"
            "Видео: Cristian Bulumac · "
            '<a href="https://creativecommons.org/licenses/by/3.0/">CC BY 3.0</a>'
            ' · <a href="' + SOURCE_PAGE + '">·</a>'
        )
        with mp4.open("rb") as video_file:
            result = telegram_send(
                "sendVideo",
                data={
                    "chat_id": CHAT_ID,
                    "caption": caption,
                    "parse_mode": "HTML",
                    "supports_streaming": "true",
                },
                files={"video": ("dino.mp4", video_file, "video/mp4")},
            )
        message_id = result.get("message_id")
        if not message_id:
            raise RuntimeError("Telegram did not return message_id")
        state.setdefault("video_posts", {})[KEY] = message_id
        save_state(state)
        print("VIDEO_POSTED_OK", "message_id:", message_id, "size:", mp4.stat().st_size)


if __name__ == "__main__":
    main()
