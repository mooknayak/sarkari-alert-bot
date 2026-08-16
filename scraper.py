# scraper.py
# Yahan hum websites se naye posts nikaalte hain (RSS ya generic scraping se)
# aur unse Department, Category, Vacancy count nikaalte hain
#
# NOTE: Ab har site ke liye alag CSS selector dhundne ki zaroorat nahi hai.
# "fetch_scrape" function poore page ke sabhi <a> links padh kar khud
# pehchan leta hai ki kaun sa link bharti/result/admit-card se juda hai
# (title mein keyword dhoond kar). Isse 50-60 sites jodna bahut aasan ho jata hai
# - bas URL daalna kaafi hai.

import re
import requests
from bs4 import BeautifulSoup
import feedparser

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# ---------- Category pehchaanne ke keywords ----------
CATEGORIES = {
    "Admit Card": ["admit card", "hall ticket", "call letter", "e-admit", "प्रवेश पत्र"],
    "Result": ["result", "merit list", "final result", "cut off", "परिणाम"],
    "Answer Key": ["answer key", "objection", "उत्तर कुंजी"],
    "Apply": ["apply online", "application form", "last date to apply", "आवेदन"],
    "Notification": ["recruitment", "vacancy", "notification", "bharti", "भर्ती", "अधिसूचना"],
}

# Yeh keywords batate hain ki koi link "kaam ka" hai ya nahi
# (generic scraping mein sirf inhi keywords wale links uthaye jaate hain)
RELEVANT_KEYWORDS = [
    "recruitment", "vacancy", "notification", "admit card", "hall ticket",
    "result", "merit", "answer key", "apply online", "advertisement",
    "bharti", "भर्ती", "प्रवेश पत्र", "परिणाम", "अधिसूचना", "आवेदन",
    "cut off", "interview letter", "call letter",
]


def detect_category(title):
    """Title padh kar pehchanta hai ki yeh Notification/Admit Card/Result vagera hai"""
    title_lower = title.lower()
    for category, keywords in CATEGORIES.items():
        for kw in keywords:
            if kw in title_lower:
                return category
    return "General Update"


def extract_vacancy(title):
    """Title se post/vacancy ki sankhya nikalne ki koshish karta hai"""
    match = re.search(r'(\d{2,6})\s*(posts?|vacanc\w*|pad)', title, re.IGNORECASE)
    if match:
        return match.group(1)
    return "N/A"


def is_relevant_link(title):
    """Check karta hai ki yeh link bharti/result/admit-card se related hai ya nahi"""
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in RELEVANT_KEYWORDS)


def fetch_rss(source):
    """RSS feed wali site se naye entries nikalta hai (agar kisi source ki RSS ho)"""
    entries = []
    feed = feedparser.parse(source["url"])
    for item in feed.entries:
        entries.append({
            "department": source["department"],
            "title": item.title,
            "link": item.link,
        })
    return entries


def fetch_scrape(source):
    """
    GENERIC scraper - kisi bhi sarkari website ke poore homepage/notice-page
    ke sabhi <a> links padh kar, jo bhi link bharti/result/admit-card jaisa
    lage (RELEVANT_KEYWORDS ke hisaab se), use utha leta hai.

    Isse har site ke liye alag selector nahi likhna padta - bas URL daalna
    kaafi hai. (Trade-off: kabhi-kabhi kuch faltu/galat links bhi aa sakte
    hain, lekin ismein zyaadatar sahi jaankari mil jaati hai.)
    """
    entries = []
    try:
        response = requests.get(source["url"], headers=HEADERS, timeout=20)
        soup = BeautifulSoup(response.text, "html.parser")

        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            href = a["href"]

            if not title or len(title) < 8:
                continue
            if not is_relevant_link(title):
                continue

            # agar link relative hai (jaise "/notice/123"), use poora banaye
            if href.startswith("/"):
                base = "/".join(source["url"].split("/")[:3])
                href = base + href
            elif not href.startswith("http"):
                continue

            entries.append({
                "department": source["department"],
                "title": title,
                "link": href,
            })
    except Exception as e:
        print(f"[ERROR] {source['department']} ko scrape karne mein dikkat: {e}")

    return entries


def fetch_new_posts(source):
    """Source ke type ke hisaab se sahi function bulata hai"""
    if source.get("type") == "rss":
        return fetch_rss(source)
    else:
        return fetch_scrape(source)
