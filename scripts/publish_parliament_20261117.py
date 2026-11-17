"""One-time fact-checked 17 Nov 2026 Serbian parliament milestone.

Strictly respects the channel's daytime, 90-minute, 10/day and duplicate
requirements. Distinct from the *morning announcement*: mandates have
now been confirmed and the newly elected MPs have taken their oath.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from bs4 import BeautifulSoup

from bot import (
    Article, TZ, article_id, article_photo, interval_allows_publication,
    is_duplicate, load_state, normalized_title, photo_caption,
    post_telegram, publication_allowed, prune_state, save_state,
    verify_telegram_bot,
)

URL = "https://www.tanjug.rs/srbija/politika/298393/poslanici-skupstine-srbije-polozili-zakletvu/vest"
SERBIAN_TITLE = "Poslanici Skupštine Srbije položili zakletvu"
HEADLINE_RU = (
    "Новый парламент Сербии начал работу: депутаты принесли присягу, "
    "большинство — у «Студенческого списка»"
)
PARAGRAPHS_RU = (
    "Сегодня, 17 ноября, в Белграде официально сформирован новый состав "
    "парламента Сербии. На первом заседании Скупщины подтвердили мандаты "
    "депутатов, после чего они принесли присягу. Досрочные выборы прошли "
    "25 октября.\n\n"
    "«Студенческий список» получил 140 из 250 мест — абсолютное "
    "большинство. У списка «Александр Вучич — Объединённая Сербия», "
    "сформированного вокруг Сербской прогрессивной партии, 103 мандата. "
    "Парламенту предстоит избрать новое руководство; следующий важный "
    "этап — формирование правительства."
)
SOURCE_RU = "Tanjug"


def main() -> None:
    now = datetime.now(timezone.utc)
    state = load_state()
    prune_state(state, now)
    if not publication_allowed(now):
        print("SKIP: quiet hours 22:00–08:00 Belgrade")
        return
    posts_today = sum(
        datetime.fromtimestamp(float(item["ts"]), TZ).date()
        == now.astimezone(TZ).date()
        for item in state["posted"]
    )
    if posts_today >= 10:
        print("SKIP: 10 posts per Belgrade calendar day reached")
        return
    if not interval_allows_publication(state, now):
        print("SKIP: at least 90 minutes between publications")
        return

    article = Article(
        SOURCE_RU, SERBIAN_TITLE, URL,
        "Poslanicima potvrđeni mandati i položena zakletva. "
        "Studentska lista osvojila 140, a Ujedinjena Srbija 103 mandata.",
        now.timestamp(),
    )
    if is_duplicate(article, state):
        print("SKIP: same parliamentary oath milestone already published")
        return
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    channel = os.getenv("TELEGRAM_CHANNEL", "@serbia24live").strip()
    if not token or not channel:
        raise RuntimeError("Telegram token or channel missing")

    verify_telegram_bot(token, channel)
    caption = photo_caption(article, HEADLINE_RU, PARAGRAPHS_RU)
    visible_length = len(BeautifulSoup(caption, "html.parser").get_text())
    if visible_length > 1024:
        raise RuntimeError("Telegram photo caption exceeds 1024 characters")
    picture = article_photo(article)
    source_photo_used = post_telegram(
        caption, token, channel, URL, picture, caption
    )
    stamp = datetime.now(timezone.utc).timestamp()
    state["seen"][article_id(article)] = stamp
    state["posted"].append({
        "ts": stamp,
        "title_norm": normalized_title(SERBIAN_TITLE),
        "summary_norm": normalized_title(article.summary),
        "source": SOURCE_RU,
        "published_title_ru": HEADLINE_RU,
        "published_text_ru": PARAGRAPHS_RU,
        "article_url": URL,
        "caption_text": BeautifulSoup(caption, "html.parser").get_text("\n", strip=True),
    })
    save_state(state)
    print("PUBLISHED parliament oath and Studentska lista majority news")
    print("Source photo:", "yes" if source_photo_used else "no, channel fallback logo")


if __name__ == "__main__":
    main()
