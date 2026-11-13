"""Read-only robots-aware source structure diagnostics for regional Serbia events.

No Telegram access, no publication or photo downloads. Prints small event
snippets so a robust parser can be built from observed public HTML.
"""
import re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

UA="Serbia24Afisha/1.0 (+https://github.com/zamendirin-lgtm/serbia24-bot.)"
URLS=[
 "https://www.serbia.travel/en/event-calendar/",
 "https://www.serbia.travel/sr-lat/kalendar-dogadjaja/",
 "https://visitsubotica.rs/manifestacije/",
]
sess=requests.Session()
sess.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
for url in URLS:
    host=urlparse(url).netloc
    print("SOURCE "+url)
    try:
        robots=sess.get("https://"+host+"/robots.txt",timeout=12)
        print("ROBOTS "+str(robots.status_code))
        if not robots.ok:continue
        rp=RobotFileParser()
        rp.parse(robots.text.splitlines())
        print("CAN_FETCH "+str(rp.can_fetch(UA,url)))
        if not rp.can_fetch(UA,url):continue
        r=sess.get(url,timeout=22)
        print("HTTP "+str(r.status_code)+" length "+str(len(r.content)))
        if not r.ok or len(r.content)>2500000:continue
        r.encoding=r.apparent_encoding if not r.encoding or r.encoding.lower()=="iso-8859-1" else r.encoding
        soup=BeautifulSoup(r.text,"html.parser")
        print("PAGE_TITLE "+(soup.title.get_text(" ",strip=True)[:120] if soup.title else ""))
        possible=soup.find_all(string=re.compile(
            "SAJAM ZIMNICE|SAJAM ETNO|INTERNATIONAL FAIR|Desir|Winterfest|KULINAR|FESTIVAL",re.I))
        count=0
        for el in possible:
            if count>=4:break
            if len(str(el))>200:continue
            parent=el.find_parent(["a","h2","h3","h4","article","div"])
            if not parent:continue
            outer=parent
            for _ in range(3):
                if not outer.parent:break
                if outer.name=="article":break
                outer=outer.parent
            print("MATCH "+str(el).strip()[:120])
            print("NODE "+str(outer)[:2200].replace("\n"," "))
            count+=1
        print("EVENT_LINKS")
        anchors=[]
        for a in soup.select("a[href]"):
            href=a.get("href","")
            if any(v in href for v in ("/events/","/manifestacije/","/dogadjaj","/event/")):
                t=a.get_text(" ",strip=True)
                if t and len(t)>7:
                    anchors.append((href[:140],t[:110]))
        for a in anchors[:8]:
            print("LINK "+str(a))
    except Exception as exc:
        print("FAILED "+type(exc).__name__)
