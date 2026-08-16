# scraper.py
# Yahan hum websites se naye posts nikaalte hain (RSS ya generic scraping se),
# unse Department, Category, Vacancy count nikaalte hain, aur har notice ke
# andar jaakar "Apply Online" ka seedha link bhi dhoondte hain.
#
# NOTE: Kuch sarkari sites (jaise SSC, UPSC) cloud/datacenter server ke IP
# address hi block kar deti hain - aisi site ke liye koi bhi code-level
# sudhaar 100% guarantee nahi deta. Neeche behtar, asli-browser jaisa
# headers aur zyada retries di gayi hain jo kayi cases mein madad karti hain,
# lekin agar poori tarah IP-block hai to yeh source consistently fail hoga -
# tab bhi baaki 130+ sources aur Amar Ujala/Sarkari Result/Free Job Alert
# jaisi aggregator RSS feeds se wahi jaankari mil jaati hai, isliye kuch
# chootega nahi.

import re
import time
import requests
from bs4 import BeautifulSoup
import feedparser

# Asli Chrome browser jaisa poora header-set - sirf User-Agent nahi,
# poora set bhejne se kayi bot-detection filter paar ho jaate hain
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "hi-IN,hi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}

# Timeout aur retries dono badha diye - genuinely slow site ko poora mauka
# milega, aur bar-baar koshish se temporary dikkat mein bhi kaam ban sakta hai
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
WAIT_BETWEEN_RETRIES = 10  # seconds

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

APPLY_LINK_KEYWORDS = [
    "apply online", "apply now", "online application", "click here to apply",
    "आवेदन करें", "अप्लाई ऑनलाइन", "यहाँ आवेदन करें", "ऑनलाइन आवेदन",
]


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


def find_apply_link(notice_url):
    try:
        response = requests.get(notice_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
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


def fetch_scrape(source, retries=MAX_RETRIES):
    """
    Generic scraper - poore page ke sabhi <a> links padh kar, jo bhi link
    bharti/result/admit-card jaisa lage, use utha leta hai.

    Agar site baar-baar (retries ke baad bhi) connect na ho, to iska matlab
    zyaadatar yeh hota hai ki site ne server ka IP hi block kar rakha hai -
    aisi site consistently fail hogi, code se poori tarah theek nahi ho sakti.
    """
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
    return entries


def fetch_new_posts(source):
    if source.get("type") == "rss":
        return fetch_rss(source)
    else:
        return fetch_scrape(source)
