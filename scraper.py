# scraper.py
# Yahan hum websites se naye posts nikaalte hain (RSS ya scraping se)
# aur unse Department, Category, Vacancy count nikaalte hain

import re
import requests
from bs4 import BeautifulSoup
import feedparser

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ---------- Category pehchaanne ke keywords ----------
CATEGORIES = {
    "Admit Card": ["admit card", "hall ticket", "prwesh patr", "e-admit"],
    "Result": ["result", "merit list", "final result", "cut off"],
    "Answer Key": ["answer key", "objection"],
    "Apply": ["apply online", "application form", "last date to apply"],
    "Notification": ["recruitment", "vacancy", "notification", "bharti"],
}


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


def fetch_rss(source):
    """RSS feed wali site se naye entries nikalta hai"""
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
    HTML scraping wali site se naye entries nikalta hai.
    NOTE: Har site ka HTML structure alag hota hai, isliye source["selector"]
    ko us site ka asli structure dekh kar set karna hoga (browser mein
    right-click -> Inspect karke element ka class/tag pata chal jaata hai).
    """
    entries = []
    try:
        response = requests.get(source["url"], headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.select(source["selector"])
        for a in links:
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not title or not href:
                continue
            # agar link relative hai (jaise "/notice/123"), use poora banaye
            if href.startswith("/"):
                base = "/".join(source["url"].split("/")[:3])
                href = base + href
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
    if source["type"] == "rss":
        return fetch_rss(source)
    else:
        return fetch_scrape(source)
