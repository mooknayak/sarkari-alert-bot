# portal_fetch.py
# 🆕 NAYI FILE
#
# Private job portals (Sarkari Result, Free Job Alert, Sarkari Exam jaisi) ko
# padhne ke KAI tareeke, ek ke baad ek, jab tak koi chal na jaye:
#   1) RSS / feed   (sabse halka - aksar bot-suraksha se bachta hai)
#   2) Seedha HTML page
#   3) Sitemap (nayi posts ke link + lastmod)
#   4) Reader-service (r.jina.ai) - doosre server se page padhwana
#
# Jo tareeka chala, uska naam METHOD_USED[department] mein rakha jaata hai,
# taaki Telegram report mein dikhe ki har site kaise padhi gayi.

import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urldefrag, urljoin

import requests

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml,application/xml,text/xml,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "hi-IN,hi;q=0.9,en-US;q=0.8,en;q=0.7",
}

METHOD_USED = {}          # {"Free Job Alert": "RSS /feed/", ...}

FEED_PATHS = ["/feed/", "/rss", "/rss.xml", "/feed", "/feeds/posts/default?alt=rss", "/atom.xml"]
SITEMAP_PATHS = ["/sitemap.xml", "/post-sitemap.xml", "/wp-sitemap-posts-post-1.xml", "/sitemap_index.xml"]
MAX_ENTRIES = 60
TIME_BUDGET_SECONDS = 100


def _get(url, timeout=12):
    try:
        return requests.get(url, headers=HEADERS, timeout=timeout)
    except requests.exceptions.SSLError:
        return requests.get(url, headers=HEADERS, timeout=timeout, verify=False)


def _tag(el):
    return el.tag.split("}")[-1].lower()


def parse_feed(content):
    """RSS 2.0 / Atom dono se [(title, link)] nikalta hai. Feed na ho to []."""
    try:
        root = ET.fromstring(content)
    except Exception:
        return []
    items = []
    for el in root.iter():
        if _tag(el) not in ("item", "entry"):
            continue
        title = link = None
        for ch in el:
            t = _tag(ch)
            if t == "title":
                title = " ".join((ch.text or "").split())
            elif t == "link":
                href = (ch.get("href") or ch.text or "").strip()
                if href and (link is None or ch.get("rel") in (None, "alternate")):
                    link = href
        if title and link and link.startswith("http"):
            items.append((title, link))
    return items


def parse_sitemap(content):
    """[(kind, loc, lastmod)] - kind 'url' ya 'sitemap' (index ke andar)."""
    try:
        root = ET.fromstring(content)
    except Exception:
        return []
    out = []
    for el in root.iter():
        kind = _tag(el)
        if kind not in ("url", "sitemap"):
            continue
        loc = lastmod = None
        for ch in el:
            t = _tag(ch)
            if t == "loc":
                loc = (ch.text or "").strip()
            elif t == "lastmod":
                lastmod = (ch.text or "").strip()
        if loc:
            out.append((kind, loc, lastmod or ""))
    return out


def _slug_title(url):
    parts = [p for p in urlparse(url).path.split("/") if p]
    if not parts:
        return ""
    slug = re.sub(r"\.(html?|php|aspx?)$", "", parts[-1], flags=re.I)
    title = re.sub(r"[-_]+", " ", slug).strip()
    return "" if title.replace(" ", "").isdigit() else title


def _origin(url):
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _entries(department, pairs, limit=MAX_ENTRIES):
    seen, out = set(), []
    for title, link in pairs:
        link = urldefrag(link)[0]
        if link in seen or not title:
            continue
        seen.add(link)
        out.append({"department": department, "title": title, "link": link})
        if len(out) >= limit:
            break
    return out


def fetch_portal(source):
    from scraper import fetch_scrape, is_relevant_link   # (late import - circular se bachne ke liye)

    dept = source["department"]
    base = _origin(source["url"])
    deadline = time.monotonic() + TIME_BUDGET_SECONDS
    errors = []

    # ---- 1) RSS / feed ----
    for u in list(source.get("feeds", [])) + [base + p for p in FEED_PATHS]:
        if time.monotonic() > deadline:
            break
        try:
            r = _get(u, timeout=10)
            if r.status_code != 200:
                errors.append(f"feed {urlparse(u).path or '/'}: {r.status_code}")
                continue
            items = parse_feed(r.content)
            if items:
                METHOD_USED[dept] = f"RSS {urlparse(u).path or u}"
                return _entries(dept, items)
        except Exception as e:
            errors.append(f"feed: {type(e).__name__}")

    # ---- 2) seedha HTML ----
    if time.monotonic() < deadline:
        try:
            entries = fetch_scrape(source, retries=1)
            if entries:
                METHOD_USED[dept] = "HTML"
                return entries[:MAX_ENTRIES]
            errors.append("html: 0 relevant links")
        except Exception as e:
            errors.append(f"html: {str(e)[:60]}")

    # ---- 3) sitemap ----
    for path in SITEMAP_PATHS:
        if time.monotonic() > deadline:
            break
        try:
            r = _get(base + path, timeout=12)
            if r.status_code != 200:
                continue
            nodes = parse_sitemap(r.content)
            urls = [n for n in nodes if n[0] == "url"]
            if not urls:
                subs = [n for n in nodes if n[0] == "sitemap"]
                posty = [n for n in subs if "post" in n[1].lower()] or subs
                posty.sort(key=lambda n: n[2], reverse=True)
                for sub in posty[:2]:
                    rs = _get(sub[1], timeout=12)
                    if rs.status_code == 200:
                        urls += [n for n in parse_sitemap(rs.content) if n[0] == "url"]
            if urls:
                urls.sort(key=lambda n: n[2], reverse=True)
                pairs = [(_slug_title(n[1]), n[1]) for n in urls[:200]]
                pairs = [(t, l) for t, l in pairs if t and is_relevant_link(t)]
                if pairs:
                    METHOD_USED[dept] = f"Sitemap {path}"
                    return _entries(dept, pairs)
        except Exception as e:
            errors.append(f"sitemap: {type(e).__name__}")

    # ---- 4) reader-service ----
    if time.monotonic() < deadline + 40:
        try:
            r = _get("https://r.jina.ai/" + source["url"], timeout=40)
            if r.status_code == 200:
                host = urlparse(source["url"]).hostname or ""
                pairs = [
                    (t.strip(), l) for t, l in
                    re.findall(r"(?<!!)\[([^\]\n]{8,200})\]\((https?://[^)\s]+)\)", r.text)
                    if (urlparse(l).hostname or "").endswith(host.replace("www.", ""))
                    and is_relevant_link(t)
                ]
                if pairs:
                    METHOD_USED[dept] = "Reader"
                    return _entries(dept, pairs)
                errors.append("reader: 0 relevant links")
            else:
                errors.append(f"reader: {r.status_code}")
        except Exception as e:
            errors.append(f"reader: {type(e).__name__}")

    raise Exception("सभी तरीके फेल: " + "; ".join(errors[-5:]))
