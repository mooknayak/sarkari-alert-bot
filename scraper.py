# scraper.py
# Websites se naye posts nikaalna, category/vacancy pehchaanna, aur
# "Apply Online" link dhoondhna - ab pehle se zyada tarikon se.

import re
import time
import requests
from bs4 import BeautifulSoup
import feedparser

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "hi-IN,hi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
WAIT_BETWEEN_RETRIES = 10

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

APPLY_LINK_TEXT_KEYWORDS = [
    "apply online", "apply now", "online application", "click here to apply",
    "आवेदन करें", "अप्लाई ऑनलाइन", "यहाँ आवेदन करें", "ऑनलाइन आवेदन",
]

# Agar link ke TEXT mein "apply" jaisa kuch na mile, to link ke URL
# (href) mein hi "apply"/"online-form" jaisa pattern dhoondte hain -
# kayi sites (jaise sarkariresult.com) button/image ke andar link
# rakhti hain jahan text khaali ya alag hota hai
APPLY_LINK_URL_PATTERNS = ["apply", "application", "online-form", "registration"]

# Jaani-pehchaani vibhagon ke asli official website - agar koi post
# kisi aggregator (Sarkari Result, Free Job Alert, Amar Ujala) se aaye,
# to title padh kar asli vibhag pehchaan kar uski official site batayenge,
# aggregator ki site nahi
KNOWN_DEPARTMENT_SITES = {
    "ssc": "https://ssc.gov.in",
    "upsc": "https://www.upsc.gov.in",
    "ibps": "https://www.ibps.in",
    "rrb": "https://www.rrcb.gov.in",
    "railway": "https://www.rrcb.gov.in",
    "sbi": "https://sbi.co.in",
    "uppsc": "https://uppsc.up.nic.in",
    "upsssc": "https://upsssc.gov.in",
    "up police": "https://uppbpb.gov.in",
    "bpsc": "https://bpsc.bihar.gov.in",
    "mppsc": "https://mppsc.mp.gov.in",
    "rpsc": "https://rpsc.rajasthan.gov.in",
    "aiims": "https://www.aiims.edu",
    "isro": "https://www.isro.gov.in",
    "drdo": "https://www.drdo.gov.in",
    "epfo": "https://www.epfindia.gov.in",
    "indian army": "https://joinindianarmy.nic.in",
    "indian navy": "https://joinindiannavy.gov.in",
    "air force": "https://careerairforce.gov.in",
}


def detect_category(title):
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


def resolve_official_site(title, fallback_url):
    """
    Agar title mein kisi jaani-pehchaani vibhag ka naam mile, to uski
    ASLI official website deta hai (na ki jis aggregator se yeh post
    mila). Agar kuch na mile, to jo source se mila wahi (fallback) dega.
    """
    title_lower = title.lower()
    for keyword, official_url in KNOWN_DEPARTMENT_SITES.items():
        if keyword in title_lower:
            return official_url
    return fallback_url


def find_apply_link(notice_url):
    """
    Notice page ke andar "Apply Online" link dhoondhta hai - pehle link
    ke TEXT mein keyword dhoondhta hai, na mile to link ke URL (href)
    mein bhi "apply" jaisa pattern dhoondhta hai (kayi sites button
    ke andar link chhupati hain, text khaali hota hai).
    """
    try:
        response = requests.get(notice_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        soup = BeautifulSoup(response.text, "html.parser")

        # Pehla tareeka: link ke text mein keyword
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            if any(kw in text for kw in APPLY_LINK_TEXT_KEYWORDS):
                href = a["href"]
                if href.startswith("/"):
                    base = "/".join(notice_url.split("/")[:3])
                    href = base + href
                if href.startswith("http"):
                    return href

        # Doosra tareeka (fallback): link ke URL mein hi pattern
        for a in soup.find_all("a", href=True):
            href_lower = a["href"].lower()
            if any(pat in href_lower for pat in APPLY_LINK_URL_PATTERNS):
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


def fetch_scrape(source, retries=MAX_RETRIES):
    entries = []
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(source["url"], headers=HEADERS, timeout=REQUEST_TIMEOUT)
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
                time.sleep(WAIT_BETWEEN_RETRIES)

    print(f"[ERROR] {source['department']} ko scrape karne mein dikkat ({retries} koshish ke baad): {last_error}")
    raise last_error if last_error else Exception("Unknown scrape error")


def fetch_new_posts(source):
    if source.get("type") == "rss":
        return fetch_rss(source)
    else:
        return fetch_scrape(source)
