"""Owner-requested correction of the specific 26 Nov 2026 peregrine-falcon post.

Only edits the original channel message. Never publishes or deletes a message.
"""
import html
import json
import re
import sys
from datetime import date, datetime, timezone

import requests
from bs4 import BeautifulSoup

import bot

SOURCE = "https://phys.org/news/2026-11-world-fastest-animal-livable-territory.html"
EXPECTED_DATE = "2026-11-26"

TITLE = "Сапсаны могут расширить ареал в Британии на 74% к 2080 году"
PARAGRAPH_1 = (
    "По расчётам учёных, к 2080 году площадь территорий Великобритании, "
    "пригодных для обитания сапсанов, может увеличиться примерно на 74%. "
    "Такой прогноз получен для сценария с высокими выбросами парниковых газов."
)
PARAGRAPH_2 = (
    "Однако больше подходящих мест не означает автоматического роста "
    "численности птиц. Для сохранения сапсанов по-прежнему важны "
    "охрана, доступность добычи и снижение угроз со стороны человека."
)


def locate_original():
    # Public Telegram preview exposes original message IDs; the Bot API has
    # no direct getMessage method. Never guess an ID or edit an unrelated post.
    for url in ("https://t.me/s/priroda_realnosti", "https://t.me/priroda_realnosti"):
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"},
                             timeout=24)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            posts = soup.select(".tgme_widget_message[data-post]")
            print("PUBLIC_PREVIEW", url, "cards", len(posts))
            for item in posts[-12:]:
                preview = item.get_text(" ", strip=True)
                dt = item.select_one("time[datetime]")
                print("PREVIEW_ITEM", item.get("data-post", "?"),
                      (dt.get("datetime", "")[:10] if dt else "no-date"),
                      repr(preview[:150]))
            for div in posts:
                text = div.get_text(" ", strip=True).lower()
                if ("2080" not in text or "сапсан" not in text):
                    continue
                # The post may already have an improved headline; identify
                # the same 26-Nov article by its unique subject and date.
                if ("самое быстрое животное" not in text and
                    "сапсаны могут" not in text):
                    continue
                element = div.select_one("time[datetime]")
                if element:
                    raw_date = element.get("datetime", "")[:10]
                    if raw_date and raw_date != EXPECTED_DATE:
                        continue
                post = div.get("data-post", "")
                match = re.fullmatch(r"priroda_realnosti/(\d+)", post,
                                     flags=re.IGNORECASE)
                if match:
                    return int(match.group(1))
        except requests.RequestException as exc:
            print("PUBLIC_CHANNEL_LOOKUP_FAILED", type(exc).__name__)
    return None


def verified_falcon_photo():
    """Exact verified U.S. Fish & Wildlife Service public-domain Commons file.

    Use Wikimedia's direct file path rather than the API, which may return HTTP 429.
    Never send the URL until the remote server confirms a JPEG response.
    """
    import hashlib
    filename = "Falco_peregrinus.jpg"
    digest = hashlib.md5(filename.encode("utf-8")).hexdigest()
    url = ("https://upload.wikimedia.org/wikipedia/commons/" +
           digest[0] + "/" + digest[:2] + "/" + filename)
    page = "https://commons.wikimedia.org/wiki/File:Falco_peregrinus.jpg"
    try:
        with bot.HTTP.get(url, stream=True, timeout=25) as response:
            print("FALCON_DIRECT_STATUS", response.status_code,
                  response.headers.get("content-type", "unknown"))
            response.raise_for_status()
            if not response.headers.get("content-type", "").lower().startswith("image/jpeg"):
                return None
            first = next(response.iter_content(1024), b"")
            if not first.startswith(b"\xff\xd8"):
                return None
        return {"id": "commons:public-domain-falco-peregrinus",
                "url": url, "page": page,
                "license": {"name": "Public domain", "credit": "", "lic_url": ""}}
    except (requests.RequestException, ValueError, OSError) as exc:
        print("FALCON_DIRECT_FETCH_FAILED", type(exc).__name__)
    return None


def main():
    if bot.DRY or not bot.TOKEN:
        raise RuntimeError("This correction needs the secret and live mode")
    message_id = locate_original()
    if message_id is None:
        print("NOT_EDITED: target post not reliably identified")
        sys.exit(1)
    media = (bot.commons_image("peregrine falcon", bot.read_state())
             or verified_falcon_photo())
    if not media:
        print("NOT_EDITED: no reusable photo confirmed to depict a peregrine falcon")
        sys.exit(1)
    caption = ("🦅 <b>" + html.escape(TITLE) + "</b>\n\n" +
               html.escape(PARAGRAPH_1) + "\n\n" +
               html.escape(PARAGRAPH_2) + "\n\n" +
               bot.compact_source_line(SOURCE, media))
    if len(caption) > 1024:
        print("NOT_EDITED: full caption exceeds Telegram photo limit")
        sys.exit(1)
    input_media = json.dumps({
        "type": "photo",
        "media": media["url"],
        "caption": caption,
        "parse_mode": "HTML"
    }, ensure_ascii=False)
    bot.telegram("editMessageMedia", {
        "chat_id": bot.CHAT, "message_id": str(message_id),
        "media": input_media
    })
    print("PEREGRINE_ARTICLE_CORRECTED_IN_PLACE", message_id, media["id"])
    print("NO_NEW_TELEGRAM_POST_CREATED")


if __name__ == "__main__":
    main()
