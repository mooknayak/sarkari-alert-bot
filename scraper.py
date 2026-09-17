# scraper.py
# Websites se naye posts nikaalna, category/vacancy pehchaanna, aur
# "Apply Online" link dhoondhna - ab pehle se zyada tarikon se.

import re
import io
import time
import base64
import requests
from bs4 import BeautifulSoup
import feedparser

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

# 🆕 Scanned/image-based PDF ko page-by-page photo (image) mein badalne ke
# liye - iske bina hum aisi PDF ka text kabhi nahi nikaal paate (jisme
# koi text-layer hi nahi hota, sirf scan ki hui photo hoti hai)
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from PIL import Image
except ImportError:
    Image = None

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


# ============================================================================
# Notice page ke andar jaakar POORA readable text nikaalta hai - taaki AI ko
# sirf title nahi, balki poori jaankari (dates, eligibility, fee, vacancy
# breakup) mil sake aur woh ek professional, complete post likh sake.
# ============================================================================

MAX_FULL_TEXT_CHARS = 6000  # AI ko dene ke liye itna kaafi hai, zyada bhejna dhima/mehenga hota hai


def fetch_full_details(notice_url):
    """
    Notice/detail page kholkar uska saaf-suthra text nikaalta hai - script,
    style, nav, footer jaisी cheezein hata di jaati hain taaki sirf asli
    content bache. Kuch bhi galat ho jaaye (site down, block, timeout), to
    khaali string deta hai - isse poora bot kabhi nahi rukta, sirf us ek
    post ke liye AI ko kam jaankari milegi.
    """
    try:
        response = requests.get(notice_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Non-content tags hata do - yeh AI ke liye sirf noise hain
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        full_text = "\n".join(lines)

        return full_text[:MAX_FULL_TEXT_CHARS]

    except Exception as e:
        print(f"[ERROR] Full details nikaalte waqt dikkat ({notice_url}): {e}")
        return ""


# ============================================================================
# 🌟 SABSE ZAROORI HISSA: ASLI "OFFICIAL NOTIFICATION" dhoondhna aur padhna
#
# Ek insaan editor jo karta hai, bot bhi bilkul wahi karega:
#   1) Notice/listing page kholna
#   2) Us page par jo bhi "Official Notification / अधिसूचना" jaisa link
#      diya ho, use kholna - chahe wo doosre department ki apni site
#      par jaaye
#   3) Wahan jo bhi mile - PDF ho, ek photo/scan ho, ya seedha ek
#      normal page ho - sabko sahi tarike se padhna
#   4) Agar PDF scanned nikle (jisme text-layer hi na ho), to usse
#      bhi photo mein badal kar padhne layak banana
#
# Yeh poora kaam kai "suraksha raundon" mein bata hai (neeche har round
# alag se comment kiya gaya hai) - kisi ek round mein kuch bhi गड़बड़ हो,
# to sirf wahi hissa khaali reh jaata hai, poora bot KABHI crash nahi
# hota.
# ============================================================================

MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024   # PDF/photo, dono ke liye same size-limit
MAX_PDF_TEXT_CHARS = 10000
MAX_PDF_PAGES = 15                        # bahut lambi PDF mein sirf shuru ke itne page kaafi hote hain
MIN_TEXT_FOR_SKIP_VISION = 300            # itna text mil jaaye to photo/scan padhne ki zaroorat nahi
MAX_IMAGES_TO_COLLECT = 3                 # AI ko ek saath zyada se zyada itni hi photo bhejenge

NOTIFICATION_KEYWORDS = [
    "notification", "advertisement", "detailed notification", "advt",
    "official notification", "notice", "full advertisement", "click here",
    "view notification", "download notification", "official website",
    "सूचना", "अधिसूचना", "विज्ञापन", "भर्ती सूचना", "नोटिस", "पूरी सूचना", "देखें",
]

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def _absolute_url(href, base_page_url):
    if href.startswith("/"):
        base = "/".join(base_page_url.split("/")[:3])
        return base + href
    return href


def find_notification_link(notice_url, html=None):
    """
    Notice page ke andar se ASLI "Official Notification" wala link
    dhoondhta hai - PDF ho, photo ho, ya kisi doosre department ki
    normal page ho, teeno tarah ke link pehchaanta hai.

    Return: (absolute_url ya None, kind) jahan kind in
    {"pdf", "image", "page", None}
    """
    try:
        if html is None:
            response = requests.get(notice_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            html = response.text
        soup = BeautifulSoup(html, "html.parser")

        candidates = []  # (url, kind, matched_keyword)
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith("#") or href.lower().startswith("javascript:"):
                continue
            href = _absolute_url(href, notice_url)
            if not href.startswith("http"):
                continue

            href_lower = href.lower()
            link_text = a.get_text(strip=True).lower()

            if href_lower.endswith(".pdf"):
                kind = "pdf"
            elif href_lower.endswith(IMAGE_EXTENSIONS):
                kind = "image"
            else:
                kind = "page"

            matched = any(kw.lower() in link_text or kw.lower() in href_lower for kw in NOTIFICATION_KEYWORDS)
            candidates.append((href, kind, matched))

        # Round 1 - sabse bharosemand: keyword-match wali PDF
        for href, kind, matched in candidates:
            if matched and kind == "pdf":
                return href, "pdf"

        # Round 2 - keyword-match wali photo/image
        for href, kind, matched in candidates:
            if matched and kind == "image":
                return href, "image"

        # Round 3 - keyword-match wala normal page (jaise doosre
        # department ki apni site ka link) - isse aage ek hop aur
        # jaakar wahan se asli PDF/photo dhoondhi jaayegi
        for href, kind, matched in candidates:
            if matched and kind == "page":
                return href, "page"

        # Fallback - koi keyword match nahi mila, to page ki pehli PDF le lo
        for href, kind, matched in candidates:
            if kind == "pdf":
                return href, "pdf"

        return None, None

    except Exception as e:
        print(f"[ERROR] Notification link dhoondhte waqt dikkat ({notice_url}): {e}")
        return None, None


def download_file(url):
    """
    Kisi bhi file (PDF ya photo) ko download karta hai, size-limit ke
    saath. Kabhi crash nahi karta - dikkat aaye to (None, "") deta hai.
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=45, stream=True)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")

        content = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            content.extend(chunk)
            if len(content) > MAX_FILE_SIZE_BYTES:
                print(f"[CHETAVANI] File bahut badi hai (15MB se zyada), chhod rahe hain: {url}")
                return None, ""

        return bytes(content), content_type
    except Exception as e:
        print(f"[ERROR] File download karte waqt dikkat ({url}): {e}")
        return None, ""


def extract_pdf_text(pdf_bytes):
    """PDF bytes se text nikaalta hai (agar text-layer maujood ho)."""
    if PdfReader is None:
        print("[CHETAVANI] pypdf library install nahi hai - requirements.txt check karein")
        return ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text_parts = []
        for page in reader.pages[:MAX_PDF_PAGES]:
            try:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            except Exception:
                continue  # is ek page mein dikkat ho to agle page par badh jao
        return "\n".join(text_parts).strip()[:MAX_PDF_TEXT_CHARS]
    except Exception as e:
        print(f"[ERROR] PDF se text nikaalte waqt dikkat: {e}")
        return ""


def _compress_image_for_ai(image_bytes, max_dimension=1600, quality=85):
    """
    AI ko bhejne se pehle photo ko chhota/compress karta hai - taaki
    upload tez ho aur AI ka token-cost kam rahe. Pillow na ho ya kuch
    galat ho jaaye, to original bytes hi de deta hai (kabhi crash nahi).
    """
    if Image is None:
        return image_bytes
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("RGB")
        img.thumbnail((max_dimension, max_dimension))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()
    except Exception:
        return image_bytes


def render_pdf_pages_as_images(pdf_bytes, max_pages=3):
    """
    Scanned/image-based PDF (jisme text-layer bilkul nahi hota) ko
    page-by-page photo mein badalta hai - taaki AI use photo ki tarah
    "dekh" kar padh sake. PyMuPDF (fitz) na ho ya kuch bhi galat ho
    jaaye, to khaali list deta hai (poora pipeline chalta rehta hai).
    """
    if fitz is None:
        print("[CHETAVANI] PyMuPDF (fitz) install nahi hai - scanned PDF photo mein nahi badli ja sakegi")
        return []
    images = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page_index in range(min(max_pages, len(doc))):
            try:
                page = doc.load_page(page_index)
                # 2x zoom - taaki chhote/dhundhle text bhi AI ko saaf dikhe
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                png_bytes = pix.tobytes("png")
                images.append(_compress_image_for_ai(png_bytes))
            except Exception:
                continue  # is ek page mein dikkat ho to agle page par badh jao
        doc.close()
    except Exception as e:
        print(f"[ERROR] PDF ko photo mein badalte waqt dikkat: {e}")
        return []
    return images


def fetch_notification_bundle(notice_url):
    """
    🌟 MASTER FUNCTION - main.py/test_one_post.py isi ko istemal karte hain.

    Notice page se shuru karke, asli "Official Notification" tak pahunchta
    hai (chahe woh isi page par ho ya ek hop door kisi doosre department
    ki site par), aur wahan jo bhi mile - PDF, photo, ya normal page -
    sabko sahi tarike se padh kar ek "bundle" (text + photos) taiyaar
    karta hai, jo seedha AI ko diya ja sakta hai.

    Return: {"text": str, "images": [bytes, ...], "notification_url": str|None}

    SURAKSHA: har round apne alag try/except mein hai (upar ke functions
    mein) - koi ek step fail ho to bhi baaki poora function chalta rehta
    hai, kabhi crash nahi hoga.
    """
    bundle = {"text": "", "images": [], "notification_url": None}

    # ---------- Round 1: listing/notice page ka apna text ----------
    page_text = fetch_full_details(notice_url)
    text_parts = []
    if page_text:
        text_parts.append("=== NOTICE PAGE (SUMMARY) ===\n" + page_text)

    # ---------- Round 2: page ke andar "Official Notification" link dhoondhna ----------
    link, kind = find_notification_link(notice_url)

    # Agar link ek normal page nikla (doosre department ki site jaisa),
    # to ek hop aur jaakar WAHAN se asli PDF/photo dhoondhte hain -
    # zyada aage nahi jaate (infinite loop se bachne ke liye sirf 1 hop)
    if kind == "page" and link:
        bundle["notification_url"] = link
        deeper_page_text = fetch_full_details(link)
        if deeper_page_text:
            text_parts.append("=== OFFICIAL DEPARTMENT PAGE ===\n" + deeper_page_text)
        deeper_link, deeper_kind = find_notification_link(link)
        if deeper_link:
            link, kind = deeper_link, deeper_kind

    # ---------- Round 3: jo bhi asli file mili (PDF ya photo), use padhna ----------
    if kind == "pdf" and link:
        bundle["notification_url"] = link
        pdf_bytes, _ = download_file(link)
        if pdf_bytes:
            pdf_text = extract_pdf_text(pdf_bytes)
            if pdf_text and len(pdf_text) >= MIN_TEXT_FOR_SKIP_VISION:
                text_parts.insert(0, "=== OFFICIAL NOTIFICATION PDF (SABSE ZAROORI) ===\n" + pdf_text)
            else:
                # Text bahut kam mila - matlab yeh SCANNED PDF ho sakti hai,
                # isliye photo mein badal kar AI ko "dikhate" hain
                print(f"    [PDF] Bahut kam text mila (scanned ho sakti hai) - photo mein badal rahe hain: {link}")
                if pdf_text:
                    text_parts.insert(0, "=== OFFICIAL NOTIFICATION PDF (ANSHIK TEXT) ===\n" + pdf_text)
                bundle["images"].extend(render_pdf_pages_as_images(pdf_bytes)[:MAX_IMAGES_TO_COLLECT])

    elif kind == "image" and link:
        bundle["notification_url"] = link
        img_bytes, content_type = download_file(link)
        if img_bytes and (content_type.startswith("image/") or link.lower().endswith(IMAGE_EXTENSIONS)):
            bundle["images"].append(_compress_image_for_ai(img_bytes))
        elif img_bytes:
            print(f"    [CHETAVANI] Link image jaisa laga par Content-Type match nahi hua, chhod rahe hain: {link}")

    bundle["text"] = "\n\n".join(text_parts)[:MAX_FULL_TEXT_CHARS + MAX_PDF_TEXT_CHARS]
    return bundle


# 🔧 Purane naam se bhi kaam chale (backward-compatible) - agar kahin
# purana code isi function ko istemal kar raha ho to bhi na tute
def fetch_full_details_with_pdf(notice_url):
    return fetch_notification_bundle(notice_url)["text"]
