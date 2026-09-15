# sanity_publisher.py
# 🆕 NAYI FILE
#
# Yeh file 2 kaam karti hai:
#   1) Scrape kiye gaye raw/kaccha text ko Gemini AI se ek saaf-suthra,
#      professional, structured post (JSON) mein badalna.
#   2) Us structured post ko seedha Sanity CMS mein ek DRAFT document ke
#      roop mein save karna - DRAFT isliye taaki woh public website par
#      TURANT NA dikhe. Aap Sanity Studio (aapki-site.com/studio) mein
#      jaakar use padh/edit karke khud "Publish" button dabayenge, tabhi
#      woh live hoga.
#
# Is file ko chalane ke liye Railway ke Variables mein yeh sab set hone
# chahiye: SANITY_PROJECT_ID, SANITY_DATASET, SANITY_API_TOKEN, GEMINI_API_KEY

import re
import json
import hashlib
import requests

from config import (
    SANITY_PROJECT_ID, SANITY_DATASET, SANITY_API_VERSION,
    SANITY_API_TOKEN, GEMINI_API_KEY,
)

SANITY_QUERY_URL = (
    f"https://{SANITY_PROJECT_ID}.api.sanity.io/v{SANITY_API_VERSION}"
    f"/data/query/{SANITY_DATASET}"
)
SANITY_MUTATE_URL = (
    f"https://{SANITY_PROJECT_ID}.api.sanity.io/v{SANITY_API_VERSION}"
    f"/data/mutate/{SANITY_DATASET}"
)

SANITY_HEADERS = {
    "Authorization": f"Bearer {SANITY_API_TOKEN}",
    "Content-Type": "application/json",
}

REQUEST_TIMEOUT = 30

# jobPost schema mein "status" field ke hisaab se category ka title -
# website ke src/sanity/schemaTypes/jobPost.ts se match karta hai
CATEGORY_TITLE_BY_STATUS = {
    "job": "Jobs",
    "admit_card": "Admit Card",
    "answer_key": "Answer Key",
    "result": "Result",
    "final_selection": "Result",
}

VALID_STATUSES = set(CATEGORY_TITLE_BY_STATUS.keys())


# ============================================================================
# HISSA 1: Gemini AI se raw text ko structured JSON mein badalna
# ============================================================================

# Google model naam badalta rehta hai - isliye ek se zyada try karte hain,
# bilkul website ke src/app/api/ask-ai/route.ts jaisa tareeka
GEMINI_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]

PROMPT_TEMPLATE = """Tum "Official Sarkari Patrika" naam ke sarkari naukri suchna portal ke liye ek professional content editor ho. Neeche ek raw/kaccha notice text diya gaya hai. Isse ek saaf, professional, accurate Hindi job-post mein badlo.

SAKHT NIYAM:
- Sirf woh jaankari do jo neeche diye gaye text mein maujood hai ya usse seedha nikaali ja sakti hai. Koi bhi tareekh, sankhya, ya fact khud se mat banao. Agar jaankari na mile to us field mein "जानकारी उपलब्ध नहीं है" likho.
- Professional Hindi bhasha, common English shabd (Apply Online, Admit Card) chalenge.
- Sirf neeche diye JSON format mein jawab do - koi extra text, koi markdown backticks, koi preamble nahi.

JSON FORMAT:
{{
  "title": "poora, spasht post title",
  "status": "job ya admit_card ya answer_key ya result ya final_selection",
  "organization": "vibhag/sanstha ka naam",
  "vacancy": "sirf number ya N/A",
  "eligibility": "shiksha yogyata, age limit",
  "description": "3-6 bullet points, har line ek naya point",
  "importantLinksText": "Label: URL (ek line mein ek link, sirf jo mile)",
  "seoMetaTitle": "60 character tak ka SEO title",
  "seoMetaDescription": "150-160 character tak ka SEO description"
}}

RAW NOTICE TEXT:
\"\"\"
{raw_text}
\"\"\""""


def _call_gemini(prompt, max_tokens=1800):
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY set nahi hai (Railway Variables mein daalein)")

    last_error = "koi model try nahi hua"
    for model in GEMINI_MODELS:
        try:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={GEMINI_API_KEY}"
            )
            resp = requests.post(
                url,
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
                },
                timeout=40,
            )
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and parts[0].get("text"):
                        return parts[0]["text"]
                last_error = "AI se khaali jawab mila"
                continue
            if resp.status_code == 429:
                last_error = f"{model}: rate limit (429)"
                continue
            last_error = f"{model}: {resp.text[:200]}"
        except Exception as e:
            last_error = f"{model}: {e}"

    raise Exception(f"Gemini se jawab nahi mila - {last_error}")


def generate_structured_post(raw_text):
    """Raw scraped text leta hai, Gemini se structured JSON banwa kar
    Python dict return karta hai."""
    prompt = PROMPT_TEMPLATE.format(raw_text=raw_text[:8000])
    raw_response = _call_gemini(prompt)

    cleaned = raw_response.strip()
    cleaned = re.sub(r"^```json", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^```", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise Exception(f"AI ka jawab valid JSON nahi tha: {e}")


# ============================================================================
# HISSA 2: Sanity ke saath baat karna (query + mutate, seedha HTTP API se -
# koi extra npm/pip package ki zaroorat nahi)
# ============================================================================

def _sanity_query(groq, params=None):
    query_params = {"query": groq}
    if params:
        for key, value in params.items():
            query_params[f"${key}"] = json.dumps(value)
    resp = requests.get(SANITY_QUERY_URL, headers=SANITY_HEADERS, params=query_params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("result")


def _sanity_mutate(mutations):
    resp = requests.post(
        SANITY_MUTATE_URL, headers=SANITY_HEADERS,
        json={"mutations": mutations}, timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code >= 300:
        raise Exception(f"Sanity mutation fail (status {resp.status_code}): {resp.text[:300]}")
    return resp.json()


def slugify(text):
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text).strip("-")
    return text[:90] or "post"


def make_unique_slug(title):
    """jobPost.ts schema ka isUnique rule sirf Studio UI mein chalta hai,
    API se likhte waqt nahi - isliye yahan khud check karte hain taaki
    do posts ka slug kabhi takrayein nahi."""
    base = slugify(title)
    slug = base
    counter = 2
    while True:
        existing = _sanity_query(
            'defined(*[_type == "jobPost" && slug.current == $slug][0]._id)',
            {"slug": slug},
        )
        if not existing:
            return slug
        slug = f"{base}-{counter}"
        counter += 1


def get_or_create_organization(name, fallback_website):
    """Organization pehle se ho to uski _id deta hai, warna nayi bana deta
    hai - isse 'UPSC' baar-baar duplicate nahi banega."""
    name = (name or "").strip() or "Sarkari Vibhag"

    existing = _sanity_query(
        '*[_type == "organization" && name == $name][0]._id',
        {"name": name},
    )
    if existing:
        return existing

    org_id = f"org-{hashlib.md5(name.encode()).hexdigest()[:12]}"
    doc = {
        "_id": org_id,
        "_type": "organization",
        "name": name,
        "slug": {"_type": "slug", "current": slugify(name)},
        "website": fallback_website or "https://www.india.gov.in",
    }
    _sanity_mutate([{"createIfNotExists": doc}])
    return org_id


def get_or_create_category(status):
    """Status (job/admit_card/...) ke hisaab se sahi Category document
    dhoondhta ya banata hai."""
    title = CATEGORY_TITLE_BY_STATUS.get(status, "Jobs")

    existing = _sanity_query(
        '*[_type == "category" && title == $title][0]._id',
        {"title": title},
    )
    if existing:
        return existing

    cat_id = f"cat-{slugify(title)}"
    doc = {
        "_id": cat_id,
        "_type": "category",
        "title": title,
        "slug": {"_type": "slug", "current": slugify(title)},
    }
    _sanity_mutate([{"createIfNotExists": doc}])
    return cat_id


def _text_to_blocks(text):
    """Plain text (har line ek point) ko Sanity ke Portable Text block
    format mein badalta hai - jobPost.ts ke 'description' field ke liye."""
    blocks = []
    for line in (text or "").split("\n"):
        line = line.strip().lstrip("-•").strip()
        if not line:
            continue
        blocks.append({
            "_type": "block",
            "style": "normal",
            "children": [{"_type": "span", "text": line}],
        })
    return blocks


def _links_text_to_array(links_text):
    """'Label: URL' format ki lines ko importantLinks array mein badalta hai."""
    links = []
    for line in (links_text or "").split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        label, _, url = line.partition(":")
        url = url.strip()
        if url.lower().startswith("http"):
            links.append({"_type": "object", "label": label.strip(), "url": url})
    return links


def create_draft_job_post(structured, source_link):
    """Structured AI data se ek DRAFT jobPost document Sanity mein banata
    hai. _id 'drafts.' se shuru hota hai - isliye yeh KABHI public website
    par nahi dikhega jab tak Studio mein manually 'Publish' na dabaya jaaye."""

    title = (structured.get("title") or "Untitled Post").strip()
    status = structured.get("status") if structured.get("status") in VALID_STATUSES else "job"

    org_id = get_or_create_organization(structured.get("organization"), source_link)
    cat_id = get_or_create_category(status)
    slug = make_unique_slug(title)

    # Post ki unique id link se banti hai - isse agar bot galti se same
    # link do baar process kar de, to duplicate draft nahi banega
    doc_id = f"drafts.jobpost-{hashlib.md5(source_link.encode()).hexdigest()[:16]}"

    doc = {
        "_id": doc_id,
        "_type": "jobPost",
        "title": title[:150],
        "slug": {"_type": "slug", "current": slug},
        "sourceUrl": source_link,
        "organization": {"_type": "reference", "_ref": org_id},
        "category": {"_type": "reference", "_ref": cat_id},
        "status": status,
        "isNew": True,
        "description": _text_to_blocks(structured.get("description")),
        "importantLinks": _links_text_to_array(structured.get("importantLinksText")),
        "seo": {
            "metaTitle": (structured.get("seoMetaTitle") or title)[:60],
            "metaDescription": (structured.get("seoMetaDescription") or "")[:160],
        },
    }

    vacancy_raw = str(structured.get("vacancy") or "").strip()
    if vacancy_raw.isdigit():
        doc["vacancyDetails"] = [{
            "_type": "object",
            "postName": title[:80],
            "totalPosts": int(vacancy_raw),
            "eligibility": structured.get("eligibility") or "",
        }]

    _sanity_mutate([{"createOrReplace": doc}])
    return {"draftId": doc_id, "slug": slug, "title": title}


# ============================================================================
# ENTRY POINT - main.py isi ek function ko bulata hai
# ============================================================================

def publish_scraped_post(raw_text, source_link):
    """Raw text leta hai -> AI se structure karwaata hai -> Sanity mein
    DRAFT bana deta hai. Koi bhi step fail ho, to exception upar (main.py
    mein) jaake pakdi jaati hai, taaki poora bot na ruke."""
    structured = generate_structured_post(raw_text)
    result = create_draft_job_post(structured, source_link)
    return result
