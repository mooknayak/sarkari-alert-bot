# scraper.py
# Yahan hum websites se naye posts nikaalte hain (RSS ya generic scraping se),
# unse Department, Category, Vacancy count nikaalte hain, aur ab yeh bhi -
# har notice ke andar jaakar "Apply Online" ka seedha link dhoondte hain.

import re
import time
import requests
from bs4 import BeautifulSoup
import feedparser

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

CATEGORIES = {
    "Admit Card": ["admit card", "hall ticket", "call letter", "e-admit", "प्रवेश पत्र"],
    "Result": ["result", "merit list", "final result", "cut off", "परिणाम"],
    "Answer Key": ["answer key", "objection", "उत्तर कुंजी"],
    "Apply": ["apply online", "application form", "last date to apply", "आवेदन"],
    "Notification": ["recruitment", "vacancy", "notification", "bharti", "भर्ती", "अधिसूचना"],
}

RELEVANT_KEYWORDS = [
    "recruitment", "vacancy", "notification", "admit card", "hall ticket",
    "result", "merit", "answer key", "apply online", "advertisement",
    "bharti", "भर्ती", "प्रवेश पत्र", "परिणाम", "अधिसूचना", "आवेदन",
    "cut off", "interview letter", "call letter",
]

# "Apply Online" wale link ko notice-page ke andar dhoondhne ke liye keywords
APPLY_LINK_KEYWORDS = [
    "apply online", "apply now", "online application", "click here to apply",
    "आवेदन करें", "अप्लाई ऑनलाइन", "यहाँ आवेदन करें", "ऑनलाइन आवेदन",
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
    match = re.search(r'(\d{2,6})\s*(posts?|vacanc\w*|pad)', title, re.IGNORECASE)
    if match:
        return match.group(1)
    return "N/A"


def is_relevant_link(title):
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in RELEVANT_KEYWORDS)


def find_apply_link(notice_url):
    """
    Kisi notice/detail page ke andar jaakar "Apply Online" jaisa likha hua
    link dhoondta hai aur uska seedha URL laata hai. Agar na mile, to
    None wapas karta hai (tab hum notice_url hi bata denge).
    """
    try:
        response = requests.get(notice_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")

        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            if any(kw in text for kw in APPLY_LINK_KEYWORDS):
                href = a["href"]
                if href.startswith("/"):
                    base = "/".join(notice_url.split("/")[:3])
                    href = base + href
                if href.startswith("http"):
                    return href
    except Exception as e:
        print(f"[ERROR] Apply link dhoondhte waqt dikkat ({notice_url}): {e}")

    return None


def fetch_rss(source):
    entries = []
    try:
        feed = feedparser.parse(source["url"])
        for item in feed.entries:
            entries.append({
                "department": source["department"],
                "title": item.title,
                "link": item.link,
            })
    except Exception as e:
        print(f"[ERROR] {source['department']} ki RSS padhne mein dikkat: {e}")
    return entries


def fetch_scrape(source, retries=2):
    entries = []
    last_error = None

    for attempt in range(1, retries + 1):
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
            return entries

        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(5)

    print(f"[ERROR] {source['department']} ko scrape karne mein dikkat ({retries} koshish ke baad): {last_error}")
    return entries


def fetch_new_posts(source):
    if source.get("type") == "rss":
        return fetch_rss(source)
    else:
        return fetch_scrape(source)
