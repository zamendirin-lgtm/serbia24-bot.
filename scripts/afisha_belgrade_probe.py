"""Read-only DOM/robots probe for reliable Belgrade events discovery."""
from __future__ import annotations
from urllib.robotparser import RobotFileParser
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests
import json

UA="Serbia24Afisha/1.0 (+https://github.com/zamendirin-lgtm/serbia24-bot.)"
PAGES=[
 "https://www.serbia.travel/sr-lat/beograd/",
 "https://www.runbgd.com/whats-on",
]
for url in PAGES:
    root=url.split("/",3)[:3]
    base="/".join(root)
    print("CHECK "+url)
    try:
        robots=requests.get(base+"/robots.txt",headers={"User-Agent":UA},timeout=15)
        rp=RobotFileParser()
        if robots.status_code != 200:
            print("robots unavailable: "+str(robots.status_code));continue
        rp.parse(robots.text.splitlines())
        if not rp.can_fetch(UA,url):
            print("ROBOTS_BLOCKED");continue
        r=requests.get(url,headers={"User-Agent":UA},timeout=20)
        print("STATUS "+str(r.status_code)+" bytes "+str(len(r.content)))
        if not r.ok:continue
        soup=BeautifulSoup(r.text,"html.parser")
        print("PAGE "+soup.title.get_text(" ",strip=True)[:100] if soup.title else "no title")
        for heading in soup.select("h2, h3, h4")[:12]:
            if any(v in heading.get_text(" ",strip=True).lower() for v in ("urlа","maraton","sajam","tribute","prekret","dogad","upcoming","manifestac","etno","furniture","event")):
                print("H: "+str(heading)[:650])
                x=heading
                for i in range(3):
                    x=x.parent
                    if x is None:break
                    print("ANCESTOR: "+str(x)[:1300])
        for a in soup.select("a[href]"):
            text=a.get_text(" ",strip=True)
            if any(w in text.lower() for w in ("etno hrane","beogradski polumaraton","urlaona","tribute maraton","prekret")):
                print("LINK: "+str(a)[:700])
        for t in soup.select('script[type="application/ld+json"]')[:2]:
            print("SCHEMA: "+(t.string or t.text or "")[:550])
    except Exception as e:
        print("FAIL type "+type(e).__name__)
