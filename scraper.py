# scraper.py
# Websites se naye posts nikaalna, category/vacancy pehchaanna, aur
# "Apply Online" link dhoondhna - ab pehle se zyada tarikon se.

import re
import io
import time
import requests
from bs4 import BeautifulSoup
import feedparser

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from pdf2image import convert_from_bytes
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

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


# ============================================================================
# 🆕 NAYA FUNCTION: Sanity ke jobPost.status field ke liye BHAROSEMAND
# tareeka - AI se guess karwane ke bajaye, hum khud keyword-match se
# pehchante hain (bilkul detect_category() jaisa). Isse "hamesha job hi
# ban jaata hai" wali samasya khatam ho jaati hai, kyunki yeh kabhi AI
# ki 'confidence' par nirbhar nahi karta - seedha title mein shabd
# dhoondhta hai.
# ============================================================================
STATUS_KEYWORDS = [
    # (Sanity status value, keywords - jo pehle match ho wahi jeetega,
    #  isliye zyada specific/khaas status pehle rakhe gaye hain)
    ("final_selection", [
        "final selection", "final result", "merit list", "selection list",
        "अंतिम चयन", "चयन सूची", "मेरिट लिस्ट", "अंतिम परिणाम",
    ]),
    ("result", [
        "result", "cut off", "cut-off", "scorecard", "score card",
        "परिणाम", "रिजल्ट", "कट ऑफ",
    ]),
    ("answer_key", [
        "answer key", "objection", "उत्तर कुंजी", "आंसर की", "आपत्ति",
    ]),
    ("admit_card", [
        "admit card", "hall ticket", "call letter", "e-admit",
        "प्रवेश पत्र", "एडमिट कार्ड", "हॉल टिकट",
    ]),
    ("job", [
        "recruitment", "vacancy", "notification", "bharti", "apply online",
        "भर्ती", "अधिसूचना", "आवेदन",
    ]),
]


def detect_status(title):
    """Title mein keyword dhoondh kar Sanity ka 'status' value deta hai.
    Kuch na mile to 'job' (sabse aam case) deta hai. Yeh AI se PEHLE
    chalaya jaata hai aur AI ko ek "bharosemand hint" ke roop mein diya
    jaata hai - isse status kabhi bhi sirf AI ke andaze par nirbhar
    nahi karta."""
    title_lower = (title or "").lower()
    for status, keywords in STATUS_KEYWORDS:
        for kw in keywords:
            if kw.lower() in title_lower:
                return status
    return "job"


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
# 🆕 NAYA FUNCTION: Notice page ke andar jaakar POORA readable text nikaalta
# hai - taaki AI ko sirf title nahi, balki poori jaankari (dates, eligibility,
# fee, vacancy breakup) mil sake aur woh ek professional, complete post
# likh sake. Yeh Sanity-publishing wale naye pipeline (sanity_publisher.py)
# ke liye banaya gaya hai - Telegram wale purane flow par iska koi asar
# nahi padta.
# ============================================================================

MAX_FULL_TEXT_CHARS = 6000  # AI ko dene ke liye itna kaafi hai, zyada bhejna dhima/mehenga hota hai


def fetch_page_title(notice_url):
    """
    🆕 SABSE ZAROORI SURAKSHA: Chahe poora page/PDF fetch fail ho jaaye
    (site block kar de, timeout ho, PDF na mile), yeh function sirf
    page ka <title> tag padhne ki koshish karta hai - yeh sabse halka,
    sabse tez, aur lagbhag hamesha kaam karne wala tareeka hai, isliye
    AI ke paas kabhi bhi 100% khaali jaankari nahi jaati.

    Kuch bhi galat ho to khaali string deta hai (kabhi crash nahi karta).
    """
    try:
        response = requests.get(notice_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        if soup.title and soup.title.string:
            return soup.title.string.strip()
    except Exception as e:
        print(f"[ERROR] Page ka <title> nikaalte waqt dikkat ({notice_url}): {e}")
    return ""


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
# 🆕 NAYA HISSA (SABSE ZAROORI): OFFICIAL NOTIFICATION PDF padhna
#
# Ab tak bot sirf notice ki chhoti "listing page" padhta tha - jismein
# aksar sirf title aur 2-4 line ki summary hoti hai. Isi wajah se AI ke
# paas eligibility, fee, dates, syllabus jaisi detail hoti hi nahi thi
# to woh khaali/adhoore fields chhod deta tha.
#
# Ab bot bilkul waisa hi karega jaisa ek INSAAN editor karta hai: page
# se "Official Notification" wali PDF dhoondhega, use download karke
# poora padhega, aur usi se AI ko poori, asli jaankari milegi - isse
# Sanity ke sabhi fields (Eligibility, Fee, Dates, How to Apply) sahi
# se bharne lagenge.
# ============================================================================

MAX_PDF_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB se badi PDF download nahi karenge
MAX_PDF_TEXT_CHARS = 10000
MAX_PDF_PAGES = 15  # bahut lambi PDF mein sirf shuru ke itne page kaafi hote hain

NOTIFICATION_PDF_KEYWORDS = [
    "notification", "advertisement", "detailed notification", "advt",
    "official notification", "notice", "full advertisement",
    "सूचना", "अधिसूचना", "विज्ञापन", "भर्ती सूचना", "नोटिस",
]

# 🆕 Kai sarkari websites do alag PDF dikhati hain: ek chhoti "Short
# Notice" aur ek badi "Detailed/Full Notification" - dono mein ALAG
# jaankari hoti hai (Short Notice mein jaldi wali summary, Full mein
# eligibility/fee/syllabus ka poora detail). Ab dono dhoondh kar dono
# padhte hain.
FULL_NOTICE_KEYWORDS = [
    "detailed notification", "full notification", "full advertisement",
    "detailed advertisement", "विस्तृत सूचना", "विस्तृत विज्ञापन", "पूर्ण विज्ञापन",
]
SHORT_NOTICE_KEYWORDS = [
    "short notice", "short notification", "लघु सूचना", "संक्षिप्त सूचना",
]


def find_notification_pdf_link(notice_url):
    """
    Notice page ke andar se OFFICIAL PDF notification ka link dhoondhta
    hai - jahan asli, poori detail (eligibility, fee, dates, syllabus)
    likhi hoti hai, na ki sirf 2-4 line ki summary.

    Pehle keyword-match wala PDF link dhoondhta hai (jaise "Notification"
    ya "अधिसूचना" likha ho), na mile to page ka PEHLA .pdf link le leta
    hai - kyunki zyadatar sarkari notice page par sirf EK hi PDF hoti hai,
    aur woh aksar wahi asli notification hoti hai.
    """
    try:
        response = requests.get(notice_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        soup = BeautifulSoup(response.text, "html.parser")

        pdf_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if ".pdf" not in href.lower():
                continue
            if href.startswith("/"):
                base = "/".join(notice_url.split("/")[:3])
                href = base + href
            if not href.startswith("http"):
                continue
            link_text = a.get_text(strip=True).lower()
            pdf_links.append((href, link_text))

        if not pdf_links:
            return None

        # Pehla tareeka: keyword se match karne wala PDF (sabse bharosemand)
        for href, link_text in pdf_links:
            if any(kw.lower() in link_text or kw.lower() in href.lower() for kw in NOTIFICATION_PDF_KEYWORDS):
                return href

        # Doosra tareeka (fallback): page ka pehla PDF hi le lo
        return pdf_links[0][0]

    except Exception as e:
        print(f"[ERROR] PDF link dhoondhte waqt dikkat ({notice_url}): {e}")
        return None


def find_all_notification_pdf_links(notice_url):
    """
    🆕 EK nahi, DO tarah ki official PDF dhoondhta hai - "Short Notice"
    aur "Full/Detailed Notification" - kyunki kai sarkari websites
    dono alag-alag PDF dikhati hain, aur dono mein ALAG jaankari hoti
    hai (Short Notice mein jaldi wali summary, Full mein poora detail -
    eligibility, fee, syllabus). Jo bhi mile, sabko return karta hai
    (as list of (label, url) tuples) - taaki dono padhi ja sakein.

    Agar sirf EK hi PDF mile (zyadatar aisa hi hota hai), to sirf wahi
    ek deta hai - koi crash ya error nahi.
    """
    try:
        response = requests.get(notice_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        soup = BeautifulSoup(response.text, "html.parser")

        pdf_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if ".pdf" not in href.lower():
                continue
            if href.startswith("/"):
                base = "/".join(notice_url.split("/")[:3])
                href = base + href
            if not href.startswith("http"):
                continue
            link_text = a.get_text(strip=True).lower()
            pdf_links.append((href, link_text))

        if not pdf_links:
            return []

        full_link = None
        short_link = None
        generic_link = None

        for href, link_text in pdf_links:
            combined = f"{link_text} {href.lower()}"
            if not full_link and any(kw.lower() in combined for kw in FULL_NOTICE_KEYWORDS):
                full_link = href
            elif not short_link and any(kw.lower() in combined for kw in SHORT_NOTICE_KEYWORDS):
                short_link = href
            elif not generic_link and any(kw.lower() in combined for kw in NOTIFICATION_PDF_KEYWORDS):
                generic_link = href

        result = []
        if full_link:
            result.append(("Full/Detailed Notification", full_link))
        elif generic_link:
            result.append(("Official Notification", generic_link))

        if short_link and short_link not in [u for _, u in result]:
            result.append(("Short Notice", short_link))

        if not result:
            # Koi keyword match nahi hua - page ka pehla PDF hi le lo
            result.append(("Notification", pdf_links[0][0]))

        return result[:2]  # zyada se zyada 2 PDF (dhima na ho jaaye)

    except Exception as e:
        print(f"[ERROR] PDF links dhoondhte waqt dikkat ({notice_url}): {e}")
        return []


MIN_TEXT_LENGTH_BEFORE_OCR = 200  # itne se kam text mile to maan lete hain PDF scanned hai
MAX_OCR_PAGES = 5  # OCR bahut dhima hota hai, isliye sirf shuru ke itne page hi


def _ocr_pdf_text(pdf_bytes):
    """
    🆕 Scanned/Photo-type PDF ke liye - jab PDF ke andar 'text layer'
    hi nahi hota (poori tarah image/scan hoti hai), to normal pypdf
    kuch nahi nikaal paata. Tab yeh function PDF ke pehle kuch pages
    ko TASVEER (image) mein badalta hai, phir usme OCR (Optical
    Character Recognition) se seedha "padhta" hai - bilkul waisa hi
    jaisa koi insaan screenshot dekh kar padhta hai.

    Hindi (Devanagari) aur English dono bhasha ke liye OCR try karta
    hai. Yeh dhima hota hai, isliye sirf shuru ke MAX_OCR_PAGES page
    tak hi karte hain - zyadatar notice ki mool jaankari shuru mein hi
    hoti hai.

    Suraksha: agar OCR library install na ho, ya kisi bhi wajah se
    OCR fail ho jaaye, hamesha khaali string deta hai - kabhi crash
    nahi karta.
    """
    if not OCR_AVAILABLE:
        print("    [OCR] pytesseract/pdf2image install nahi hai - OCR skip kar rahe hain")
        return ""

    try:
        images = convert_from_bytes(pdf_bytes, first_page=1, last_page=MAX_OCR_PAGES)
    except Exception as e:
        print(f"    [OCR] PDF ko tasveer mein badalte waqt dikkat: {e}")
        return ""

    text_parts = []
    for img in images:
        try:
            # 'hin+eng' - Hindi aur English dono padhne ki koshish karega
            page_text = pytesseract.image_to_string(img, lang="hin+eng")
            if page_text:
                text_parts.append(page_text)
        except Exception as e:
            print(f"    [OCR] Ek page padhte waqt dikkat (agle page par badh rahe hain): {e}")
            continue

    return "\n".join(text_parts).strip()


def download_and_extract_pdf_text(pdf_url):
    """
    PDF ko download karke uske andar ka text nikaalta hai.

    🆕 AB DO TAREEKE: Pehle normal text-extraction try karta hai (tez).
    Agar usse bahut kam ya khaali text mile (matlab PDF scanned/photo
    type hai), to khud-ba-khud OCR (image se text padhna) par switch
    ho jaata hai - taaki scanned notice bhi padhi ja sake.

    Suraksha: agar PdfReader library na ho, PDF 15MB se badi ho, dono
    tareeke (normal + OCR) fail ho jaayein, ya kuch bhi galat ho jaaye
    - to hamesha khaali string ("") deta hai. Isse aage ka poora
    pipeline KABHI nahi rukta, bas PDF wali extra jaankari us ek post
    ke liye nahi milegi (page-text se hi kaam chal jaayega).
    """
    if PdfReader is None:
        print("[CHETAVANI] pypdf library install nahi hai - requirements.txt check karein")
        return ""

    try:
        response = requests.get(pdf_url, headers=HEADERS, timeout=45, stream=True)
        response.raise_for_status()

        content = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            content.extend(chunk)
            if len(content) > MAX_PDF_SIZE_BYTES:
                print(f"[CHETAVANI] PDF bahut badi hai (15MB se zyada), chhod rahe hain: {pdf_url}")
                return ""

        pdf_bytes = bytes(content)

        # ---------- TAREEKA 1: Normal text-extraction (tez) ----------
        full_text = ""
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
            full_text = "\n".join(text_parts).strip()
        except Exception as e:
            print(f"    [PDF] Normal text-extraction fail hui: {e}")

        # ---------- TAREEKA 2: OCR (agar tareeka 1 se kaam na bana) ----------
        if len(full_text) < MIN_TEXT_LENGTH_BEFORE_OCR:
            print("    [PDF] Bahut kam text mila - shayad scanned/photo PDF hai, OCR try kar rahe hain...")
            ocr_text = _ocr_pdf_text(pdf_bytes)
            if len(ocr_text) > len(full_text):
                print(f"    [OCR] {len(ocr_text)} characters OCR se mile (normal tareeke se behtar)")
                full_text = ocr_text

        return full_text[:MAX_PDF_TEXT_CHARS]

    except Exception as e:
        print(f"[ERROR] PDF padhte waqt dikkat ({pdf_url}): {e}")
        return ""


def fetch_full_details_with_pdf(notice_url):
    """
    🌟 SABSE BEHTAR TAREEKA - isi ko main.py/test_one_post.py istemal
    karte hain.

    Pehle notice page ka text nikaalta hai (jaisa fetch_full_details()
    karta hai), PHIR usi page se OFFICIAL notification PDF(s) dhoondh
    kar unka poora text bhi nikaalta hai - kyunki PDF mein hi asli,
    poori jaankari (eligibility, fee, dates, syllabus, how to apply)
    hoti hai jo chhoti listing page par nahi hoti.

    🆕 AB DO PDF TAK PADHI JAATI HAIN (agar dono maujood hon) - "Short
    Notice" aur "Full/Detailed Notification" - kyunki inme alag-alag
    jaankari ho sakti hai. Jo bhi milein, sabko AI ko dete hain.
    """
    page_text = fetch_full_details(notice_url)

    pdf_sections = []
    pdf_links = find_all_notification_pdf_links(notice_url)
    for label, pdf_link in pdf_links:
        print(f"    [PDF] {label} mili: {pdf_link}")
        pdf_text = download_and_extract_pdf_text(pdf_link)
        if pdf_text:
            print(f"    [PDF] {label}: {len(pdf_text)} characters text nikala gaya")
            pdf_sections.append((label, pdf_text))
        else:
            print(f"    [PDF] {label}: text nahi nikal paaya (shayad scanned/image PDF hai)")

    if pdf_sections:
        combined = "\n\n".join(
            f"=== {label.upper()} (PDF SE - SABSE ZAROORI) ===\n{text}"
            for label, text in pdf_sections
        )
        return f"{combined}\n\n=== NOTICE PAGE SUMMARY (ADDITIONAL CONTEXT) ===\n{page_text}"

    return page_text
