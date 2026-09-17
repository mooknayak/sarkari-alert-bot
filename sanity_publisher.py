# sanity_publisher.py
#
# Yeh file 2 kaam karti hai:
#   1) Scrape kiye gaye raw/kaccha text (aur/ya official notification ki
#      photo(n)) ko AI se ek saaf-suthra, professional, structured post
#      (JSON) mein badalna - PDF text-based ho ya scanned/photo, dono
#      tarah se padh kar.
#   2) Us structured post ko seedha Sanity CMS mein ek DRAFT document ke
#      roop mein save karna - DRAFT isliye taaki woh public website par
#      TURANT NA dikhe. Aap Sanity Studio (aapki-site.com/studio) mein
#      jaakar use padh/edit karke khud "Publish" button dabayenge, tabhi
#      woh live hoga.
#
# Is file ko chalane ke liye Railway ke Variables mein yeh sab set hone
# chahiye: SANITY_PROJECT_ID, SANITY_DATASET, SANITY_API_TOKEN, aur
# kam-se-kam ek AI key (OPENROUTER_API_KEY / GROQ_API_KEY / GEMINI_API_KEY)

import os
import re
import json
import time
import base64
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
# HISSA 1: AI se raw text/photo ko structured JSON mein badalna
#
# TEEN TEXT providers (OpenRouter -> Groq -> Gemini) - agar ek fail ho to
# khud-ba-khud agle par switch. Photo/image wale case mein (jaha padhna
# "dekh" kar hota hai) sirf woh providers istemal hote hain jo vision
# support karte hain: OpenRouter (vision-capable free models) -> Gemini
# (jo khud hi multimodal hai) - Groq ko vision ke liye istemal nahi
# karte, kyunki uske free vision-model bharose layak nahi rehte.
# ============================================================================

REQUEST_TIMEOUT_AI = 60

_openrouter_models_cache = None
_openrouter_vision_models_cache = None

GROQ_MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.6-27b", "openai/gpt-oss-20b", "llama-3.1-8b-instant"]

# Vision ke liye OpenRouter par agar live-fetch se kuch na mile to yeh
# jaani-pehchaani free vision-model list aakhri sahara ke roop mein
FALLBACK_VISION_MODELS = [
    "google/gemini-2.0-flash-exp:free",
    "meta-llama/llama-3.2-11b-vision-instruct:free",
    "qwen/qwen2.5-vl-32b-instruct:free",
]

_gemini_models_cache = None


def _get_openrouter_models():
    """OpenRouter se LIVE free-model (text) list mangwata hai (cache karke)."""
    global _openrouter_models_cache
    if _openrouter_models_cache:
        return _openrouter_models_cache

    resp = requests.get("https://openrouter.ai/api/v1/models", timeout=REQUEST_TIMEOUT_AI)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    free_models = [m["id"] for m in data if m.get("id", "").endswith(":free")]
    if not free_models:
        raise Exception("Koi free model nahi mila")

    priority_keywords = ["gpt-oss-120b", "llama-3.3-70b", "gpt-oss-20b", "qwen3", "gemma-2-9b"]

    def rank(model_id):
        for i, kw in enumerate(priority_keywords):
            if kw in model_id:
                return i
        return 99

    free_models.sort(key=rank)
    _openrouter_models_cache = free_models[:6]
    return _openrouter_models_cache


def _get_openrouter_vision_models():
    """
    OpenRouter se LIVE free vision-model list mangwata hai - sirf woh
    models jo photo/image samajh sakte hain (architecture.input_modalities
    mein "image" ho). Live list na mil paaye ya khaali aaye, to hardcoded
    FALLBACK_VISION_MODELS istemal karte hain - kabhi khaali haath nahi
    rehte.
    """
    global _openrouter_vision_models_cache
    if _openrouter_vision_models_cache:
        return _openrouter_vision_models_cache

    try:
        resp = requests.get("https://openrouter.ai/api/v1/models", timeout=REQUEST_TIMEOUT_AI)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        vision_models = []
        for m in data:
            model_id = m.get("id", "")
            if not model_id.endswith(":free"):
                continue
            modalities = (m.get("architecture") or {}).get("input_modalities") or []
            if "image" in modalities:
                vision_models.append(model_id)
        if vision_models:
            _openrouter_vision_models_cache = vision_models[:6]
            return _openrouter_vision_models_cache
    except Exception as e:
        print(f"    [AI] OpenRouter vision-model list nahi mil paayi, hardcoded list istemal ho rahi hai: {e}")

    _openrouter_vision_models_cache = FALLBACK_VISION_MODELS
    return _openrouter_vision_models_cache


def _images_to_data_urls(images):
    """Photo bytes (PNG/JPEG) ko OpenAI-style base64 data-URL mein badalta hai."""
    urls = []
    for img_bytes in (images or []):
        b64 = base64.b64encode(img_bytes).decode("ascii")
        urls.append(f"data:image/jpeg;base64,{b64}")
    return urls


def _call_openrouter(prompt, images=None, max_tokens=1800):
    if not OPENROUTER_API_KEY:
        raise Exception("OPENROUTER_API_KEY set nahi hai")

    models = _get_openrouter_vision_models() if images else _get_openrouter_models()

    if images:
        content = [{"type": "text", "text": prompt}]
        for data_url in _images_to_data_urls(images):
            content.append({"type": "image_url", "image_url": {"url": data_url}})
        messages = [{"role": "user", "content": content}]
    else:
        messages = [{"role": "user", "content": prompt}]

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
                    "messages": messages,
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
    """Sirf text ke liye - vision yahan istemal nahi karte."""
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
            last_error = f"{model}: {resp.text[:200]}"
        except Exception as e:
            last_error = f"{model}: {e}"

    raise Exception(f"Groq se jawab nahi mila - {last_error}")


def _get_gemini_models():
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
    models.sort(key=lambda m: 0 if "flash" in m.lower() else 1)
    _gemini_models_cache = models[:5]
    return _gemini_models_cache


def _call_gemini(prompt, images=None, max_tokens=1800):
    """Gemini khud hi multimodal hai - isliye photo(n) ko seedha isi
    ek call mein prompt ke saath bhej dete hain (koi alag vision-model
    dhoondhne ki zaroorat nahi)."""
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY set nahi hai")

    models = _get_gemini_models()

    parts = [{"text": prompt}]
    for img_bytes in (images or []):
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(img_bytes).decode("ascii"),
            }
        })

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
                    "contents": [{"parts": parts}],
                    "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
                },
                timeout=REQUEST_TIMEOUT_AI,
            )
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    result_parts = candidates[0].get("content", {}).get("parts", [])
                    if result_parts and result_parts[0].get("text"):
                        return result_parts[0]["text"]
                last_error = f"{model}: khaali jawab mila"
                continue
            if resp.status_code == 429:
                last_error = f"{model}: rate limit (429)"
                continue
            last_error = f"{model}: {resp.text[:200]}"
        except Exception as e:
            last_error = f"{model}: {e}"

    raise Exception(f"Gemini se jawab nahi mila - {last_error}")


def _call_ai(prompt, images=None, max_tokens=2800):
    """
    Pehle OPENROUTER try karta hai, na ho to GROQ (sirf text ke liye),
    na ho to GEMINI (aakhri backup, text aur photo dono ke liye).

    Agar images diye gaye hain (vision mode), to Groq ko chhod dete hain
    (uska free vision support bharosemand nahi) - sirf OpenRouter aur
    Gemini try hote hain.
    """
    errors = []

    if OPENROUTER_API_KEY:
        try:
            return _call_openrouter(prompt, images=images, max_tokens=max_tokens)
        except Exception as e:
            errors.append(f"OpenRouter: {e}")
            print(f"    [AI] OpenRouter fail hua, agla provider try kar rahe hain... ({e})")

    if not images and GROQ_API_KEY:
        try:
            return _call_groq(prompt, max_tokens=max_tokens)
        except Exception as e:
            errors.append(f"Groq: {e}")
            print(f"    [AI] Groq fail hua, Gemini try kar rahe hain... ({e})")

    if GEMINI_API_KEY:
        try:
            return _call_gemini(prompt, images=images, max_tokens=max_tokens)
        except Exception as e:
            errors.append(f"Gemini: {e}")

    if not errors:
        raise Exception("Koi bhi AI key nahi mili - Railway Variables mein OPENROUTER_API_KEY (ya GROQ_API_KEY/GEMINI_API_KEY) daalein")

    raise Exception(" | ".join(errors))


# JSON ka poora "shape" - text aur vision, dono prompt isi ek hi
# structure ka istemal karte hain (taaki aage ka processing code common ho)
_JSON_SHAPE = """{{
  "title": "poora, spasht, SEO-friendly Hindi post title",
  "slugTitle": "sirf ANGREZI (English) mein, chhote akshar, hyphen se jude 4-8 shabd - jaise 'isro-scientist-engineer-recruitment-2026' - URL ke liye, kabhi Hindi mat likhna is field mein",
  "status": "job ya admit_card ya answer_key ya result ya final_selection",
  "organization": "vibhag/sanstha ka poora naam",
  "vacancy": "sabhi post milakar TOTAL number ya N/A",
  "jobLocation": "jaise 'All India / पूरे भारत में' ya 'Uttar Pradesh' - jahan yeh bharti lagu hoti hai",
  "eligibilitySummary": "1-2 line mein chhota summary",
  "eligibilityDetails": "poori shiksha yogyata, age limit, age relaxation - har point naye line mein",
  "howToApply": "aavedan karne ke step-by-step tareeke, har step naya line mein (jaise: 1. Official website kholein 2. Registration karein...)",
  "applicationFeeGeneral": "General/OBC candidates ki fee, jaise '₹100' - na mile to khaali",
  "applicationFeeScst": "SC/ST/PH candidates ki fee - na mile to khaali",
  "applicationFeePaymentMode": "payment kaise karein, jaise 'Online (Debit Card/Net Banking)' - na mile to khaali",
  "salaryText": "pay scale, jaise 'Level 4 (₹25,500 - ₹81,100)' - na mile to khaali",
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
  "vacancyDetails": [
    {{"postName": "post ka naam", "totalPosts": 0, "eligibility": "isi post ki alag shiksha yogyata (agar diye gaye text mein alag-alag post ke liye alag yogyata likhi ho)"}}
  ],
  "categoryWiseVacancy": {{
    "ur": 0, "ews": 0, "obc": 0, "sc": 0, "st": 0, "total": 0
  }},
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
}}"""

_COMMON_RULES = """SAKHT NIYAM:
- Sirf woh jaankari do jo tumhe diye gaye text/photo mein maujood hai ya usse seedha nikaali ja sakti hai. Koi bhi tareekh, sankhya, ya fact khud se mat banao/andaza mat lagao.
- Agar koi field ki jaankari bilkul na mile, to text wale fields mein "जानकारी उपलब्ध नहीं है" likho. Date wale fields mein jaankari na mile to seedha null likho, aur uske "Note" wale field mein agar kuch likha ho to wahi likho, warna khaali chhod do.
- "vacancyDetails" array mein SIRF tabhi kai entry banao jab text/photo mein sach mein alag-alag post-naam ke saath alag vacancy-sankhya di gayi ho (jaise "Constable - 500 pad, SI - 120 pad"). Agar sirf EK total sankhya di gayi ho (post-naam ke bina alag-alag breakup ke), to array mein sirf EK hi entry banao (poore bharti ka naam post-name mein daal kar).
- "categoryWiseVacancy" SIRF tabhi bharo jab UR/EWS/OBC/SC/ST jaisi reservation-wise table sach mein maujood ho - koi bhi number na mile to poora object 0 ki jagah khaali/null values ke saath do ya poora field hi mat bhejo.
- FAQ mein sirf woh sawaal-jawab likho jinka jawab tumhe diye gaye text/photo mein SEEDHA maujood hai - kam se kam 5, agar itne na bane to jitne bhi sach mein bane utne hi likho.
- Professional Hindi bhasha, common English shabd (Apply Online, Admit Card) chalenge.
- Sirf JSON format mein jawab do - koi extra text, koi markdown backticks, koi preamble nahi.

"links" ke "type" field ke liye SIRF yahi 5 value istemal karo (jo lagu ho wahi jodo, sabhi zaroori nahi): "Apply Online", "Download Admit Card", "Check Result", "Official Notification", "Official Website\""""

PROMPT_TEMPLATE = (
    "Tum \"Official Sarkari Patrika\" naam ke sarkari naukri suchna portal ke liye ek professional "
    "content editor ho. Neeche ek raw/kaccha notice text diya gaya hai. Isse ek saaf, professional, "
    "accurate, SEO-optimized Hindi job-post mein badlo - bilkul Sarkari Result jaisi professional "
    "websites jaisa, jisme HAR field bhari ho (sirf title-link nahi, poori detail).\n\n"
    + _COMMON_RULES
    + "\n\nJSON FORMAT:\n" + _JSON_SHAPE
    + "\n\nRAW NOTICE TEXT:\n\"\"\"\n{raw_text}\n\"\"\""
)

IMAGE_PROMPT_TEMPLATE = (
    "Tum \"Official Sarkari Patrika\" naam ke sarkari naukri suchna portal ke liye ek professional "
    "content editor ho. Tumhe neeche ek ya kai photo(n) ke roop mein ek sarkari naukri/bharti ki "
    "OFFICIAL NOTIFICATION di gayi hai (yeh ek scanned document ya photo hai). Pehle in photo(n) mein "
    "likha SAARA text (Hindi ya English, jo bhi ho) dhyan se padho, phir usse ek saaf, professional, "
    "accurate, SEO-optimized Hindi job-post mein badlo - bilkul Sarkari Result jaisi professional "
    "websites jaisa, jisme HAR field bhari ho.\n\n"
    + _COMMON_RULES
    + "\n\nJSON FORMAT:\n" + _JSON_SHAPE
    + "\n\n(Agar kuch additional page-text bhi diya gaya ho to usse bhi photo ke saath milakar istemal "
    "karo)\n\nADDITIONAL PAGE TEXT (agar koi ho):\n\"\"\"\n{raw_text}\n\"\"\""
)


def _extract_json_object(text):
    """
    AI ke jawab se JSON nikaalta hai - pehle seedhe parse karne ki koshish,
    na ho to markdown-fence hata kar, na ho to sabse bada {{...}} block
    dhoondh kar (agar AI ne niyam todkar aage-peeche kuch extra likh diya
    ho). Teen tareeke - taaki chhoti si gadbad se bhi poora post fail na ho.
    """
    cleaned = text.strip()

    # Tareeka 1: seedha
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Tareeka 2: markdown code-fence hata kar
    fenced = re.sub(r"^```json", "", cleaned, flags=re.IGNORECASE).strip()
    fenced = re.sub(r"^```", "", fenced).strip()
    fenced = re.sub(r"```$", "", fenced).strip()
    try:
        return json.loads(fenced)
    except json.JSONDecodeError:
        pass

    # Tareeka 3: text ke beech mein se sabse bada {...} block nikaal kar
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise Exception("AI ka jawab valid JSON nahi tha (teeno tareeke fail hue)")


def generate_structured_post(bundle):
    """
    Bundle {"text": str, "images": [bytes,...]} leta hai, sahi AI path
    (text ya vision) chunta hai, aur structured JSON (Python dict) deta hai.

    FAISLA: agar behtar-khaasa text (>=400 characters) mil chuka hai, to
    text-only path istemal karte hain (tez, sasta, zyada bharosemand).
    Warna agar photo(n) maujood hain, to vision path istemal karte hain.
    Dono na ho to jo bhi thoda-bahut text hai usi se kaam chalate hain.
    """
    text = (bundle or {}).get("text", "") or ""
    images = (bundle or {}).get("images", []) or []

    if len(text) >= 400 or not images:
        prompt = PROMPT_TEMPLATE.format(raw_text=text[:8000] or "(koi text nahi mila)")
        raw_response = _call_ai(prompt, images=None, max_tokens=2800)
    else:
        prompt = IMAGE_PROMPT_TEMPLATE.format(raw_text=text[:3000] or "(koi additional text nahi)")
        raw_response = _call_ai(prompt, images=images[:3], max_tokens=2800)

    return _extract_json_object(raw_response)


def generate_structured_post_with_retry(bundle, attempts=2):
    """
    🛡️ SURAKSHA ROUND: agar pehli koshish (kisi bhi wajah se - AI timeout,
    rate-limit, tooti JSON) fail ho jaaye, to thodi der रुककर ek aur
    poori koshish karta hai, tabhi jaakar haar maanta hai.
    """
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return generate_structured_post(bundle)
        except Exception as e:
            last_error = e
            print(f"    [AI] Koshish {attempt}/{attempts} fail hui: {e}")
            if attempt < attempts:
                time.sleep(5)
    raise last_error


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


def make_unique_slug(title, slug_title_hint=None):
    """jobPost.ts schema ka isUnique rule sirf Studio UI mein chalta hai,
    API se likhte waqt nahi - isliye yahan khud check karte hain taaki
    do posts ka slug kabhi takrayein nahi."""
    base = slugify(slug_title_hint) if slug_title_hint else ""
    if not base:
        base = slugify(title)
    if not base:
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
    """AI kabhi-kabhi ek field ko string ki jagah list mein bhej deta hai.
    Yeh function dono format ko hamesha ek plain string mein badal deta
    hai - taaki aage koi bhi .split()/.strip() wala code kabhi crash na ho."""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if item)
    return str(value) if value else ""


def _as_number(value):
    """AI se mila number kabhi string ("500") ya kabhi khud number (500)
    ho sakta hai - dono ko safe tarike se int mein badalta hai, na ban
    paaye to None deta hai (kabhi crash nahi)."""
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", "").strip()
            if not value or not value.lstrip("-").isdigit():
                return None
        return int(value)
    except (ValueError, TypeError):
        return None


def _text_to_blocks(text):
    """Plain text (har line ek point) ko Sanity ke Portable Text block
    format mein badalta hai - jobPost.ts ke 'description' field ke liye."""
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


VALID_LINK_TYPES = [
    "Apply Online", "Download Admit Card", "Check Result",
    "Official Notification", "Official Website",
]


def _build_links_array(links_list):
    """AI se mile links ko Sanity ke importantLinks array format mein badalta hai."""
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
    """AI se mile FAQ ko customSectionsAfterLinks ke andar ek proper section banata hai."""
    content_blocks = []
    for item in (faqs_list or []):
        if not isinstance(item, dict):
            continue
        question = _as_text(item.get("question")).strip()
        answer = _as_text(item.get("answer")).strip()
        if not question or not answer:
            continue
        content_blocks.append({
            "_type": "block", "_key": _random_key(), "style": "normal",
            "children": [{"_type": "span", "_key": _random_key(),
                           "text": f"प्रश्न: {question}", "marks": ["strong"]}],
        })
        content_blocks.append({
            "_type": "block", "_key": _random_key(), "style": "normal",
            "children": [{"_type": "span", "_key": _random_key(), "text": f"उत्तर: {answer}"}],
        })

    if not content_blocks:
        return None

    return {
        "_type": "object", "_key": _random_key(),
        "heading": "अक्सर पूछे जाने वाले प्रश्न (FAQ)",
        "content": content_blocks,
    }


def _build_custom_section(heading, text):
    """Eligibility, How-to-Apply jaisi cheezon ko ek proper section (heading + content) banata hai."""
    text = _as_text(text).strip()
    if not text or text == "जानकारी उपलब्ध नहीं है":
        return None
    content_blocks = _text_to_blocks(text)
    if not content_blocks:
        return None
    return {"_type": "object", "_key": _random_key(), "heading": heading, "content": content_blocks}


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _valid_date(value):
    """AI se mili date ko check karta hai - sirf sahi 'YYYY-MM-DD' format
    (aur asli calendar date) ho tabhi use karte hain, warna None."""
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
    """AI se mile importantDates ko Sanity ke format mein badalta hai."""
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


def _clean_short_text(value):
    """Chhote text fields ke liye - agar AI ne 'जानकारी उपलब्ध नहीं है' likh diya to khaali string deta hai."""
    value = _as_text(value).strip()
    if not value or value == "जानकारी उपलब्ध नहीं है":
        return ""
    return value


def _build_category_wise_vacancy(cw_dict):
    """
    🆕 UR/EWS/OBC/SC/ST wali reservation-table banata hai. Sirf tabhi
    kuch return karta hai jab kam-se-kam EK valid number mila ho - warna
    None (taaki khaali/sab-zero table website par na dikhe).
    """
    if not isinstance(cw_dict, dict):
        return None

    keys = ["ur", "ews", "obc", "sc", "st", "total"]
    result = {}
    any_value = False
    for key in keys:
        num = _as_number(cw_dict.get(key))
        if num is not None and num > 0:
            result[key] = num
            any_value = True

    return result if any_value else None


def _build_vacancy_details_array(vacancy_list, fallback_title, fallback_eligibility, fallback_vacancy_raw):
    """
    🆕 Ek bharti mein kai alag-alag post (jaise Constable/SI, har ek ki
    alag vacancy/eligibility) ho sakte hain - AI se mile array ko Sanity
    format mein badalta hai. Agar AI ne array nahi diya (ya khaali diya),
    to purana tareeka (poore post ka EK entry, total number ke saath)
    istemal karte hain - taaki kabhi khaali na jaaye.
    """
    result = []
    for item in (vacancy_list or []):
        if not isinstance(item, dict):
            continue
        post_name = _as_text(item.get("postName")).strip()
        total_posts = _as_number(item.get("totalPosts"))
        if not post_name or total_posts is None:
            continue
        result.append({
            "_type": "object",
            "_key": _random_key(),
            "postName": post_name[:80],
            "totalPosts": total_posts,
            "eligibility": _as_text(item.get("eligibility")).strip(),
        })

    if result:
        return result

    # Fallback: purana single-entry tareeka
    if fallback_vacancy_raw.isdigit():
        return [{
            "_type": "object",
            "_key": _random_key(),
            "postName": fallback_title[:80],
            "totalPosts": int(fallback_vacancy_raw),
            "eligibility": _as_text(fallback_eligibility),
        }]

    return None


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
        "publishedAt": _now_iso(),
        "updatedAt": _now_iso(),
    }

    # IMPORTANT DATES
    important_dates = _build_important_dates(structured.get("importantDates"))
    if important_dates:
        doc["importantDates"] = important_dates

    # JOB LOCATION
    if status == "job":
        job_location = _clean_short_text(structured.get("jobLocation"))
        if job_location:
            doc["jobLocation"] = job_location[:100]

    # APPLICATION FEE
    if status == "job":
        fee_general = _clean_short_text(structured.get("applicationFeeGeneral"))
        fee_scst = _clean_short_text(structured.get("applicationFeeScst"))
        fee_mode = _clean_short_text(structured.get("applicationFeePaymentMode"))
        if fee_general or fee_scst or fee_mode:
            doc["applicationFee"] = {"general": fee_general, "scst": fee_scst, "paymentMode": fee_mode}

    # SALARY / PAY SCALE
    if status == "job":
        salary_text = _clean_short_text(structured.get("salaryText"))
        if salary_text:
            doc["salary"] = {"payScaleText": salary_text[:150]}

    # ELIGIBILITY + HOW TO APPLY - alag, proper sections ke roop mein
    before_links_sections = []
    eligibility_section = _build_custom_section(
        "पात्रता मानदंड (Eligibility Criteria)", structured.get("eligibilityDetails"),
    )
    if eligibility_section:
        before_links_sections.append(eligibility_section)

    how_to_apply_section = _build_custom_section(
        "आवेदन कैसे करें (How to Apply)", structured.get("howToApply"),
    )
    if how_to_apply_section:
        before_links_sections.append(how_to_apply_section)

    if before_links_sections:
        doc["customSectionsBeforeLinks"] = before_links_sections

    faq_section = _build_faq_section(structured.get("faqs"))
    if faq_section:
        doc["customSectionsAfterLinks"] = [faq_section]

    # 🆕 VACANCY DETAILS - ab kai alag post (multi-post) support karta hai,
    # aur agar woh na mile to purana single-entry fallback
    # 🆕 CATEGORY-WISE VACANCY (UR/EWS/OBC/SC/ST) - result post mein yeh
    # section schema mein hi hidden hai, isliye result ke liye nahi bharte
    if status != "result":
        eligibility_summary = _as_text(
            structured.get("eligibilitySummary") or structured.get("eligibilityDetails")
        )
        vacancy_details = _build_vacancy_details_array(
            structured.get("vacancyDetails"), title, eligibility_summary, vacancy_raw,
        )
        if vacancy_details:
            doc["vacancyDetails"] = vacancy_details

        category_wise = _build_category_wise_vacancy(structured.get("categoryWiseVacancy"))
        if category_wise:
            doc["categoryWiseVacancy"] = category_wise

    # BANNER: Post ke status ke hisaab se automatic banner banakar seedha
    # "featuredImage" field mein laga dete hain
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
    uski asset _id wapas deta hai."""
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

def publish_scraped_post(content, source_link):
    """
    Bundle {"text": str, "images": [bytes,...]} (ya, purana style se,
    sirf ek plain text string bhi chalegi - backward-compatible) leta
    hai -> AI se structure karwaata hai (do-round retry ke saath) ->
    Sanity mein DRAFT bana deta hai.
    """
    if isinstance(content, str):
        bundle = {"text": content, "images": []}
    else:
        bundle = content or {"text": "", "images": []}

    structured = generate_structured_post_with_retry(bundle, attempts=2)
    result = create_draft_job_post(structured, source_link)
    return result
