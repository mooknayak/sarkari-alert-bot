# official_links.py
# 🆕 NAYI FILE
#
# Kisi bhi post-page (Sarkari Result, Free Job Alert, ya seedha koi sarkari
# site) ke andar se ASLI aadhikarik (government / NIC) links nikalta hai:
#   - Apply Online
#   - Download Admit Card
#   - Check Result / Answer Key
#   - Official Notification (aksar PDF)
#   - Official Website
#
# Soch yeh hai: us page par jo link "Apply Online" ke saamne laga hai, wahi
# link hamari post ke "Important Links" mein jaye - us private site ka
# apna link kabhi nahi.
#
# Yeh file kabhi crash nahi karti - kuch bhi galat ho to khaali result deti hai.

import os
import re
from urllib.parse import urljoin, urlparse, urldefrag, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "hi-IN,hi;q=0.9,en-US;q=0.8,en;q=0.7",
}
TIMEOUT = 20

# ---------------------------------------------------------------------------
# Kaun sa domain "aadhikarik" maana jaye
# ---------------------------------------------------------------------------
OFFICIAL_SUFFIXES = (
    ".gov.in", ".nic.in", ".ac.in", ".edu.in", ".res.in", ".mil.in",
    ".bank.in", ".fin.in",   # bank/vitt sansthaon ke liye sarkari-niyantrit domain
)

# Jo sarkari sansthayein .gov.in/.nic.in par nahi hain, par asli hain.
# Zaroorat ho to yahan ya Variables mein OFFICIAL_EXTRA_DOMAINS (comma se
# alag) jod sakte hain.
OFFICIAL_EXACT_DOMAINS = {
    "ibps.in", "sbi.co.in", "rbi.org.in", "licindia.in", "aiims.edu",
    "uppcl.org", "uphesc.org", "upsssc.gov.in", "nta.ac.in", "nbe.edu.in",
    "epfindia.gov.in", "ncs.gov.in", "digilocker.gov.in",
    # Sarkari company/bank jo .gov.in par nahi hain (zaroorat ho to aur jodein,
    # ya Variables mein OFFICIAL_EXTRA_DOMAINS likhein)
    "ntpc.co.in", "sail.co.in", "bhel.com", "ongcindia.com", "iocl.com",
    "gailonline.com", "coalindia.in", "powergrid.in", "hal-india.co.in",
    "bel-india.in", "bsnl.co.in", "nhpcindia.com", "irctc.co.in",
    "nabard.org", "pnbindia.in",
}
_extra = os.environ.get("OFFICIAL_EXTRA_DOMAINS", "")
OFFICIAL_EXACT_DOMAINS |= {d.strip().lower() for d in _extra.split(",") if d.strip()}

# In sites ke apne links hum KABHI "aadhikarik" nahi maante
AGGREGATOR_DOMAINS = {
    "sarkariresult.com", "sarkariresult.com.cm", "freejobalert.com",
    "sarkariexam.com", "sarkarijobfind.com", "amarujala.com",
    "rojgarresult.com", "sarkarinaukriblog.com", "jagranjosh.com",
    "adda247.com", "testbook.com", "careers360.com", "indiatoday.in",
    "timesofindia.indiatimes.com", "livehindustan.com",
}
SOCIAL_DOMAINS = {
    "t.me", "telegram.me", "telegram.org", "whatsapp.com", "wa.me",
    "facebook.com", "fb.com", "fb.me", "instagram.com", "twitter.com",
    "x.com", "youtube.com", "youtu.be", "play.google.com", "apps.apple.com",
    "linkedin.com", "pinterest.com", "google.com", "gstatic.com",
}
# Chhote/redirect wale links - inhe khol kar asli pata nikalte hain
SHORTENER_DOMAINS = {
    "bit.ly", "tinyurl.com", "goo.gl", "cutt.ly", "rb.gy", "t.co", "is.gd",
    "shorturl.at", "ow.ly", "bitly.com", "tiny.cc", "rebrand.ly",
}
REDIRECT_PARAMS = ("url", "u", "link", "redirect", "target", "goto", "r", "q")


def _host(url):
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _host_in(host, domains):
    return any(host == d or host.endswith("." + d) for d in domains)


def is_official_host(host):
    host = (host or "").lower()
    if not host:
        return False
    if host.endswith(OFFICIAL_SUFFIXES):
        return True
    return _host_in(host, OFFICIAL_EXACT_DOMAINS)


def is_official_url(url):
    return is_official_host(_host(url))


def is_aggregator_url(url):
    return _host_in(_host(url), AGGREGATOR_DOMAINS)


def official_root(url):
    """Kisi bhi aadhikarik link se uski main website (home) nikalta hai,
    jaise https://recruit.upsc.gov.in/x/y -> https://upsc.gov.in"""
    host = _host(url)
    if not host:
        return None
    for d in OFFICIAL_EXACT_DOMAINS:
        if host == d or host.endswith("." + d):
            return f"https://{d}"
    for suf in OFFICIAL_SUFFIXES:
        if host.endswith(suf):
            labels = host.split(".")
            n = len(suf.strip(".").split("."))
            root = ".".join(labels[-(n + 1):])
            return f"https://{root}"
    return f"https://{host}"


# ---------------------------------------------------------------------------
# Page fetch (chhota in-memory cache, taaki ek hi page baar-baar na khule)
# ---------------------------------------------------------------------------
_PAGE_CACHE = {}


def _get(url, **kw):
    try:
        return requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kw)
    except requests.exceptions.SSLError:
        # Kai bhartiya sarkari sites ki certificate chain adhoori hoti hai;
        # sirf padhne ke liye verify band karke dobara koshish
        return requests.get(url, headers=HEADERS, timeout=TIMEOUT, verify=False, **kw)


def _fetch_html(url):
    if url in _PAGE_CACHE:
        return _PAGE_CACHE[url]
    r = _get(url)
    r.raise_for_status()
    if len(_PAGE_CACHE) > 64:
        _PAGE_CACHE.clear()
    _PAGE_CACHE[url] = (r.content, r.url)
    return _PAGE_CACHE[url]


# ---------------------------------------------------------------------------
# Links nikalna (text + aas-paas ka label dono)
# ---------------------------------------------------------------------------
GENERIC_TEXTS = {
    "click here", "click", "here", "link", "download", "view", "open", "visit",
    "यहाँ क्लिक करें", "यहां क्लिक करें", "क्लिक करें", "डाउनलोड", "देखें",
    "download here", "click here to download", "check here", "get link",
}


def _row_context(a):
    """'Apply Online | Click Here' jaisi table-row ya list-item ka poora text,
    aur us row mein kitne links hain."""
    node = a
    for _ in range(5):
        node = node.parent
        if node is None:
            break
        if node.name in ("tr", "li", "p"):
            text = node.get_text(" ", strip=True)[:200]
            return text, len(node.find_all("a", href=True))
    return "", 1


def extract_anchors(page_url):
    content, base = _fetch_html(page_url)
    soup = BeautifulSoup(content, "html.parser")
    anchors = []
    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absu = urldefrag(urljoin(base, href))[0]
        if not absu.startswith("http"):
            continue
        text = a.get_text(" ", strip=True)
        if not text:
            text = (a.get("title") or a.get("aria-label") or "").strip()
        if not text:
            img = a.find("img")
            if img is not None:
                text = (img.get("alt") or img.get("title") or "").strip()
        ctx, n_links = _row_context(a)
        anchors.append({"text": text, "context": ctx, "row_links": n_links, "url": absu})
    return anchors


def _unwrap(url, budget):
    """Redirect/shortener wale link ka asli pata. budget = [bache hue network
    calls] (list, taaki ghat sake)."""
    try:
        q = parse_qs(urlparse(url).query)
        for key in REDIRECT_PARAMS:
            for val in q.get(key, []):
                val = unquote(val)
                if val.startswith("http"):
                    return val
    except Exception:
        pass
    if _host_in(_host(url), SHORTENER_DOMAINS) and budget[0] > 0:
        budget[0] -= 1
        try:
            r = _get(url, allow_redirects=True, stream=True)
            final = r.url
            r.close()
            return final
        except Exception:
            return url
    return url


# ---------------------------------------------------------------------------
# Link ka prakar pehchanna
# ---------------------------------------------------------------------------
RULES = [
    ("Download Admit Card", [
        "admit card", "hall ticket", "call letter", "e-admit", "admit-card",
        "प्रवेश पत्र", "एडमिट कार्ड", "हॉल टिकट", "कॉल लेटर",
    ]),
    ("Check Result", [
        "result", "score card", "scorecard", "merit list", "cut off", "cut-off",
        "answer key", "परिणाम", "रिजल्ट", "उत्तर कुंजी", "आंसर की", "स्कोर कार्ड",
    ]),
    ("Correction Link", [
        "correction", "edit form", "modify application", "edit application",
        "करेक्शन", "सुधार",
    ]),
    ("Syllabus", ["syllabus", "पाठ्यक्रम", "सिलेबस"]),
    ("Exam City / Status", [
        "exam city", "city intimation", "application status",
        "आवेदन स्थिति", "परीक्षा शहर",
    ]),
    ("Apply Online", [
        "apply online", "apply now", "online application", "online apply",
        "apply here", "click here to apply", "registration", "register",
        "आवेदन", "अप्लाई", "रजिस्ट्रेशन", "पंजीकरण",
    ]),
    ("Candidate Login", ["candidate login", "लॉगिन"]),
    ("Official Notification", [
        "notification", "advertisement", "advt", "notice", "detailed notice",
        "अधिसूचना", "विज्ञापन", "सूचना", "नोटिस",
    ]),
    ("Official Website", [
        "official website", "official site", "आधिकारिक वेबसाइट",
        "ऑफिशियल वेबसाइट", "official web",
    ]),
]
URL_HINTS = [
    ("Download Admit Card", ["admitcard", "admit-card", "hallticket", "call-letter", "callletter"]),
    ("Check Result", ["result", "scorecard", "answerkey", "answer-key"]),
    ("Apply Online", ["apply", "onlineapply", "registration", "recruitment/login"]),
]


def _match(text):
    t = (text or "").lower()
    for ltype, words in RULES:
        if any(w in t for w in words):
            return ltype
    return None


def classify(anchor):
    own = (anchor["text"] or "").strip()
    own_l = own.lower()
    # 1) Link ka apna text
    kind = _match(own_l)
    if kind:
        return kind
    # 2) Text generic ("Click Here") ho to us row ka label
    if (not own_l or own_l in GENERIC_TEXTS) and anchor["context"] and anchor["row_links"] <= 1:
        kind = _match(anchor["context"])
        if kind:
            return kind
    # 3) URL ke andar ke sanket
    path = anchor["url"].lower()
    if path.split("?")[0].endswith(".pdf"):
        return "Official Notification"
    for ltype, hints in URL_HINTS:
        if any(h in path for h in hints):
            return ltype
    return None


# ---------------------------------------------------------------------------
# Mukhya function
# ---------------------------------------------------------------------------
def find_official_links(page_url, max_redirect_calls=10):
    """
    page_url ke andar se aadhikarik links nikalta hai.
    Return:
      {"ok": bool, "page_url": ..., "by_type": {type: {"url","text","official"}},
       "all": [ {"type","url","text","official"} ...], "error": "..."}
    """
    out = {"ok": False, "page_url": page_url, "by_type": {}, "all": []}
    if not page_url or not str(page_url).startswith("http"):
        out["error"] = "page url nahi mila"
        return out
    # Agar link seedha PDF hi hai, to uske andar links dhoondhne ka matlab nahi
    if page_url.lower().split("?")[0].endswith(".pdf"):
        if is_official_url(page_url):
            out["by_type"]["Official Notification"] = {
                "type": "Official Notification", "url": page_url,
                "text": "Official Notification", "official": True,
            }
            root = official_root(page_url)
            if root:
                out["by_type"]["Official Website"] = {
                    "type": "Official Website", "url": root,
                    "text": "Official Website", "official": True,
                }
            out["ok"] = True
        return out

    try:
        anchors = extract_anchors(page_url)
    except Exception as e:
        out["error"] = f"page nahi khula: {e}"
        return out

    own_host = _host(page_url)
    page_is_official = is_official_host(own_host)
    budget = [max_redirect_calls]
    seen = set()
    cands = []

    for a in anchors:
        url = _unwrap(a["url"], budget)
        h = _host(url)
        if not h:
            continue
        # Us private site ke apne (andar ke) links chhod do - par agar page
        # khud sarkari site hai to uske apne links bhi aadhikarik hi hain
        if h == own_host and not page_is_official:
            continue
        if _host_in(h, AGGREGATOR_DOMAINS) or _host_in(h, SOCIAL_DOMAINS):
            continue
        kind = classify({**a, "url": url})
        if not kind or url in seen:
            continue
        seen.add(url)
        cands.append({
            "type": kind, "url": url, "text": a["text"],
            "official": is_official_host(h),
        })

    # Aadhikarik domain pehle, phir page par dikhne ka kram
    cands_sorted = sorted(cands, key=lambda c: (0 if c["official"] else 1))
    out["all"] = cands_sorted

    for c in cands_sorted:
        if c["type"] not in out["by_type"]:
            out["by_type"][c["type"]] = c

    # Official Website: saaf likha na mile to kisi aadhikarik link ka root
    if "Official Website" not in out["by_type"]:
        first_official = next((c for c in cands_sorted if c["official"]), None)
        if first_official:
            root = official_root(first_official["url"])
            if root:
                out["by_type"]["Official Website"] = {
                    "type": "Official Website", "url": root,
                    "text": "Official Website", "official": True,
                }
    out["ok"] = bool(out["by_type"])
    return out


def collect_official_links(source_url, override_url=None):
    """Publish-flow ke liye surakshit wrapper. override_url = aap haath se
    jo aadhikarik page dena chahein (agar pata ho); uske links ko prathmikta."""
    result = {"ok": False, "by_type": {}, "all": [], "page_url": source_url}
    try:
        if source_url and str(source_url).startswith("http"):
            result = find_official_links(source_url)
        if override_url and str(override_url).startswith("http"):
            ov = find_official_links(override_url)
            merged = dict(result.get("by_type", {}))
            merged.update(ov.get("by_type", {}))
            if "Official Notification" not in ov.get("by_type", {}) and \
               "Official Notification" not in merged:
                merged["Official Notification"] = {
                    "type": "Official Notification", "url": override_url,
                    "text": "Official Notification", "official": is_official_url(override_url),
                }
            result["by_type"] = merged
            result["all"] = ov.get("all", []) + result.get("all", [])
            result["ok"] = bool(merged)
    except Exception as e:
        result["error"] = str(e)
    return result


def format_links_block(official):
    """AI ko dene ke liye saaf block - AI sirf inhi URL ko istemal karega."""
    lines = ["=== OFFICIAL LINKS FOUND ON THE PAGE (use ONLY these URLs in \"links\"; never invent a URL) ==="]
    items = official.get("by_type", {}) if official else {}
    if not items:
        lines.append("NONE FOUND - keep \"links\" as an empty list []")
    for ltype, c in items.items():
        lines.append(f"- {ltype}: {c['url']}")
    # Ek se zyada notification PDF ho to dikhao
    extra = [c for c in (official or {}).get("all", [])
             if c["type"] == "Official Notification"
             and c["url"] != items.get("Official Notification", {}).get("url")]
    for c in extra[:2]:
        lines.append(f"- Official Notification (another): {c['url']}")
    return "\n".join(lines)


def find_pdf_links(page_url, limit=2):
    """Page ki aadhikarik-pehle PDF links [(label, url)]."""
    try:
        anchors = extract_anchors(page_url)
    except Exception:
        return []
    pdfs = []
    seen = set()
    for a in anchors:
        if ".pdf" not in a["url"].lower().split("?")[0] and ".pdf" not in a["url"].lower():
            continue
        if a["url"] in seen:
            continue
        seen.add(a["url"])
        pdfs.append(a)
    pdfs.sort(key=lambda a: 0 if is_official_url(a["url"]) else 1)
    return pdfs[:limit * 3]
