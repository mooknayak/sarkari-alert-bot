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

import os
import re
import json
import hashlib
import requests

from config import (
    SANITY_PROJECT_ID, SANITY_DATASET, SANITY_API_VERSION,
    SANITY_API_TOKEN, OPENROUTER_API_KEY, GROQ_API_KEY, GEMINI_API_KEY,
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
# HISSA 1: AI se raw text ko structured JSON mein badalna
#
# 🆕 AB DO PROVIDERS: Pehle GROQ try hota hai (tez aur free), agar woh na ho
# ya kisi wajah se fail ho jaaye, to khud-ba-khud GEMINI par switch ho jaata
# hai - isse kisi EK provider ki dikkat se poora system nahi rukta.
# ============================================================================

REQUEST_TIMEOUT_AI = 45

# 🆕 OPENROUTER - AB SABSE PEHLE TRY HOGA (aasaan sign-up ke liye):
# console.groq.com par account banane mein dikkat aa rahi thi, isliye
# OpenRouter jodा gaya - yahan koi phone-verification nahi maangi jaati,
# Google/GitHub se seedha sign-up ho jaata hai, aur "free" model list
# rotate hoti rehti hai isiliye yahan bhi LIVE list mangwate hain (kabhi
# band ho chuka model try nahi hoga)
_openrouter_models_cache = None

# Groq apne models samay-samay par retire karta rehta hai (jaise
# llama-3.3-70b-versatile 16 August 2026 ko band ho gaya) - isliye yahan
# bhi ek se zyada model try karte hain, sabse achhe se shuru karke
GROQ_MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.6-27b", "openai/gpt-oss-20b", "llama-3.1-8b-instant"]

# Gemini ke model naam bhi badalte rehte hain - isliye hardcoded list ki
# jagah har baar Google se LIVE list mangwate hain (jo bhi model us waqt
# available ho, wahi use hoga - kabhi purana/band naam istemal nahi hoga)
_gemini_models_cache = None


def _get_openrouter_models():
    """OpenRouter se LIVE free-model list mangwata hai (cache karke) -
    kyunki free models ki list समय-समय पर badalti rehti hai."""
    global _openrouter_models_cache
    if _openrouter_models_cache:
        return _openrouter_models_cache

    resp = requests.get("https://openrouter.ai/api/v1/models", timeout=REQUEST_TIMEOUT_AI)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    free_models = [m["id"] for m in data if m.get("id", "").endswith(":free")]
    if not free_models:
        raise Exception("Koi free model nahi mila")

    # Bade, achhe reasoning wale models pehle try karo
    priority_keywords = ["gpt-oss-120b", "llama-3.3-70b", "gpt-oss-20b", "qwen3", "gemma-2-9b"]

    def rank(model_id):
        for i, kw in enumerate(priority_keywords):
            if kw in model_id:
                return i
        return 99

    free_models.sort(key=rank)
    _openrouter_models_cache = free_models[:6]
    return _openrouter_models_cache


def _call_openrouter(prompt, max_tokens=1800):
    if not OPENROUTER_API_KEY:
        raise Exception("OPENROUTER_API_KEY set nahi hai")

    models = _get_openrouter_models()
    last_error = "koi model try nahi hua"
    for model in models:
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.3,
                },
                timeout=REQUEST_TIMEOUT_AI,
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content")
                if text:
                    return text
                last_error = f"{model}: khaali jawab mila"
                continue
            if resp.status_code == 429:
                last_error = f"{model}: rate limit (429)"
                continue
            last_error = f"{model}: {resp.text[:200]}"
        except Exception as e:
            last_error = f"{model}: {e}"

    raise Exception(f"OpenRouter se jawab nahi mila - {last_error}")


def _call_groq(prompt, max_tokens=1800):
    if not GROQ_API_KEY:
        raise Exception("GROQ_API_KEY set nahi hai")

    last_error = "koi model try nahi hua"
    for model in GROQ_MODELS:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.3,
                },
                timeout=REQUEST_TIMEOUT_AI,
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content")
                if text:
                    return text
                last_error = f"{model}: khaali jawab mila"
                continue
            if resp.status_code == 429:
                last_error = f"{model}: rate limit (429)"
                continue
            # Model band/deprecated ho sakta hai - agle model par chale jaayein
            last_error = f"{model}: {resp.text[:200]}"
        except Exception as e:
            last_error = f"{model}: {e}"

    raise Exception(f"Groq se jawab nahi mila - {last_error}")


def _get_gemini_models():
    """Google se LIVE model list mangwata hai (cache karke) - taaki
    kabhi bhi hardcoded/purana model naam use na ho."""
    global _gemini_models_cache
    if _gemini_models_cache:
        return _gemini_models_cache

    resp = requests.get(
        f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}",
        timeout=REQUEST_TIMEOUT_AI,
    )
    resp.raise_for_status()
    data = resp.json()
    models = [
        m["name"].replace("models/", "")
        for m in data.get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]
    if not models:
        raise Exception("Koi usable Gemini model nahi mila")
    # Flash models pehle try karo - tez aur sasta hota hai
    models.sort(key=lambda m: 0 if "flash" in m.lower() else 1)
    _gemini_models_cache = models[:5]
    return _gemini_models_cache


def _call_gemini(prompt, max_tokens=1800):
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY set nahi hai")

    models = _get_gemini_models()
    last_error = "koi model try nahi hua"
    for model in models:
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
                timeout=REQUEST_TIMEOUT_AI,
            )
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and parts[0].get("text"):
                        return parts[0]["text"]
                last_error = f"{model}: khaali jawab mila"
                continue
            if resp.status_code == 429:
                last_error = f"{model}: rate limit (429)"
                continue
            last_error = f"{model}: {resp.text[:200]}"
        except Exception as e:
            last_error = f"{model}: {e}"

    raise Exception(f"Gemini se jawab nahi mila - {last_error}")


def _call_ai(prompt, max_tokens=1800):
    """Pehle OPENROUTER try karta hai (sabse aasaan sign-up), na ho to
    GROQ, na ho to GEMINI (aakhri backup)."""
    errors = []

    if OPENROUTER_API_KEY:
        try:
            return _call_openrouter(prompt, max_tokens)
        except Exception as e:
            errors.append(f"OpenRouter: {e}")
            print(f"    [AI] OpenRouter fail hua, agla provider try kar rahe hain... ({e})")

    if GROQ_API_KEY:
        try:
            return _call_groq(prompt, max_tokens)
        except Exception as e:
            errors.append(f"Groq: {e}")
            print(f"    [AI] Groq fail hua, Gemini try kar rahe hain... ({e})")

    if GEMINI_API_KEY:
        try:
            return _call_gemini(prompt, max_tokens)
        except Exception as e:
            errors.append(f"Gemini: {e}")

    if not errors:
        raise Exception("Koi bhi AI key nahi mili - Railway Variables mein OPENROUTER_API_KEY (ya GROQ_API_KEY/GEMINI_API_KEY) daalein")

    raise Exception(" | ".join(errors))

PROMPT_TEMPLATE = """Tum "Official Sarkari Patrika" naam ke sarkari naukri suchna portal ke liye ek professional content editor ho. Neeche ek raw/kaccha notice text diya gaya hai. Isse ek saaf, professional, accurate, SEO-optimized Hindi job-post mein badlo - bilkul Sarkari Result jaisi professional websites jaisa, jisme HAR field bhari ho (sirf title-link nahi, poori detail).

SAKHT NIYAM:
- Sirf woh jaankari do jo neeche diye gaye text mein maujood hai ya usse seedha nikaali ja sakti hai. Koi bhi tareekh, sankhya, ya fact khud se mat banao/andaza mat lagao.
- Agar "Title:" line diya gaya hai, use hamesha "title" field ke liye istemal karo (SEO ke liye behtar bana sakte ho, lekin poori tarah khud se naya title mat gadhna jab tak asli title bilkul na mile).
- Agar "Likely Status:" diya gaya hai, USI status ko istemal karo jab tak neeche ke content mein saaf-saaf koi DOOSRA status likha ho (jaise agar Likely Status 'job' hai lekin content mein saaf 'Result Declared' likha hai, to 'result' hi चुनो). Khud se kabhi status ko 'job' mat maan lo sirf isliye ki confidence kam hai - Likely Status ko default maano.
- "aboutOrganization" field ke liye tum apne general knowledge ka istemal kar sakte ho (jaise SSC, UPSC, Railway jaise jaane-maane vibhagon ke baare mein) - yeh field sakht niyam se bahar hai. Agar organization anjaan hai, to ek generic professional line likho (jaise "यह भारत सरकार/राज्य सरकार का एक मान्यता प्राप्त विभाग है").
- Agar koi field ki jaankari bilkul na mile, to text wale fields mein "जानकारी उपलब्ध नहीं है" likho. Date wale fields (jahan "YYYY-MM-DD" mangi hai) mein jaankari na mile to seedha null likho (khud se koi date mat banao), aur uske "Note" wale field mein agar kuch likha ho (jaise "जल्द जारी होगी") to wahi likho, warna woh bhi khaali chhod do.
- FAQ mein sirf woh sawaal-jawab likho jinka jawab diye gaye text mein SEEDHA maujood hai - kam se kam 5. Agar kisi sawaal ka jawab text mein nahi mil raha, to woh sawaal hi mat banao (jawab mein "जानकारी उपलब्ध नहीं है" mat bharo - iski jagah koi aisa sawaal chuno jiska jawab sach mein text mein ho).
- Professional Hindi bhasha, common English shabd (Apply Online, Admit Card) chalenge.
- Sirf neeche diye JSON format mein jawab do - koi extra text, koi markdown backticks, koi preamble nahi.

JSON FORMAT:
{{
  "title": "poora, spasht, SEO-friendly Hindi post title",
  "slugTitle": "sirf ANGREZI (English) mein, chhote akshar, hyphen se jude 4-8 shabd - jaise 'isro-scientist-engineer-recruitment-2026' - URL ke liye, kabhi Hindi mat likhna is field mein",
  "status": "job ya admit_card ya answer_key ya result ya final_selection - upar diye 'Likely Status' ko default maano",
  "organization": "vibhag/sanstha ka poora naam",
  "aboutOrganization": "2-4 line mein is vibhag/sanstha ke baare mein professional jaankari (general knowledge chalega)",
  "vacancy": "sirf number ya N/A",
  "jobLocation": "jaise 'All India / पूरे भारत में' ya 'Uttar Pradesh' - jahan yeh bharti lagu hoti hai",
  "eligibilitySummary": "1-2 line mein chhota summary (sirf vacancy table ke liye)",
  "eligibilityDetails": "poori shiksha yogyata, age limit, age relaxation - har point naye line mein",
  "howToApply": "aavedan karne ke step-by-step tareeke, har step naya line mein (jaise: 1. Official website kholein 2. Registration karein...)",
  "applicationFeeGeneral": "General/OBC candidates ki fee, jaise '₹100' - na mile to khaali",
  "applicationFeeScst": "SC/ST/PH candidates ki fee - na mile to khaali",
  "applicationFeePaymentMode": "payment kaise karein, jaise 'Online (Debit Card/Net Banking)' - na mile to khaali",
  "salaryText": "pay scale, jaise 'Level 4 (₹25,500 - ₹81,100)' - na mile to khaali",
  "salaryMin": "sirf number, jaise 25500 - na mile to khaali",
  "salaryMax": "sirf number, jaise 81100 - na mile to khaali",
  "categoryWiseVacancy": {{
    "ur": "sirf number - na mile to khaali",
    "ews": "sirf number - na mile to khaali",
    "obc": "sirf number - na mile to khaali",
    "sc": "sirf number - na mile to khaali",
    "st": "sirf number - na mile to khaali",
    "total": "sirf number - na mile to khaali"
  }},
  "admitCardInfo": "sirf agar status 'admit_card' hai: download process, zaroori documents - na mile to khaali",
  "resultInfo": "sirf agar status 'result' ya 'final_selection' hai: cut-off, agla step - na mile to khaali",
  "salaryMin": "sirf number (₹ prati maah), na mile to null",
  "salaryMax": "sirf number (₹ prati maah), na mile to null",
  "categoryWiseVacancy": {{
    "ur": "General/UR ke pad, sirf number, na mile to null",
    "ews": "EWS ke pad, sirf number, na mile to null",
    "obc": "OBC/BC ke pad, sirf number, na mile to null",
    "sc": "SC ke pad, sirf number, na mile to null",
    "st": "ST ke pad, sirf number, na mile to null",
    "total": "kul pad, sirf number, na mile to null"
  }},
  "importantDates": {{
    "applicationStart": "YYYY-MM-DD ya null",
    "applicationStartNote": "agar exact date na ho to chhota note, warna khaali",
    "applicationEnd": "YYYY-MM-DD ya null",
    "applicationEndNote": "agar exact date na ho to chhota note, warna khaali",
    "admitCardDate": "YYYY-MM-DD ya null",
    "admitCardDateNote": "agar exact date na ho to chhota note, warna khaali",
    "examDate": "YYYY-MM-DD ya null",
    "examDateNote": "agar exact date na ho to chhota note, warna khaali",
    "resultDate": "YYYY-MM-DD ya null",
    "resultDateNote": "agar exact date na ho to chhota note, warna khaali"
  }},
  "description": "4-7 bullet points, har line ek naya point, poori jaankari ke saath",
  "links": [
    {{"label": "Hindi mein chhota label", "url": "http...", "type": "Apply Online"}},
    {{"label": "Hindi mein chhota label", "url": "http...", "type": "Official Notification"}},
    {{"label": "Hindi mein chhota label", "url": "http...", "type": "Official Website"}}
  ],
  "faqs": [
    {{"question": "Hindi mein sawaal", "answer": "Hindi mein seedha jawab"}}
  ],
  "seoMetaTitle": "60 character tak ka SEO title",
  "seoMetaDescription": "150-160 character tak ka SEO description"
}}

"links" ke "type" field ke liye SIRF yahi 5 value istemal karo (jo lagu ho wahi jodo, sabhi zaroori nahi): "Apply Online", "Download Admit Card", "Check Result", "Official Notification", "Official Website"

RAW NOTICE TEXT:
\"\"\"
{raw_text}
\"\"\""""


def generate_structured_post(raw_text):
    """Raw scraped text leta hai, AI (pehle Groq, backup Gemini) se
    structured JSON banwa kar Python dict return karta hai."""
    prompt = PROMPT_TEMPLATE.format(raw_text=raw_text[:8000])
    raw_response = _call_ai(prompt, max_tokens=2800)

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
    text = _as_text(text).lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text).strip("-")
    return text[:90]


def _random_key():
    """Sanity ke har array-item ko ek unique '_key' chahiye hota hai
    (Studio mein editing ke liye zaroori) - yeh chhota random ID banata hai."""
    return hashlib.md5(os.urandom(16)).hexdigest()[:12]


def _now_iso():
    """Abhi ka UTC waqt Sanity ke datetime format (ISO 8601) mein deta hai."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_base_slug(title, slug_title_hint=None):
    """Title/slug-hint se base slug nikaalta hai (bina uniqueness-suffix
    ke) - duplicate-check aur make_unique_slug dono isi ko istemal karte
    hain, taaki dono jagah SAME slug par comparison ho."""
    base = slugify(slug_title_hint) if slug_title_hint else ""
    if not base:
        base = slugify(title)
    if not base:
        base = f"sarkari-post-{_random_key()[:6]}"
    return base


def _strip_drafts_prefix(doc_id):
    return doc_id[len("drafts."):] if doc_id.startswith("drafts.") else doc_id


def find_existing_post_by_slug(base_slug):
    """Base slug se koi bhi maujooda jobPost (draft ya published, kisi
    bhi source se) dhoondhta hai - _id aur sourceUrl dono ke saath."""
    return _sanity_query(
        '*[_type == "jobPost" && slug.current == $slug][0]{_id, sourceUrl}',
        {"slug": base_slug},
    )


def make_unique_slug(base_slug, exclude_doc_id=None):
    """jobPost.ts schema ka isUnique rule sirf Studio UI mein chalta hai,
    API se likhte waqt nahi - isliye yahan khud check karte hain taaki
    do ALAG posts ka slug kabhi takrayein nahi.

    🔧 FIX 1: Hindi (Devanagari) title se slugify() karne par sab akshar
    hat jaate hain aur khaali/'post' jaisa bekaar slug ban jaata tha -
    ab caller (_compute_base_slug) English slug-hint ko priority deta hai.

    🔧 FIX 2: 'exclude_doc_id' pass karne se, agar SAME post dobara
    (usi source_link se) generate ho raha ho, to woh apne aap ko hi
    "duplicate" na maan le - warna har baar slug ke aage -2, -3 judta
    jaata (jabki asal mein ek hi post baar-baar update ho raha hota hai)."""
    exclude_stripped = _strip_drafts_prefix(exclude_doc_id) if exclude_doc_id else None
    slug = base_slug
    counter = 2
    while True:
        existing = _sanity_query(
            '*[_type == "jobPost" && slug.current == $slug][0]._id',
            {"slug": slug},
        )
        if not existing or (exclude_stripped and _strip_drafts_prefix(existing) == exclude_stripped):
            return slug
        slug = f"{base_slug}-{counter}"
        counter += 1
        slug = f"{base}-{counter}"
        counter += 1


def get_or_create_organization(name, fallback_website, about_text=None):
    """Organization pehle se ho to uski _id deta hai, warna nayi bana deta
    hai - isse 'UPSC' baar-baar duplicate nahi banega. Pehli baar banate
    waqt hi 'about' (2-3 line summary) bhi daal dete hain, agar mile."""
    name = _as_text(name).strip() or "Sarkari Vibhag"

    existing = _sanity_query(
        '*[_type == "organization" && name == $name][0]._id',
        {"name": name},
    )
    if existing:
        return existing

    org_id = f"org-{hashlib.md5(name.encode()).hexdigest()[:12]}"
    org_slug = slugify(name) or org_id
    doc = {
        "_id": org_id,
        "_type": "organization",
        "name": name,
        "slug": {"_type": "slug", "current": org_slug},
        "website": fallback_website or "https://www.india.gov.in",
    }
    about_clean = _clean_short_text(about_text)
    if about_clean:
        doc["about"] = about_clean[:600]
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


def _as_text(value):
    """AI kabhi-kabhi ek field ko string ki jagah list (jaise har point
    alag array-item) mein bhej deta hai. Yeh function dono format ko
    hamesha ek plain string mein badal deta hai - taaki aage koi bhi
    .split()/.strip() wala code kabhi crash na ho, chahe AI ka jawab
    kaisa bhi format mein aaye."""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if item)
    return str(value) if value else ""


def _text_to_blocks(text):
    """Plain text (har line ek point) ko Sanity ke Portable Text block
    format mein badalta hai - jobPost.ts ke 'description' field ke liye.
    Har block/span ko _key diya gaya hai (Sanity Studio mein editing ke
    liye zaroori). 🔧 FIX: text agar list ho (AI kabhi aisa bhej deta
    hai) to pehle usse string mein badal lete hain, warna .split() par
    crash ho jaata tha."""
    text = _as_text(text)
    blocks = []
    for line in text.split("\n"):
        line = line.strip().lstrip("-•").strip()
        if not line:
            continue
        blocks.append({
            "_type": "block",
            "_key": _random_key(),
            "style": "normal",
            "children": [{"_type": "span", "_key": _random_key(), "text": line}],
        })
    return blocks


# jobPost.ts schema mein importantLinks.linkType ke liye SIRF yeh 5 value
# valid hain - AI kabhi thoda alag likh de to yahan sahi value se match
# karte hain, warna default "Official Website" laga dete hain
VALID_LINK_TYPES = [
    "Apply Online", "Download Admit Card", "Check Result",
    "Official Notification", "Official Website",
]


def _build_links_array(links_list):
    """AI se mile links (label/url/type) ko Sanity ke importantLinks
    array format mein badalta hai - har link ka sahi 'linkType' bhi
    set karta hai, taaki website par sahi icon/style ke saath dikhe."""
    result = []
    for item in (links_list or []):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.lower().startswith("http"):
            continue
        link_type = item.get("type") or "Official Website"
        if link_type not in VALID_LINK_TYPES:
            link_type = "Official Website"
        result.append({
            "_type": "object",
            "_key": _random_key(),
            "label": _as_text(item.get("label") or link_type).strip()[:60],
            "url": url,
            "linkType": link_type,
        })
    return result


def _build_faq_section(faqs_list):
    """AI se mile FAQ (question/answer) ko jobPost.ts ke
    'customSectionsAfterLinks' ke andar ek proper section ke roop mein
    banata hai - isse website par yeh bilkul aapke doosre structured
    section jaisa (heading + content box) dikhega, koi plain/generic
    text block nahi banega."""
    content_blocks = []
    for item in (faqs_list or []):
        if not isinstance(item, dict):
            continue
        question = _as_text(item.get("question")).strip()
        answer = _as_text(item.get("answer")).strip()
        if not question or not answer:
            continue
        # Sawaal - Bold
        content_blocks.append({
            "_type": "block",
            "_key": _random_key(),
            "style": "normal",
            "children": [{
                "_type": "span", "_key": _random_key(),
                "text": f"प्रश्न: {question}", "marks": ["strong"],
            }],
        })
        # Jawab - Normal
        content_blocks.append({
            "_type": "block",
            "_key": _random_key(),
            "style": "normal",
            "children": [{
                "_type": "span", "_key": _random_key(),
                "text": f"उत्तर: {answer}",
            }],
        })

    if not content_blocks:
        return None

    return {
        "_type": "object",
        "_key": _random_key(),
        "heading": "अक्सर पूछे जाने वाले प्रश्न (FAQ)",
        "content": content_blocks,
    }


def _build_custom_section(heading, text):
    """Eligibility, How-to-Apply jaisi cheezon ko jobPost.ts ke
    'customSectionsBeforeLinks' format mein ek proper section (heading +
    content box) banata hai - description ke andar generic text ki
    jagah website par alag, saaf dikhne wala box banta hai."""
    text = _as_text(text).strip()
    if not text or text == "जानकारी उपलब्ध नहीं है":
        return None
    content_blocks = _text_to_blocks(text)
    if not content_blocks:
        return None
    return {
        "_type": "object",
        "_key": _random_key(),
        "heading": heading,
        "content": content_blocks,
    }


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _valid_date(value):
    """AI se mili date ko check karta hai - sirf sahi 'YYYY-MM-DD' format
    (aur asli calendar date) ho tabhi use karte hain, warna None -
    isse Sanity ko kabhi galat/tuta hua date bhejकर 400 error nahi aata."""
    value = _as_text(value).strip()
    if not value or not _DATE_RE.match(value):
        return None
    try:
        from datetime import date
        y, m, d = (int(x) for x in value.split("-"))
        date(y, m, d)
        return value
    except (ValueError, TypeError):
        return None


def _build_important_dates(dates_dict):
    """AI se mile importantDates ko Sanity ke format mein badalta hai -
    har date ke liye pehle asli date try karta hai, na mile to sirf
    uska 'Note' text field bharta hai (schema mein dono ka yehi design
    hai). Poora object khaali rahe to None deta hai."""
    if not isinstance(dates_dict, dict):
        return None

    pairs = [
        ("applicationStart", "applicationStartNote"),
        ("applicationEnd", "applicationEndNote"),
        ("admitCardDate", "admitCardDateNote"),
        ("examDate", "examDateNote"),
        ("resultDate", "resultDateNote"),
    ]

    result = {}
    for date_key, note_key in pairs:
        valid = _valid_date(dates_dict.get(date_key))
        if valid:
            result[date_key] = valid
            continue
        note = _as_text(dates_dict.get(note_key)).strip()
        if note and note != "जानकारी उपलब्ध नहीं है":
            result[note_key] = note[:100]

    return result if result else None


def _safe_int(value):
    """AI se mili sankhya ko surakshit tareeke se number mein badalta
    hai - agar woh number na ho (jaise 'जानकारी उपलब्ध नहीं है' ya
    null ya khaali), to None deta hai, kabhi crash nahi karta."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = _as_text(value).strip()
    if not text or not text.replace(",", "").replace(".", "").isdigit():
        return None
    try:
        return int(float(text.replace(",", "")))
    except (ValueError, TypeError):
        return None


def _clean_short_text(value):
    """Chhote text fields (fee, salary, location) ke liye - agar AI ne
    'जानकारी उपलब्ध नहीं है' likh diya to khaali string deta hai (taaki
    website par khaali/bekaar field na dikhe)."""
    value = _as_text(value).strip()
    if not value or value == "जानकारी उपलब्ध नहीं है":
        return ""
    return value


def create_draft_job_post(structured, source_link, status_hint=None):
    """Structured AI data se ek DRAFT jobPost document Sanity mein banata
    hai. _id 'drafts.' se shuru hota hai - isliye yeh KABHI public website
    par nahi dikhega jab tak Studio mein manually 'Publish' na dabaya jaaye."""

    title = _as_text(structured.get("title")).strip() or "Untitled Post"
    status = structured.get("status") if structured.get("status") in VALID_STATUSES else (status_hint or "job")
    vacancy_raw = str(structured.get("vacancy") or "").strip()

    # Post ki unique id link se banti hai - isse agar bot galti se same
    # link do baar process kar de, to duplicate draft nahi banega
    doc_id = f"drafts.jobpost-{hashlib.md5(source_link.encode()).hexdigest()[:16]}"

    # 🆕 CROSS-SOURCE DUPLICATE CHECK: agar yehi post (jaisa hi title)
    # KISI DOOSRE source se pehle hi aa chuka hai, to naya draft na
    # banayein - warna 5 alag websites (Sarkari Result, FreeJobAlert,
    # etc.) ek hi asli notice ke liye 5 alag draft bana dengi.
    base_slug = _compute_base_slug(title, structured.get("slugTitle"))
    existing_post = find_existing_post_by_slug(base_slug)
    if existing_post:
        existing_id_stripped = _strip_drafts_prefix(existing_post.get("_id", ""))
        this_id_stripped = _strip_drafts_prefix(doc_id)
        existing_source = existing_post.get("sourceUrl", "")
        if existing_id_stripped != this_id_stripped and existing_source != source_link:
            print(f"    [DUPLICATE] '{title}' jaisa post pehle se maujood hai "
                  f"(source: {existing_source}) - naya draft NAHI banaya")
            return {"draftId": None, "slug": base_slug, "title": title, "duplicate": True}

    org_id = get_or_create_organization(
        structured.get("organization"), source_link,
        about_text=structured.get("aboutOrganization"),
    )
    cat_id = get_or_create_category(status)
    slug = make_unique_slug(base_slug, exclude_doc_id=doc_id)

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
        "importantLinks": _build_links_array(structured.get("links")),
        "seo": {
            "metaTitle": _as_text(structured.get("seoMetaTitle") or title)[:60],
            "metaDescription": _as_text(structured.get("seoMetaDescription"))[:160],
        },
        # 🆕 publishedAt/updatedAt: Studio mein yeh apne aap aaj ki date bhar
        # deta hai (initialValue), lekin woh sirf Studio UI ka trick hai -
        # seedhe API se likhte waqt yeh khud set karna padta hai, warna
        # khaali reh jaata (jo Schema.org dateModified ke liye zaroori hai)
        "publishedAt": _now_iso(),
        "updatedAt": _now_iso(),
    }

    # 🆕 IMPORTANT DATES - Application/Admit Card/Exam/Result dates
    important_dates = _build_important_dates(structured.get("importantDates"))
    if important_dates:
        doc["importantDates"] = important_dates

    # 🆕 JOB LOCATION - Google Jobs ke liye zaroori maana jaata hai
    if status == "job":
        job_location = _clean_short_text(structured.get("jobLocation"))
        if job_location:
            doc["jobLocation"] = job_location[:100]

    # 🆕 APPLICATION FEE - teeno field mein se koi ek bhi mile to jodein
    if status == "job":
        fee_general = _clean_short_text(structured.get("applicationFeeGeneral"))
        fee_scst = _clean_short_text(structured.get("applicationFeeScst"))
        fee_mode = _clean_short_text(structured.get("applicationFeePaymentMode"))
        if fee_general or fee_scst or fee_mode:
            doc["applicationFee"] = {
                "general": fee_general,
                "scst": fee_scst,
                "paymentMode": fee_mode,
            }

    # 🆕 SALARY / PAY SCALE
    if status == "job":
        salary_text = _clean_short_text(structured.get("salaryText"))
        salary_min = _safe_int(structured.get("salaryMin"))
        salary_max = _safe_int(structured.get("salaryMax"))
        if salary_text or salary_min or salary_max:
            salary_obj = {}
            if salary_text:
                salary_obj["payScaleText"] = salary_text[:150]
            if salary_min:
                salary_obj["minAmount"] = salary_min
            if salary_max:
                salary_obj["maxAmount"] = salary_max
            doc["salary"] = salary_obj

    # 🆕 CATEGORY-WISE VACANCY (UR/EWS/OBC/SC/ST/Total)
    cat_vacancy_raw = structured.get("categoryWiseVacancy")
    if isinstance(cat_vacancy_raw, dict):
        cat_vacancy = {}
        for key in ("ur", "ews", "obc", "sc", "st", "total"):
            val = _safe_int(cat_vacancy_raw.get(key))
            if val is not None:
                cat_vacancy[key] = val
        if cat_vacancy:
            doc["categoryWiseVacancy"] = cat_vacancy

    # 🆕 ADMIT CARD INFO / RESULT INFO - sirf jab status lagu ho
    if status == "admit_card":
        admit_info = _clean_short_text(structured.get("admitCardInfo"))
        if admit_info:
            doc["admitCardInfo"] = admit_info[:2000]

    if status in ("result", "final_selection"):
        result_info = _clean_short_text(structured.get("resultInfo"))
        if result_info:
            doc["resultInfo"] = result_info[:2000]

    # 🆕 STATUS TIMELINE - is naye status ko ek entry ke roop mein jod dete
    # hain, taaki website par "kab kya hua" ki history bhi dikhe
    status_labels = {
        "job": "Notification / Job Opening jari hui",
        "admit_card": "Admit Card jari hua",
        "answer_key": "Answer Key jari hui",
        "result": "Result ghoshit hua",
        "final_selection": "Final Selection / Merit List jari hui",
    }
    doc["statusTimeline"] = [{
        "_type": "object",
        "_key": _random_key(),
        "status": status_labels.get(status, status),
        "date": _now_iso(),
    }]

    # 🆕 ELIGIBILITY + HOW TO APPLY - alag, proper sections ke roop mein
    # (description ke andar generic text ki jagah) - "customSectionsBeforeLinks"
    # mein jaate hain, isliye page par Important Links se PEHLE dikhenge
    before_links_sections = []
    eligibility_section = _build_custom_section(
        "पात्रता मानदंड (Eligibility Criteria)",
        structured.get("eligibilityDetails"),
    )
    if eligibility_section:
        before_links_sections.append(eligibility_section)

    how_to_apply_section = _build_custom_section(
        "आवेदन कैसे करें (How to Apply)",
        structured.get("howToApply"),
    )
    if how_to_apply_section:
        before_links_sections.append(how_to_apply_section)

    if before_links_sections:
        doc["customSectionsBeforeLinks"] = before_links_sections

    faq_section = _build_faq_section(structured.get("faqs"))
    if faq_section:
        doc["customSectionsAfterLinks"] = [faq_section]

    if vacancy_raw.isdigit():
        eligibility_summary = _as_text(
            structured.get("eligibilitySummary") or structured.get("eligibilityDetails")
        )
        doc["vacancyDetails"] = [{
            "_type": "object",
            "_key": _random_key(),
            "postName": title[:80],
            "totalPosts": int(vacancy_raw),
            "eligibility": eligibility_summary,
        }]

    # 🆕 BANNER: Post ke hisaab se automatic banner banakar seedha
    # "featuredImage" field mein laga dete hain (Google News/Discover/
    # WhatsApp preview isi photo ko istemal karti hai). Yeh apni ALAG
    # try/except mein hai - agar font file na mile ya kisi wajah se
    # banner na ban paaye, to bhi POORA POST bina banner ke ban jaayega,
    # rukega nahi.
    try:
        from banner_generator import generate_banner
        banner_bytes = generate_banner(
            title=title,
            organization=_as_text(structured.get("organization")),
            vacancy=vacancy_raw if vacancy_raw.isdigit() else "",
            status=status,
        )
        asset_id = _upload_image_to_sanity(banner_bytes, f"{slug}.png")
        doc["featuredImage"] = {
            "_type": "image",
            "asset": {"_type": "reference", "_ref": asset_id},
            "alt": title[:125],
        }
    except Exception as e:
        print(f"    [BANNER] Banner nahi ban paaya (post phir bhi ban jaayega): {e}")

    _sanity_mutate([{"createOrReplace": doc}])
    return {"draftId": doc_id, "slug": slug, "title": title}


def _upload_image_to_sanity(image_bytes, filename="banner.png"):
    """PNG image bytes ko Sanity ke Assets API se upload karta hai aur
    uski asset _id wapas deta hai - isi _id ko document ke image field
    mein reference ki tarah jodते hैं।"""
    url = f"https://{SANITY_PROJECT_ID}.api.sanity.io/v{SANITY_API_VERSION}/assets/images/{SANITY_DATASET}"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {SANITY_API_TOKEN}", "Content-Type": "image/png"},
        params={"filename": filename},
        data=image_bytes,
        timeout=30,
    )
    if resp.status_code >= 300:
        raise Exception(f"Image upload fail (status {resp.status_code}): {resp.text[:200]}")
    return resp.json()["document"]["_id"]


# ============================================================================
# ENTRY POINT - main.py isi ek function ko bulata hai
# ============================================================================

def publish_scraped_post(raw_text, source_link, status_hint=None):
    """Raw text leta hai -> AI se structure karwaata hai -> Sanity mein
    DRAFT bana deta hai. Koi bhi step fail ho, to exception upar (main.py
    mein) jaake pakdi jaati hai, taaki poora bot na ruke.

    status_hint (optional): keyword-based bharosemand status (scraper.py
    ka detect_status()) - agar AI khud koi valid status na de paaye, to
    seedha "job" maan lene ke bajaye isi hint ka istemal hota hai."""
    structured = generate_structured_post(raw_text)
    result = create_draft_job_post(structured, source_link, status_hint=status_hint)
    return result
# 🆕 TELEGRAM REVIEW-BOT KE LIYE - draft ko padhna, sirf-kuch-fields patch
# karna, aur seedha Publish karna. Yeh sab Vercel wale interactive bot
# (/api/telegram_webhook.py) istemal karta hai.
# ============================================================================

def get_draft_by_id(doc_id):
    """Poora draft document Sanity se laata hai - review-summary Telegram
    par bhejne ke liye."""
    return _sanity_query('*[_id == $id][0]', {"id": doc_id})


def patch_sanity_fields(doc_id, field_set):
    """Sirf diye gaye fields ko update karta hai - poora document dobara
    nahi likhna padta. Nested field jaise 'importantDates.examDate' bhi
    seedha chal jaata hai (Sanity ka apna 'dotted path' support)."""
    if not field_set:
        return None
    mutation = {"patch": {"id": doc_id, "set": field_set}}
    return _sanity_mutate([mutation])


def publish_draft_now(doc_id):
    """Draft ko TURANT Publish kar deta hai - bilkul Sanity Studio ke
    'Publish' button jaisa: draft ka poora content published (bina
    'drafts.' wali) id par copy karke, draft version delete kar deta hai."""
    draft_doc = get_draft_by_id(doc_id)
    if not draft_doc:
        raise Exception("Draft nahi mila - shayad pehle hi publish ho chuka hai ya ID galat hai")

    published_id = _strip_drafts_prefix(doc_id)
    published_doc = dict(draft_doc)
    published_doc["_id"] = published_id
    published_doc["updatedAt"] = _now_iso()

    mutations = [
        {"createOrReplace": published_doc},
        {"delete": {"id": doc_id}},
    ]
    _sanity_mutate(mutations)
    return published_id


def rebuild_eligibility_section(doc_id, new_eligibility_text):
    """Eligibility wala custom-section poora naye sirre se banata hai
    (kyunki yeh ek 'array' field hai, seedha text patch nahi ho sakta)
    aur Sanity mein set kar deta hai."""
    section = _build_custom_section("पात्रता मानदंड (Eligibility Criteria)", new_eligibility_text)
    current = get_draft_by_id(doc_id) or {}
    sections = current.get("customSectionsBeforeLinks", []) or []
    # Purana "Eligibility" section hata kar naya jodते hैं, baaki jaise-the-waise
    sections = [s for s in sections if s.get("heading") != "पात्रता मानदंड (Eligibility Criteria)"]
    if section:
        sections.insert(0, section)
    patch_sanity_fields(doc_id, {"customSectionsBeforeLinks": sections})


def rebuild_how_to_apply_section(doc_id, new_text):
    """How-to-Apply wala custom-section poora naye sirre se banata hai."""
    section = _build_custom_section("आवेदन कैसे करें (How to Apply)", new_text)
    current = get_draft_by_id(doc_id) or {}
    sections = current.get("customSectionsBeforeLinks", []) or []
    sections = [s for s in sections if s.get("heading") != "आवेदन कैसे करें (How to Apply)"]
    if section:
        sections.append(section)
    patch_sanity_fields(doc_id, {"customSectionsBeforeLinks": sections})


def rebuild_faq_section(doc_id, faqs_list):
    """FAQ section poora naye sirre se banata hai."""
    section = _build_faq_section(faqs_list)
    patch_sanity_fields(doc_id, {"customSectionsAfterLinks": [section] if section else []})


# ============================================================================
# 🆕 VISION AI - scanned PDF/photo se seedha "dekh kar" jaankari nikaalne
# ke liye (Vercel par tesseract/OCR install nahi ho sakta, isliye yeh
# behtar tareeka hai - AI seedha tasveer padh leta hai)
# ============================================================================

VISION_MODELS = [
    "qwen/qwen2.5-vl-72b-instruct:free",
    "qwen/qwen2.5-vl-32b-instruct:free",
    "meta-llama/llama-3.2-11b-vision-instruct:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
]


def call_vision_ai(prompt, images_base64):
    """Ek ya kai tasveerein (base64 PNG) + ek sawaal/prompt AI ko bhejta
    hai, jawab (text) wapas deta hai. Kai free vision-model try karta
    hai (ek fail ho to agla). Koi bhi kaam na kare to Exception uthata
    hai - calling code isse pakad kar bina crash hue aage badh jaata hai."""
    if not OPENROUTER_API_KEY:
        raise Exception("OPENROUTER_API_KEY set nahi hai - vision AI ke liye zaroori hai")

    content = [{"type": "text", "text": prompt}]
    for img_b64 in images_base64[:5]:  # zyada se zyada 5 tasveerein ek saath
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
        })

    last_error = "koi model try nahi hua"
    for model in VISION_MODELS:
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": content}],
                    "max_tokens": 2500,
                    "temperature": 0.2,
                },
                timeout=55,
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content")
                if text:
                    return text
                last_error = f"{model}: khaali jawab mila"
                continue
            if resp.status_code == 429:
                last_error = f"{model}: rate limit"
                continue
            last_error = f"{model}: {resp.text[:200]}"
        except Exception as e:
            last_error = f"{model}: {e}"

    raise Exception(f"Vision AI se jawab nahi mila - {last_error}")
