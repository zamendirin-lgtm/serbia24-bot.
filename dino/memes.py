"""Original youth-culture meme cards for DinoDvij, no copied social media art.

Humor includes edgy opinions and hobby rivalries, never personalized bullying.
"""
from __future__ import annotations
import hashlib
import math
import random
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import bot

W, H = 1080, 1350
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
MEMES = [
    ("БАТТЛ НЕДЕЛИ", "ТЕРИАНЫ", "ДИНОСЬЮТЫ", "ЧЕЙ ДВИЖ ГРОМЧЕ?", "Ну что, начинаем спор? 🔥"),
    ("ВОПРОС РЕБРОМ", "МАСКА СВОИМИ РУКАМИ", "ГОТОВЫЙ КОСТЮМ", "ГДЕ БОЛЬШЕ СТИЛЯ?", "Кто за что? 👀"),
    ("УРОВЕНЬ КРИНЖА", "СНИМАТЬ 10 ДУБЛЕЙ", "ВЫЛОЖИТЬ ПЕРВЫЙ", "ЧТО СТРАШНЕЕ?", "Только не говорите, что легко 😅"),
    ("БИТВА ОБРАЗОВ", "ЛИСЬЯ МАСКА", "КОСТЮМ ДИНО", "КТО УКРАДЁТ ВСЕ ЛАЙКИ?", "Выбирай сторону 🐾🦖"),
    ("САМЫЙ СЛОЖНЫЙ ВЫБОР", "ЭПИЧНЫЙ ВЫХОД", "ЭПИЧНЫЙ ФЕЙЛ", "ЧТО НАБЕРЁТ БОЛЬШЕ ПРОСМОТРОВ?", "Интернет любит неожиданности 😈"),
    ("СКАНДАЛ НА РОВНОМ МЕСТЕ", "ЭТО КРИНЖ", "ЭТО ИСКУССТВО", "ВЕЧНЫЙ СПОР", "А ты на чьей стороне? 🔥"),
    ("БАТТЛ КОСТЮМОВ", "КРАСИВЫЙ ОБРАЗ", "СМЕШНОЙ ОБРАЗ", "КТО ПОБЕДИТ В ЛЕНТЕ?", "Голосуем в комментариях 👇"),
    ("ЗАКОН СОЦСЕТЕЙ", "ГОТОВИЛСЯ 3 ЧАСА", "СНЯЛ ЗА 3 СЕКУНДЫ", "ЧТО ЗАВИРУСИТСЯ?", "Классика интернета 🤡"),
    ("ТЕРРИАНСКИЕ ДИЛЕММЫ", "ИДЕАЛЬНАЯ МАСКА", "ИДЕАЛЬНЫЙ ТРЮК", "КУДА ВЛОЖИТЬ ВСЁ ВРЕМЯ?", "Серьёзный выбор? 😏"),
    ("ТАК И ЖИВЁМ", "НАЗВАЛИ СТРАННЫМ", "ПОПРОСИЛИ ССЫЛКУ", "ПЕРЕОБУВАНИЕ ЗА 3 СЕКУНДЫ", "Узнали ситуацию?"),
    ("ВОЙНА ФОРМАТОВ", "ВИДЕО 9:16", "ВИДЕО 16:9", "ЧТО СМОТРИШЬ ДО КОНЦА?", "Неожиданная битва 📱"),
    ("ТЕСТ НА ВКУС", "НЕОНОВАЯ МАСКА", "МИНИМАЛИЗМ", "КАКОЙ СТИЛЬ НЕ КРИНЖ?", "Выбираем без дипломатии 😈"),
    ("КОГДА ПОШЁЛ В ДИНОСЬЮТЕ", "ПЛАН: СТАТЬ ЛЕГЕНДОЙ", "РЕАЛЬНОСТЬ: ДВЕРНОЙ ПРОЁМ", "БОСС-ФАЙТ", "Кто знает эту боль? 😂"),
    ("КВАДРОБИКА: ВЫБИРАЙ", "КРАСИВЫЙ ПРЫЖОК", "СМЕШНОЕ ПРИЗЕМЛЕНИЕ", "ЧТО ЧАЩЕ В РЕКОМЕНДАЦИЯХ?", "Без травм, конечно 😅"),
    ("ДИНОСЬЮТЫ И РЕАЛЬНОСТЬ", "ВЫГЛЯДЕТЬ ГРОЗНО", "НЕ УМЕТЬ ПОВЕРНУТЬСЯ", "ОДНА ИСТОРИЯ, ДВА КАДРА", "У кого так было? 🦖"),
    ("ПРОВЕРКА НА ХАЙП", "ДОРОГОЙ КОСТЮМ", "ИДЕЯ ЗА 0 РУБЛЕЙ", "ЧТО НАБЕРЁТ МИЛЛИОН?", "Ставлю на неожиданный ответ"),
    ("БИТВА КОНТЕНТА", "ИДЕАЛЬНЫЙ МОНТАЖ", "СЛУЧАЙНЫЙ МЕМ", "КТО УКРАДЁТ ТРЕНДЫ?", "Алгоритмы, объяснитесь 😭"),
    ("ОБСУЖДЕНИЕ НЕДЕЛИ", "ТЕРРИАНСКИЕ МАСКИ", "ДИНОЗАВРЫ В ТОЛПЕ", "ЧТО ЭПИЧНЕЕ ВЖИВУЮ?", "Вот тут будет спор 🔥"),
    ("РЕАЛЬНОСТЬ БЛОГЕРА", "100 ЛАЙКОВ ЗА ОБРАЗ", "1000 ЗА НЕУДАЧНЫЙ ДУБЛЬ", "ПОЧЕМУ, ИНТЕРНЕТ?", "У кого знакомо? 🤨"),
    ("ВЫХОДИМ НА СЛОЖНЫЙ УРОВЕНЬ", "СДЕЛАТЬ МАСКУ", "СНЯТЬ С НЕЙ ВИРУСНЫЙ РОЛИК", "НАСТОЯЩИЙ БОСС", "Что сложнее?"),
    ("КТО ТУТ ГЛАВНЫЙ?", "ХАРИЗМА В ОБРАЗЕ", "КРУТОЙ КОСТЮМ", "ЧТО РЕШАЕТ?", "Спорим без банальностей 👀"),
    ("ИНТЕРНЕТ В ДВУХ СЛОВАХ", "СВОЯ ТУСОВКА", "ЧУЖИЕ КОММЕНТАРИИ", "ГДЕ БОЛЬШЕ ДРАМЫ?", "Читаем комментарии как сериал 🍿"),
    ("ВАЖНЫЙ ОПРОС", "СМЕШНОЙ ДИНОСЬЮТ", "СЕРЬЁЗНЫЙ ДИНОСЬЮТ", "КАКОЙ НУЖЕН В ЧАТЕ?", "За кого топишь?"),
    ("КАК ПОНЯТЬ ЧТО ЭТО ТРЕНД", "СНАЧАЛА СМЕЯЛИСЬ", "ПОТОМ ПОВТОРЯЮТ", "ИНТЕРНЕТ НИКОГДА НЕ МЕНЯЕТСЯ", "Бывало? 😈"),
    ("СТИЛЬ ПРОТИВ ХАЙПА", "КРУТАЯ ФОТОСЕССИЯ", "СМЕШНОЙ ЗАКУЛИСНЫЙ КАДР", "ЧТО ПОСТИТЬ?", "Вот и решайте 🔥"),
    ("БИТВА ТУСОВОК", "ЛЮБИТЕЛИ МАСОК", "ЛЮБИТЕЛИ ДИНОСЬЮТОВ", "КТО УСТРОИТ ЛУЧШИЙ ФЛЕШМОБ?", "Каждый может проголосовать"),
    ("СКАЗАЛ, ЧТО НЕ БУДЕШЬ СНИМАТЬ", "ОДИН ДУБЛЬ", "ДВАДЦАТЬ ПЯТЬ ДУБЛЕЙ", "ПРОШЛО ТРИ ЧАСА", "Ой, ну случайно 😂"),
    ("БАТТЛ ЭСТЕТИКИ", "ЛЕСНАЯ ЛИСА", "НЕОНОВЫЙ ДИНОЗАВР", "КТО ЗАБЕРЁТ ВАШ ЛАЙК?", "Дайте огня в реакциях 🔥"),
    ("ЧТО СИЛЬНЕЕ?", "МОДНЫЙ ТРЕНД", "СВОЙ СТРАННЫЙ СТИЛЬ", "ПОБЕДИТЕЛЬ ВЫБРАН?", "Не всем зайдёт этот ответ 😈"),
    ("СЛОЖНЕЙШИЙ ВЫБОР", "КРАСИВАЯ МАСКА", "МЕМНЫЙ КОСТЮМ", "НА ЧТО ПОТРАТИТЬ БЮДЖЕТ?", "Кто выбирает хаос? 😂"),
]
PALETTES = [
    ((14, 20, 42), (23, 15, 55), (247, 82, 123), (57, 216, 180)),
    ((18, 18, 30), (43, 19, 44), (255, 107, 67), (105, 184, 255)),
    ((13, 25, 40), (24, 26, 42), (255, 195, 52), (167, 109, 247)),
    ((29, 17, 37), (15, 26, 45), (255, 98, 196), (61, 220, 222)),
]


def font(size):
    return ImageFont.truetype(FONT, size)


def fit_text(draw, text, max_width, max_size, min_size=32):
    for size in range(max_size, min_size-1, -2):
        f = font(size)
        if draw.textbbox((0, 0), text, font=f)[2] <= max_width:
            return f
    return font(min_size)


def center(draw, y, text, f, fill, stroke=0, stroke_fill="#101322"):
    bbox = draw.textbbox((0, 0), text, font=f, stroke_width=stroke)
    width = bbox[2] - bbox[0]
    draw.text(((W-width)/2, y), text, font=f, fill=fill,
              stroke_width=stroke, stroke_fill=stroke_fill)


def fox(draw, cx, cy, rad, tone):
    # Original geometric fox, not a borrowed photo or logo.
    draw.ellipse((cx-rad, cy-rad, cx+rad, cy+rad), fill=(41, 35, 64))
    draw.polygon([(cx-rad*0.77, cy-rad*.16), (cx-rad*.92, cy-rad*.86),
                  (cx-rad*.17, cy-rad*.58)], fill=tone)
    draw.polygon([(cx+rad*.77, cy-rad*.16), (cx+rad*.92, cy-rad*.86),
                  (cx+rad*.17, cy-rad*.58)], fill=tone)
    draw.polygon([(cx-rad*.7, cy-rad*.3), (cx, cy-rad*.56),
                  (cx+rad*.7, cy-rad*.3), (cx+rad*.66, cy+rad*.42),
                  (cx, cy+rad*.83), (cx-rad*.66, cy+rad*.42)], fill=tone)
    draw.polygon([(cx-rad*.38, cy+rad*.2), (cx, cy+rad*.83), (cx+rad*.38, cy+rad*.2)],
                 fill=(242, 235, 235))
    draw.ellipse((cx-rad*.36, cy-rad*.05, cx-rad*.16, cy+rad*.10), fill=(17, 22, 39))
    draw.ellipse((cx+rad*.16, cy-rad*.05, cx+rad*.36, cy+rad*.10), fill=(17, 22, 39))
    draw.ellipse((cx-rad*.09, cy+rad*.4, cx+rad*.09, cy+rad*.57), fill=(17, 22, 39))


def dino(draw, cx, cy, rad, tone):
    draw.ellipse((cx-rad, cy-rad, cx+rad, cy+rad), fill=(41, 35, 64))
    draw.polygon([(cx-rad*.72, cy-rad*.47),(cx-rad*.48,cy-rad*.98),
                  (cx-rad*.19,cy-rad*.54),(cx+rad*.08,cy-rad*.98),
                  (cx+rad*.31,cy-rad*.42),(cx+rad*.57,cy-rad*.74),
                  (cx+rad*.61,cy+rad*.22)], fill=(66, 119, 84))
    draw.ellipse((cx-rad*.64,cy-rad*.5,cx+rad*.71,cy+rad*.72),fill=tone)
    draw.ellipse((cx-rad*.25,cy-rad*.08,cx-rad*.08,cy+rad*.1),fill=(15, 31, 34))
    draw.ellipse((cx+rad*.19,cy-rad*.08,cx+rad*.36,cy+rad*.1),fill=(15, 31, 34))
    draw.arc((cx-rad*.24,cy+rad*.08,cx+rad*.5,cy+rad*.46),0,180,fill=(13,40,34),width=8)
    draw.ellipse((cx+rad*.52,cy+rad*.21,cx+rad*.64,cy+rad*.3),fill=(30,94,69))


def render_meme(entry, index):
    header, left, right, footer, prompt = entry
    upper, lower, a, b = PALETTES[index % len(PALETTES)]
    im = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(im)
    for y in range(H):
        t = y / H
        draw.line((0, y, W, y), fill=tuple(int(upper[i]*(1-t)+lower[i]*t) for i in range(3)))
    rand = random.Random(5001+index)
    for _ in range(42):
        x = rand.randint(0, W)
        y = rand.randint(0, H)
        r = rand.randint(2, 10)
        draw.ellipse((x-r, y-r, x+r, y+r), outline=(65, 60, 97), width=2)
    draw.rounded_rectangle((65, 75, W-65, 220), radius=37, fill=(38, 40, 66))
    center(draw, 114, header, fit_text(draw,header,W-195,58), (244,244,248))
    fox(draw, 300, 530, 195, a)
    dino(draw, 780, 530, 195, b)
    draw.rounded_rectangle((460, 490, 620, 570),radius=28,fill=(245,247,253))
    center(draw, 507, "VS", font(45), (28, 28, 50))
    draw.rounded_rectangle((86, 760, 520, 942), radius=30, fill=(43, 42, 70))
    draw.rounded_rectangle((560, 760, 994, 942), radius=30, fill=(43, 42, 70))
    for label, cx, fg in [(left, 303, a), (right, 778, b)]:
        words = label.split()
        lines = []
        current = ""
        for word in words:
            candidate = (current + " " + word).strip()
            if draw.textbbox((0,0),candidate,font=font(42))[2] <= 385:
                current = candidate
            else:
                if current: lines.append(current)
                current = word
        if current: lines.append(current)
        lines=lines[:3]
        starty=785+max(0,(3-len(lines))*20)
        for k,line in enumerate(lines):
            fs=fit_text(draw,line,390,42)
            bbox=draw.textbbox((0,0),line,font=fs)
            draw.text((cx-(bbox[2]-bbox[0])/2,starty+k*54),line,font=fs,fill=fg)
    draw.rounded_rectangle((82, 1020, W-82, 1206), radius=39, fill=(241, 242, 245))
    footer_font=fit_text(draw, footer, 840, 59, 27)
    center(draw, 1073, footer, footer_font, (25, 26, 46))
    center(draw, 1258, "THERIANS  ×  DINOSUITS", font(28), (160,171,195))
    return im, prompt


def post_meme(state, dry_run=False, force=False):
    used = set(state.get("meme_used", []))
    available = [(i, entry) for i, entry in enumerate(MEMES) if str(i) not in used]
    if not available:
        print("NO_NEW_ORIGINAL_MEMES")
        return False
    # Alternate versions without repeating, not the same image every 15 minutes.
    index, entry = random.choice(available)
    print("MEME_SELECTED", index, entry[0], "available", len(available))
    if dry_run:
        print("MEME_DRY_RUN_OK")
        return True
    target = bot.telegram_send("getChat", data={"chat_id":bot.CHAT_ID})
    if target.get("type") not in ("group","supergroup"):
        raise RuntimeError("Refusing to publish outside the group")
    im, prompt = render_meme(entry, index)
    with tempfile.TemporaryDirectory(prefix="dino-meme-") as tmp:
        path = Path(tmp) / "meme.jpg"
        im.save(path, "JPEG", quality=89)
        with path.open("rb") as fp:
            result=bot.telegram_send(
                "sendPhoto",
                data={"chat_id":bot.CHAT_ID,"caption":prompt},
                files={"photo":("meme.jpg",fp,"image/jpeg")},
            )
    if not result.get("message_id"):
        raise RuntimeError("Telegram did not confirm meme upload")
    state.setdefault("meme_used", []).append(str(index))
    state["meme_used"] = state["meme_used"][-100:]
    print("MEME_POSTED_OK",result["message_id"],index)
    return True


def scheduled_meme(state, now, dry_run=False):
    # 6 meme windows/day (~1 every 2h) preserves chat conversation.
    # On remaining runs, video search is still the first choice.
    if now.hour not in (9, 11, 13, 15, 18, 21) or now.minute >= 15:
        return False
    return post_meme(state, dry_run=dry_run)
