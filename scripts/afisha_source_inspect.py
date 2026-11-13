"""Minimal source structure inspection; read-only and robots-aware."""
import requests, re
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
UA="Serbia24Afisha/1.0 (+https://github.com/zamendirin-lgtm/serbia24-bot.)"
SITES=["https://visitsubotica.rs/manifestacije/","https://www.old.serbia.travel/kalendar"]
s=requests.Session()
s.headers.update({"User-Agent":UA})
for url in SITES:
    print("URL "+url)
    try:
        p=urlparse(url); r=s.get(p.scheme+"://"+p.netloc+"/robots.txt",timeout=14)
        if not r.ok:print("no robots");continue
        robots=RobotFileParser();robots.parse(r.text.splitlines())
        if not robots.can_fetch(UA,url):print("robots disallow");continue
        resp=s.get(url,timeout=20)
        resp.raise_for_status()
        resp.encoding=resp.apparent_encoding if not resp.encoding or resp.encoding.lower()=="iso-8859-1" else resp.encoding
        soup=BeautifulSoup(resp.text,"html.parser")
        print("status 200 bytes "+str(len(resp.content)))
        if "visitsubotica" in url:
            for a in soup.select('a[href*="/events/"]'):
                t=a.get_text(" ",strip=True)
                if "Desir" in t or "Фестивал" in t or "Winterfest" in t:
                    print("ANCHOR "+str(a)[:450])
                    curr=a
                    for i in range(5):
                        curr=curr.parent if curr else None
                        if not curr:break
                        print("UP "+str(i)+" "+str(curr)[:1600].replace("\n"," "))
                    if "Desir" in t:break
            for el in soup.find_all(string=re.compile("17.11.2026"))[:3]:
                print("DATE_NODE "+str(el.parent.parent)[:1000])
        else:
            for a in soup.select("a[href]"):
                href=a.get("href","")
                if any(v in href for v in ("/dogadjaj/","/events/","/manifestacija/")):
                    print("EVENT_LINK "+href+" label="+a.get_text(" ",strip=True)[:130])
                    if len(href)>200:break
            print("events-word-count "+str(soup.get_text(" ",strip=True).lower().count("2026")))
            print("event-cards "+str(len(soup.select(".event,.events,.event-item,.manifestacija"))))
    except Exception as e:
        print("ERR "+type(e).__name__)
