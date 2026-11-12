"""One-time verified Burger King Serbia price post (12 November 2026).

Prices sourced from Biznis Kurir's on-site report at the opening.
Runs only from a dedicated GitHub Actions workflow, using repository secrets.
No price model estimates, no credentials in this file.
"""
from __future__ import annotations

import html
import os
from datetime import datetime, timezone

from bot import (
    Article,
    article_id,
    article_photo,
    load_state,
    normalized_title,
    post_telegram,
    save_state,
    verify_telegram_bot,
)

URL = "https://biznis.kurir.rs/info-biz/10160270/burger-king-otvorio-prvi-restoran-u-beogradu"
SOURCE_TITLE = "Burger King otvorio prvi restoran u Beogradu: koliko košta Whopper i šta je na meniju"
TITLE = "🍔 Burger King открылся в Сербии: сколько стоят бургеры и большие комбо?"
PARAGRAPHS = [
    "12 ноября первый ресторан Burger King в Сербии открылся в торговом центре Ušće в Белграде. Издание Biznis Kurir опубликовало цены из меню нового заведения.",
    "Цены в динарах — сначала отдельный бургер, затем большой комбо (картофель фри + напиток):",
]
MENU = [
    ("Whopper", "590", "1 040"),
    ("Big King", "550", "1 000"),
    ("Crispy Chicken", "490", "940"),
    ("Chicken Royale", "570", "1 020"),
    ("Triple Cheeseburger", "650", "1 100"),
    ("Double Whopper", "890", "1 360"),
    ("Xtra Long Chili Cheese", "790", "1 240"),
    ("Big King XXL", "1 100", "1 570"),
]


def build_caption() -> str:
    prices = "\n".join(
        f"• {html.escape(name)} — {single} / {combo}"
        for name, single, combo in MENU
    )
    caption = (
        f"<b>{html.escape(TITLE)}</b>\n\n"
        f"{html.escape(PARAGRAPHS[0])}\n\n"
        f"{html.escape(PARAGRAPHS[1])}\n"
        f"{prices}\n\n"
        "Следующий ресторан планируют открыть в BEO Shopping Center, "
        "а позже — в ТЦ Galerija.\n\n"
        f'🔗 <a href="{html.escape(URL, quote=True)}">Источник: Biznis Kurir</a>'
    )
    # Telegram sendPhoto captions allow at most 1024 visible characters.
    from bs4 import BeautifulSoup
    assert len(BeautifulSoup(caption, "html.parser").get_text()) <= 1024
    return caption


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    channel = os.getenv("TELEGRAM_CHANNEL", "@serbia24live").strip()
    if not token or not channel:
        raise RuntimeError("Telegram secret/channel not configured")

    article = Article(
        source="Biznis Kurir",
        title=SOURCE_TITLE,
        url=URL,
        summary="Cene Burger King Whopper 590 dinara, veliki obrok 1040 dinara.",
        published_ts=datetime.now(timezone.utc).timestamp(),
    )
    state = load_state()
    uid = article_id(article)
    if uid in state.get("seen", {}):
        print("Burger King price post already published; skipping duplicate.")
        return

    verify_telegram_bot(token, channel)
    caption = build_caption()
    image_url = article_photo(article)
    sent_original = post_telegram(
        caption, token, channel, URL, image_url, caption,
    )
    stamp = datetime.now(timezone.utc).timestamp()
    state.setdefault("seen", {})[uid] = stamp
    state.setdefault("posted", []).append({
        "ts": stamp,
        "title_norm": normalized_title(SOURCE_TITLE),
        "summary_norm": normalized_title(article.summary),
        "source": "Biznis Kurir",
    })
    save_state(state)
    print("Published Burger King verified opening-price post to channel.")
    print("Photo type:", "source photo" if sent_original else "branded fallback")


if __name__ == "__main__":
    main()
