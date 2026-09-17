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

PROMPT_TEMPLATE = """Tum "Official Sarkari Patrika" naam ke sarkari naukri suchna portal ke liye ek professional content editor ho. Neeche ek raw/kaccha notice text diya gaya hai. Isse ek saaf, professional, accurate, SEO-optimized Hindi job-post mein badlo - bilkul Sarkari Result jaisi professional websites jaisa.

SAKHT NIYAM:
- Sirf woh jaankari do jo neeche diye gaye text mein maujood hai ya usse seedha nikaali ja sakti hai. Koi bhi tareekh, sankhya, ya fact khud se mat banao. Agar jaankari na mile to us field mein "जानकारी उपलब्ध नहीं है" likho.
- Professional Hindi bhasha, common English shabd (Apply Online, Admit Card) chalenge.
- FAQ mein sirf woh sawaal-jawab likho jo diye gaye text se seedha nikalte hain (jaise eligibility, last date, fee, vacancy) - kam se kam 5, khud se koi jhoothi jaankari mat jodo.
- Sirf neeche diye JSON format mein jawab do - koi extra text, koi markdown backticks, koi preamble nahi.

JSON FORMAT:
{{
  "title": "poora, spasht, SEO-friendly Hindi post title",
  "slugTitle": "sirf ANGREZI (English) mein, chhote akshar, hyphen se jude 4-8 shabd - jaise 'isro-scientist-engineer-recruitment-2026' - URL ke liye, kabhi Hindi mat likhna is field mein",
  "status": "job ya admit_card ya answer_key ya result ya final_selection",
  "organization": "vibhag/sanstha ka poora naam",
  "vacancy": "sirf number ya N/A",
  "eligibility": "shiksha yogyata, age limit",
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


def make_unique_slug(title, slug_title_hint=None):
    """jobPost.ts schema ka isUnique rule sirf Studio UI mein chalta hai,
    API se likhte waqt nahi - isliye yahan khud check karte hain taaki
    do posts ka slug kabhi takrayein nahi.

    🔧 FIX: Hindi (Devanagari) title se slugify() karne par sab akshar
    hat jaate hain (URL mein sirf a-z0-9 chalta hai) aur khaali/'post'
    jaisa bekaar slug ban jaata tha. Ab AI se ek ALAG English slug-hint
    bhi mangwate hain aur usse priority dete hain - Hindi title sirf
    tabhi try hota hai jab woh already English/Latin ho."""
    base = slugify(slug_title_hint) if slug_title_hint else ""
    if not base:
        base = slugify(title)
    if not base:
        # Title bhi poori tarah Hindi nikla aur hint bhi nahi mila -
        # aakhri sahara: ek chhota random-suffix wala generic slug
        base = f"sarkari-post-{_random_key()[:6]}"

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


def create_draft_job_post(structured, source_link):
    """Structured AI data se ek DRAFT jobPost document Sanity mein banata
    hai. _id 'drafts.' se shuru hota hai - isliye yeh KABHI public website
    par nahi dikhega jab tak Studio mein manually 'Publish' na dabaya jaaye."""

    title = _as_text(structured.get("title")).strip() or "Untitled Post"
    status = structured.get("status") if structured.get("status") in VALID_STATUSES else "job"
    vacancy_raw = str(structured.get("vacancy") or "").strip()

    org_id = get_or_create_organization(structured.get("organization"), source_link)
    cat_id = get_or_create_category(status)
    slug = make_unique_slug(title, structured.get("slugTitle"))

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
        "importantLinks": _build_links_array(structured.get("links")),
        "seo": {
            "metaTitle": _as_text(structured.get("seoMetaTitle") or title)[:60],
            "metaDescription": _as_text(structured.get("seoMetaDescription"))[:160],
        },
    }

    faq_section = _build_faq_section(structured.get("faqs"))
    if faq_section:
        doc["customSectionsAfterLinks"] = [faq_section]

    if vacancy_raw.isdigit():
        doc["vacancyDetails"] = [{
            "_type": "object",
            "_key": _random_key(),
            "postName": title[:80],
            "totalPosts": int(vacancy_raw),
            "eligibility": _as_text(structured.get("eligibility")),
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

def publish_scraped_post(raw_text, source_link):
    """Raw text leta hai -> AI se structure karwaata hai -> Sanity mein
    DRAFT bana deta hai. Koi bhi step fail ho, to exception upar (main.py
    mein) jaake pakdi jaati hai, taaki poora bot na ruke."""
    structured = generate_structured_post(raw_text)
    result = create_draft_job_post(structured, source_link)
    return result
