# scraper.py
# Yahan hum websites se naye posts nikaalte hain (RSS ya generic scraping se)
# aur unse Department, Category, Vacancy count nikaalte hain
#
# NOTE: Har site ke liye alag CSS selector dhundne ki zaroorat nahi hai.
# "fetch_scrape" function poore page ke sabhi <a> links padh kar khud
# pehchan leta hai ki kaun sa link bharti/result/admit-card se juda hai.

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
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in RELEVANT_KEYWORDS)


def fetch_rss(source):
    """RSS feed wali site se naye entries nikalta hai"""
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
    """
    GENERIC scraper - poore page ke sabhi <a> links padh kar, jo bhi link
    bharti/result/admit-card jaisa lage, use utha leta hai.

    "retries" - agar pehli koshish mein site na khule (jaise timeout ya
    slow server), to thoda ruk kar dobara koshish karta hai. Isse
    temporary network dikkat ki wajah se poori site chhoote jaane se bachta hai.
    """
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
            return entries  # safal hua to yahin se return kar do

        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(5)  # thoda ruk kar dobara koshish

    print(f"[ERROR] {source['department']} ko scrape karne mein dikkat ({retries} koshish ke baad): {last_error}")
    return entries


def fetch_new_posts(source):
    """Source ke type ke hisaab se sahi function bulata hai"""
    if source.get("type") == "rss":
        return fetch_rss(source)
    else:
        return fetch_scrape(source)
