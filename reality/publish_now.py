#!/usr/bin/env python3
"""One-time, source-checked publication, explicitly requested by channel owner."""
import html
import sys
from datetime import datetime, timezone

import requests
import bot

KEY = "editorial-2026-11-12-mars-organic-carbon"
SOURCE = "https://www.sciencedaily.com/releases/2026/11/261111005908.htm"

TITLE = "🔴 На Марсе нашли органические соединения. Значит ли это, что там была жизнь?"
BODY = (
    "Марсоход NASA Perseverance подтвердил присутствие сложного органического углерода "
    "в двух древних породах формации Bright Angel в кратере Езеро. Особенно удивительно, "
    "что органика сохранилась всего в нескольких микронах под поверхностью, несмотря "
    "на разрушительное воздействие марсианской среды.\n\n"
    "Подобные соединения могут быть необходимыми компонентами живых систем, однако "
    "они способны возникать и в результате процессов без участия живых организмов. "
    "Поэтому открытие не доказывает, что на Марсе существовала жизнь, но помогает "
    "понять, где искать её возможные следы."
)
def content(add_media_credit=None):
    caption = '<b>' + html.escape(TITLE) + '</b>\n\n' + html.escape(BODY)
    if add_media_credit:
        caption += "\n\n" + bot.compact_source_line(SOURCE, add_media_credit)
    else:
        caption += '\n\n🔗 <a href="' + html.escape(SOURCE, quote=True) + '">Источник</a>'
    return caption

def main():
    state = bot.read_state()
    if KEY in state.get("posted", {}):
        print("ALREADY_POSTED_ONE_TIME_ARTICLE; skipping")
        return
    if not bot.TOKEN or bot.DRY:
        print("MANUAL_ARTICLE_NOT_PUBLISHED: missing secret or preview mode")
        sys.exit(1)
    # Only the manually requested publication bypasses quiet hours and the
    # scheduled minimum interval; all future posts obey existing limits.
    media = bot.commons_image("NASA Perseverance rover Mars", state)
    if media:
        caption = content(media)
        if len(caption) <= 1024:
            try:
                bot.telegram("sendPhoto", {
                    "chat_id": bot.CHAT, "photo": media["url"],
                    "caption": caption, "parse_mode": "HTML",
                    "disable_notification": "false"
                })
                bot.record_send(state, KEY, media["id"])
                print("PUBLISHED_MANUAL_ARTICLE_WITH_IMAGE")
                return
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                print("IMAGE_UPLOAD_FAILED; attempting text-only publication", type(exc).__name__)
    body = content()
    bot.telegram("sendMessage", {"chat_id": bot.CHAT, "text": body,
                                  "parse_mode": "HTML",
                                  "disable_web_page_preview": "true"})
    bot.record_send(state, KEY, "")
    print("PUBLISHED_MANUAL_ARTICLE_AS_TEXT")

if __name__ == "__main__":
    main()
