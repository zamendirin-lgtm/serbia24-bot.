"""Historical editorial audit of accessible public Serbia24 posts (no Telegram posting).

Batch Groq review rates *readability/internal consistency*, not independent
truth. Only texts recovered from the channel are counted as audited.
Unreviewed posts have a null score; never silently assign them 8/10.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import time
import requests

INPUT = Path("reports/serbia24_published_posts.json")
OUTPUT = Path("reports/serbia24_editorial_audit.json")
SUMMARY = Path("reports/serbia24_editorial_audit.md")

SYSTEM = """Ты строгий редактор русского новостного канала. Оцени ТЕКУЩИЙ
опубликованный текст каждого поста, не переписывая, от 0 до 10.
Цель 8/10, завышать нельзя. Не оценивай только по длине.

Пять критериев, каждый от 0 до 2:
- clarity: понятность неспециалисту, термины объяснены;
- completeness: понятны главные обстоятельства, конкретная новость не оборвана;
- russian: естественный русский, без машинного перевода, бюрократии и сербизмов;
- headline: заголовок интригует, но точно соответствует содержанию;
- logic: внутренняя последовательность, не путает план и факт, не смешивает
  разные сроки или действующих лиц.

Калибровка (ОЦЕНКИ СТРОГИЕ):
- «парламент был проточным котлом» без объяснения — до 4/10;
- «активировал платёжный документ», без объяснения долга — до 5/10;
- «перевели инспектора», если в тексте лишь проверка перед переводом — до 4/10;
- «национальные пенсии» без объяснения, что за выплаты — до 6/10;
- ясные факты, конкретные суммы и контекст, хорошая русская формулировка —
  обычно 8/10 и выше.
- Сербский текст вместо русского — до 2/10.

Это только оценка НАПИСАННОГО: без первоисточника нельзя подтверждать
фактическую достоверность. Не придумывай фактов. Отдельно отметь
«needs_source_check», если заметна возможная фактическая ошибка.
Пост с установленным заголовком «Channel created» не оценивай.
Не включай в оценку служебную ссылку-закреп.

Верни только JSON: {"reviews":[
  {"id":7, "scores":{"clarity":0,"completeness":0,"russian":0,
    "headline":0,"logic":0}, "issues":["короткая проблема"],
   "needs_source_check":false}
]}.
Для каждого поданного id — ровно один результат. Все оценки — целые 0..2.
Нет гарантий фактической проверки."""
KEYS = ("clarity","completeness","russian","headline","logic")


def review_batch(posts: list[dict], key: str) -> list[dict]:
    payload = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {"role":"system","content":SYSTEM},
            {"role":"user","content":json.dumps({
                "channel":"Serbia24","posts":[
                    {"id":p["id"],"text":p["text"][:1250]} for p in posts
                ]
            }, ensure_ascii=False)},
        ],
        "temperature":0.1,
        "max_completion_tokens":1900,
        "response_format":{"type":"json_object"},
        "reasoning_effort":"low",
        "include_reasoning":False,
        "stream":False,
    }
    for attempt in range(3):
        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization":f"Bearer {key}"},
                json=payload,timeout=35,
            )
            if response.status_code==429:
                delay=min(35,int(response.headers.get("retry-after","12"))+2)
                print("Groq audit rate limit; retrying after delay",delay)
                time.sleep(delay)
                continue
            if response.status_code!=200:
                print("Audit API returned status", response.status_code,
                      "(body withheld)")
                return []
            result=response.json()
            raw=result["choices"][0]["message"]["content"]
            parsed=json.loads(raw)
            reviews=parsed.get("reviews",[])
            if not isinstance(reviews,list):
                return []
            expected={x["id"] for x in posts}
            clean=[]
            for r in reviews:
                if not isinstance(r,dict) or r.get("id") not in expected:
                    continue
                scores=r.get("scores")
                if (not isinstance(scores,dict) or set(scores)!=set(KEYS)
                    or any(type(scores[x]) is not int or
                           not 0<=scores[x]<=2 for x in KEYS)):
                    continue
                issues=r.get("issues")
                if not isinstance(issues,list):
                    issues=[]
                clean.append({
                    "id":r["id"],"scores":scores,"score":sum(scores.values()),
                    "issues":[str(i)[:150] for i in issues[:3]],
                    "needs_source_check":bool(r.get("needs_source_check",False)),
                })
            return clean
        except (requests.RequestException,ValueError,KeyError,TypeError) as exc:
            print("Audit API exception",type(exc).__name__)
            time.sleep(2+attempt*4)
    return []


def main() -> None:
    all_posts=json.loads(INPUT.read_text(encoding="utf-8"))["posts"]
    news=[p for p in all_posts if p["id"] not in (1,9) and
          len(p.get("text","").strip())>=80]
    token=os.getenv("GROQ_API_KEY","").strip()
    if not token:
        print("No Groq key available; cannot score historical posts")
        raise RuntimeError("GROQ_API_KEY not configured")
    reviews=[]
    for start in range(0,len(news),4):
        batch=news[start:start+4]
        scored=review_batch(batch,token)
        reviews.extend(scored)
        print(f"Historical batch {start//4+1}:",len(scored),"/",len(batch),"scored")
        time.sleep(3)
    index={r["id"]:r for r in reviews}
    records=[]
    for p in news:
        grade=index.get(p["id"])
        records.append({
            "id":p["id"],"url":p["url"],"published":p["published"],
            "source_url":p.get("source_url",""),
            "headline":" ".join(p["text"].splitlines()[:2])[:180],
            "text_length":len(p["text"]),
            "score":grade["score"] if grade else None,
            "scores":grade["scores"] if grade else None,
            "issues":grade["issues"] if grade else ["Оценить не удалось: модель/API не ответили"],
            "needs_source_check":grade["needs_source_check"] if grade else True,
        })
    values=[r["score"] for r in records if r["score"] is not None]
    report={
        "created_at":datetime.now(timezone.utc).isoformat(),
        "scope":"Public posts accessible from Telegram preview at time of retrieval",
        "limitation":"Scores judge clarity, structure and internal consistency; factual claims NOT independently checked against each source.",
        "accessible_news_posts":len(news),
        "scored_posts":len(values),
        "not_scored":len(news)-len(values),
        "below_8":sum(x<8 for x in values),
        "at_least_8":sum(x>=8 for x in values),
        "average_score":round(sum(values)/len(values),2) if values else None,
        "records":records,
    }
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    summary=[
        "# Serbia24: аудит качества опубликованных новостей",
        "",
        f"Дата проверки: {report['created_at'][:16]} UTC.",
        f"Доступно новостей: **{len(news)}**. Оценены: **{len(values)}**.",
        f"Оценка ниже 8/10: **{report['below_8']}**, 8/10 и выше: **{report['at_least_8']}**.",
        f"Средняя оценка: **{report['average_score'] if values else 'не установлена'}/10**.",
        "",
        "**Ограничение:** оценки текста моделью — ориентир для редактуры, "
        "не независимая проверка фактов первоисточника. "
        "Недоступные/удалённые посты не оценены.",
        "",
        "| № | Балл | Краткая причина | Ссылка |",
        "| --- | ---: | --- | --- |",
    ]
    for p in records:
        issues="; ".join(p["issues"]).replace("|","/").replace("\n"," ")[:220]
        summary.append(
            f"| {p['id']} | {p['score'] if p['score'] is not None else '—'} | "
            f"{issues or 'Замечаний нет'} | [Пост]({p['url']}) |"
        )
    SUMMARY.write_text("\n".join(summary)+"\n",encoding="utf8")
    print("FINAL COVERAGE:",len(values),"/",len(news),
          "score<8:",report["below_8"],"average:",report["average_score"])
    print("FIRST QUALITY ISSUES:")
    for p in sorted((p for p in records if p["score"] is not None),
                    key=lambda x:x["score"])[:14]:
        print(f"#{p['id']} {p['score']}/10:", "; ".join(p["issues"])[:200])


if __name__=="__main__":
    main()
