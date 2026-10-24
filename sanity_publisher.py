# sanity_publisher.py
#  NAYI FILE
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
import time
import random
import threading
import hashlib
import requests
from urllib.parse import urlparse

#  Aadhikarik (gov/nic) link nikalne wala module
from official_links import (
    collect_official_links, format_links_block, is_official_url, official_root,
)

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
    "syllabus": "Syllabus",
}

VALID_STATUSES = set(CATEGORY_TITLE_BY_STATUS.keys())


# ============================================================================
# HISSA 1: AI se raw text ko structured JSON mein badalna
#
#  AB DO PROVIDERS: Pehle GROQ try hota hai (tez aur free), agar woh na ho
# ya kisi wajah se fail ho jaaye, to khud-ba-khud GEMINI par switch ho jaata
# hai - isse kisi EK provider ki dikkat se poora system nahi rukta.
# ============================================================================

REQUEST_TIMEOUT_AI = 45

# ============================================================================
#  SAMAY-SEEMA (Vercel ke 280 second ke andar rehne ke liye)
# ----------------------------------------------------------------------------
# Pehle: har AI model ko 45 second, ek provider mein 5-6 models, 3 provider,
# upar se "3 baar dobara koshish" - sab milakar 280 second se bahut zyada ho
# sakta tha. Vercel beech mein hi function band kar deta tha aur dashboard par
# sirf "connect nahi ho paya" dikhta tha.
#
# Ab: webhook har request ke shuru mein ek GHADI chalu karta hai
# (start_request_clock). Har AI call se pehle bacha hua samay dekha jaata hai:
#  - har model ka timeout = min(45 sec, bacha hua samay)
#  - samay kam bacha to turant ruk jaata hai aur saaf error deta hai
# GitHub Actions wale bot mein yeh ghadi chalu nahi hoti, to wahan pehle jaisa
# hi chalta hai.
# ============================================================================
_ctx = threading.local()
AI_MIN_SECONDS = 10      # isse kam bachne par naya AI call shuru hi nahi karenge


class AIBudgetExceeded(Exception):
    """Vercel ki samay-seema ke andar AI ke liye samay nahi bacha."""


def start_request_clock(total_seconds=235):
    """AI ko poora kaam is samay tak khatam karna hai. 235 = Vercel ke 280 second
    mein se ~45 second Sanity mein save karne aur jawab bhejne ke liye surakshit."""
    _ctx.deadline = time.monotonic() + total_seconds


def clear_request_clock():
    _ctx.deadline = None


def remaining_seconds():
    deadline = getattr(_ctx, "deadline", None)
    return None if deadline is None else deadline - time.monotonic()


def _ai_timeout():
    """Agle AI request ke liye timeout. Samay kam bacha to AIBudgetExceeded."""
    remaining = remaining_seconds()
    if remaining is None:
        return REQUEST_TIMEOUT_AI
    if remaining < AI_MIN_SECONDS:
        raise AIBudgetExceeded(f"sirf {max(0, int(remaining))} second bache")
    return max(5, min(REQUEST_TIMEOUT_AI, remaining - 3))


def _vision_timeout():
    """Photo/image padhne wale AI ka timeout (pehle fix 55 second tha)."""
    remaining = remaining_seconds()
    if remaining is None:
        return 55
    if remaining < AI_MIN_SECONDS:
        raise AIBudgetExceeded(f"sirf {max(0, int(remaining))} second bache")
    return max(5, min(55, remaining - 3))


#  OPENROUTER - AB SABSE PEHLE TRY HOGA (aasaan sign-up ke liye):
# console.groq.com par account banane mein dikkat aa rahi thi, isliye
# OpenRouter jod gaya - yahan koi phone-verification nahi maangi jaati,
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
    kyunki free models ki list \u0938\u092e\u092f-\u0938\u092e\u092f \u092a\u0930 badalti rehti hai."""
    global _openrouter_models_cache
    if _openrouter_models_cache:
        return _openrouter_models_cache

    resp = requests.get("https://openrouter.ai/api/v1/models", timeout=_ai_timeout())
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
                    "temperature": 0.2,
                },
                timeout=_ai_timeout(),
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
        except AIBudgetExceeded:
            raise
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
                timeout=_ai_timeout(),
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
        except AIBudgetExceeded:
            raise
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
        timeout=_ai_timeout(),
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
                timeout=_ai_timeout(),
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
        except AIBudgetExceeded:
            raise
        except Exception as e:
            last_error = f"{model}: {e}"

    raise Exception(f"Gemini se jawab nahi mila - {last_error}")


# ============================================================================
#  KAI MUFT AI COMPANIES (taaki ek ka quota khatam ho to doosri chal jaye)
# ----------------------------------------------------------------------------
# Purane 3 (OpenRouter, Groq, Gemini) ke saath ab 3 aur: Cerebras, Mistral,
# NVIDIA. Teeno "OpenAI-compatible" hain, isliye ek hi generic function kaafi
# hai. Model ke naam har baar company se LIVE list mangwa kar chune jaate hain
# (naam badalne par code kharab nahi hota).
#
# Kaam kaise karta hai: jin companies ki key Variables mein hai, bas wahi
# istemal hoti hain. Baaree-baaree (random order mein, taaki load baante) -
# ek fail/429 to agli par. Order tay karna ho to Variables mein
#   AI_PROVIDER_ORDER = groq,cerebras,gemini,mistral,nvidia,openrouter
#   AI_SPREAD_LOAD = 0     (0 = hamesha isi order mein, 1 = random/baant kar)
# ============================================================================
OPENAI_COMPAT = {
    "cerebras": {
        "base": "https://api.cerebras.ai/v1", "key": "CEREBRAS_API_KEY",
        "prefer": ["gpt-oss-120b", "llama-3.3-70b", "qwen-3-235b", "qwen-3-32b", "llama3.1-8b"],
        "skip": ["embed"],
    },
    "mistral": {
        "base": "https://api.mistral.ai/v1", "key": "MISTRAL_API_KEY",
        "prefer": ["mistral-small-latest", "mistral-large-latest", "open-mistral-nemo", "ministral-8b"],
        "skip": ["embed", "moderation", "ocr", "codestral", "voxtral", "pixtral"],
    },
    "nvidia": {
        "base": "https://integrate.api.nvidia.com/v1", "key": "NVIDIA_API_KEY",
        "prefer": ["llama-3.3-70b", "llama-3.1-70b", "gpt-oss-120b", "qwen", "mistral-large", "nemotron", "llama-3.1-8b"],
        "skip": ["embed", "rerank", "guard", "vision", "vlm", "reward", "clip", "parse", "safety", "translate", "code", "nv-"],
    },
}
_compat_models_cache = {}


def _get_compat_models(name):
    if name in _compat_models_cache:
        return _compat_models_cache[name]
    cfg = OPENAI_COMPAT[name]
    key = os.environ.get(cfg["key"], "")
    resp = requests.get(cfg["base"] + "/models", headers={"Authorization": f"Bearer {key}"},
                        timeout=_ai_timeout())
    resp.raise_for_status()
    ids = [m.get("id", "") for m in resp.json().get("data", []) if m.get("id")]
    ids = [i for i in ids if not any(sk in i.lower() for sk in cfg["skip"])]

    def rank(model_id):
        for n, kw in enumerate(cfg["prefer"]):
            if kw in model_id.lower():
                return n
        return 99

    ids.sort(key=rank)
    picked = [i for i in ids if rank(i) < 99][:4] or ids[:3]
    if not picked:
        raise Exception("koi usable model nahi mila")
    _compat_models_cache[name] = picked
    return picked


def _call_openai_compat(name, prompt, max_tokens=1800):
    cfg = OPENAI_COMPAT[name]
    key = os.environ.get(cfg["key"], "")
    if not key:
        raise Exception(f"{cfg['key']} set nahi hai")

    last_error = "koi model try nahi hua"
    for model in _get_compat_models(name):
        try:
            resp = requests.post(
                cfg["base"] + "/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.3,
                },
                timeout=_ai_timeout(),
            )
            if resp.status_code == 200:
                text = resp.json().get("choices", [{}])[0].get("message", {}).get("content")
                if text:
                    return text
                last_error = f"{model}: khaali jawab mila"
                continue
            if resp.status_code == 429:
                last_error = f"{model}: rate limit (429)"
                continue
            last_error = f"{model}: {resp.text[:200]}"
        except AIBudgetExceeded:
            raise
        except Exception as e:
            last_error = f"{model}: {e}"

    raise Exception(f"{name} se jawab nahi mila - {last_error}")


def _available_providers():
    callers = {}
    if OPENROUTER_API_KEY:
        callers["openrouter"] = _call_openrouter
    if GROQ_API_KEY:
        callers["groq"] = _call_groq
    if GEMINI_API_KEY:
        callers["gemini"] = _call_gemini
    for pname, cfg in OPENAI_COMPAT.items():
        if os.environ.get(cfg["key"], ""):
            callers[pname] = (lambda pr, mt, _n=pname: _call_openai_compat(_n, pr, mt))
    return callers


def _call_ai(prompt, max_tokens=1800):
    """Jin AI companies ki key Variables mein hai, unhein baaree-baaree
    try karta hai - ek ka quota (429) khatam ho to agli par chala jaata hai."""
    callers = _available_providers()
    if not callers:
        raise Exception(
            "Koi bhi AI key nahi mili - Variables mein GROQ_API_KEY / GEMINI_API_KEY / "
            "CEREBRAS_API_KEY / MISTRAL_API_KEY / NVIDIA_API_KEY / OPENROUTER_API_KEY mein se "
            "kam se kam ek daalein"
        )

    order = [x.strip().lower() for x in
             os.environ.get("AI_PROVIDER_ORDER", "groq,cerebras,gemini,mistral,nvidia,openrouter").split(",")
             if x.strip()]
    names = [n for n in order if n in callers] + [n for n in callers if n not in order]
    if os.environ.get("AI_SPREAD_LOAD", "1") == "1" and len(names) > 1:
        random.shuffle(names)      # load baante - ek company ka quota jaldi khatam na ho

    errors = []
    for pname in names:
        try:
            return callers[pname](prompt, max_tokens)
        except AIBudgetExceeded:
            raise
        except Exception as e:
            errors.append(f"{pname}: {e}")
            print(f"    [AI] {pname} fail hua, agli company try kar rahe hain... ({e})")

    raise Exception(" | ".join(errors))


PROMPT_TEMPLATE = """You are a professional content editor for "Official Sarkari Patrika", an Indian government job and exam information portal. Below is a raw notice text. Turn it into a clean, accurate, SEO-optimised post in SIMPLE INDIAN ENGLISH - like professional portals such as Sarkari Result or Free Job Alert - with EVERY field filled (not just a title and link, but full detail).

STRICT RULES:
- Use ONLY facts that are present in the text below or can be taken directly from it. Never invent or guess any date, number, fee or fact.
- LANGUAGE (MOST IMPORTANT): write everything in SIMPLE, PLAIN INDIAN ENGLISH - the English used in Indian government notices and Indian newspapers. Short, clear sentences. Everyday words (use "apply", not "submit your candidature"). Indian style: Rs/rupee amounts like "Rs 100" or "Rs 25,500", "lakh/crore", dates like "18 November 2026". Write in the English alphabet only: no Hindi, no Hinglish, no other language or script. The only exception is the field "jobLocation" when it is "All India".
- If a "Title:" line is given, use it for the "title" field (you may improve it for SEO, but do not invent a completely new title unless no real title is available).
- If a "Likely Status:" is given, use THAT status unless the content below clearly says a different one (for example Likely Status is 'job' but the text clearly says 'Result Declared', then choose 'result'). Never assume 'job' just because you are unsure - treat Likely Status as the default.
- "aboutOrganization": you may use general knowledge here (for well-known bodies like SSC, UPSC, Railway). If the organisation is unknown, write one generic professional line (for example "This is a recognised department of the Government of India / a State Government.").
- If a text field has no information at all, write "Information not available" - EXCEPT "eligibilityDetails", "howToApply" and "faqs", which you must ALWAYS fill (see below). For date fields ("YYYY-MM-DD") write null when the date is not in the text (never invent one); if the text gives a note instead (for example "to be announced soon"), put that in the matching "Note" field, otherwise leave the Note empty.
- FAQs: ALWAYS give at least 5. First give questions whose answers are DIRECTLY in the text (vacancy, last date, fee, eligibility, selection). If you still have fewer than 5, add questions whose answers are always true for this kind of government notice (how to apply, where is the official website, which documents are needed, what is the selection process, where to check the official notification). Never invent a new date, number or fee in these - write "please check the official notification" instead. Never answer "Information not available".
- "jobLocation": NEVER leave empty. If the text names no single state or city, write "All India".
- "eligibilityDetails": write all education, age limit and age relaxation details found (even if incomplete), one point per line. If the text has nothing at all, write "Full eligibility details (educational qualification and age limit) are given in the official notification." plus any hints you can find. Never leave it empty.
- "howToApply": ALWAYS fill. If the text has no steps, write the standard steps for this kind of notice (open the official website, read the notification, register or log in, fill the form, upload documents, pay the fee, submit and print) - without inventing any date or fee. One step per line.
- SEO ("seoMetaTitle", "seoMetaDescription") is VERY IMPORTANT because it decides Google ranking. The title must contain the full organisation/exam name + post type (Job / Admit Card / Result) + the year. The description must be clear, specific and click-worthy (no keyword stuffing). Never generic or empty.
- "description" is a FULL SUMMARY written for the status: for a Job - post, department, vacancies, eligibility, important dates overview; for an Admit Card - which exam, when released, exam date; for a Result - which exam, when declared, next step. At least 4-5 good points, one per line.
- "links": the text starts with a block called "OFFICIAL LINKS FOUND ON THE PAGE". Use ONLY URLs from that block (type must be one of: Apply Online / Download Admit Card / Check Result / Official Notification / Official Website). NEVER invent a URL and never give a link to a private website (such as Sarkari Result or Free Job Alert). If the block says "NONE FOUND", use "links": [].
- "shortSummary" (shown as "Short Details" at the top of the post): 5-6 short, simple English sentences, 330 to 430 characters in total. First sentence: which organisation released what (recruitment / admit card / result). Then total posts, start and last date of application, a short hint on eligibility, one or two points on fee or selection, and in the last sentence where to apply or download. Use only real facts from the text. NO URL, emoji or hashtag. Do not copy the title. Do not write anything that is not in the text.
- "organization": the most common, short, standard name (for example "SSC", "UPSSSC", "UPSC", "Railway (RRB)", "IBPS", "BPSC", "DSSSB") - the same name every time for the same body.
- Reply ONLY in the JSON format below - no extra text, no markdown backticks, no preamble.

JSON FORMAT:
{{
  "title": "full, clear, SEO-friendly English post title",
  "slugTitle": "ENGLISH only, lower case, 4-8 words joined by hyphens, for the URL - for example 'isro-scientist-engineer-recruitment-2026'",
  "status": "one of: job, admit_card, answer_key, result, final_selection - treat the given 'Likely Status' as default",
  "organization": "short standard name of the department (for example SSC, UPSSSC, Railway (RRB)) - same every time",
  "shortSummary": "5-6 short simple English sentences, 330-430 characters in total, only facts from the text, no link/emoji",
  "aboutOrganization": "2-4 lines of professional information about this department (general knowledge is fine)",
  "vacancy": "only a number, or N/A",
  "jobLocation": "for example 'All India' or 'Uttar Pradesh' - where this notice applies",
  "eligibilitySummary": "1-2 line short summary (only for the vacancy table)",
  "eligibilityDetails": "complete educational qualification, age limit and age relaxation - simple English, one point per line",
  "howToApply": "steps to apply / download, simple English, one step per line - for example: 1. Open the official website 2. Register 3. Fill the form",
  "applicationFeeGeneral": "fee for General/OBC candidates, for example 'Rs 100' - empty if not given",
  "applicationFeeScst": "fee for SC/ST/PH candidates - empty if not given",
  "applicationFeePaymentMode": "how to pay, for example 'Online (Debit Card / Net Banking)' - empty if not given",
  "salaryText": "pay scale, for example 'Level 4 (Rs 25,500 - Rs 81,100)' - empty if not given",
  "salaryMin": "only a number, for example 25500 - empty if not given",
  "salaryMax": "only a number, for example 81100 - empty if not given",
  "categoryWiseVacancy": {{
    "ur": "only a number - empty if not given",
    "ews": "only a number - empty if not given",
    "obc": "only a number - empty if not given",
    "sc": "only a number - empty if not given",
    "st": "only a number - empty if not given",
    "total": "only a number - empty if not given"
  }},
  "admitCardInfo": "ONLY if status is admit_card: how to download and what to carry to the exam centre - simple English",
  "resultInfo": "ONLY if status is result or final_selection: how to check the result and the next step - simple English",
  "importantDates": {{
    "applicationStart": "YYYY-MM-DD or null",
    "applicationStartNote": "short note if there is no exact date, otherwise empty",
    "applicationEnd": "YYYY-MM-DD or null",
    "applicationEndNote": "short note if there is no exact date, otherwise empty",
    "admitCardDate": "YYYY-MM-DD or null",
    "admitCardDateNote": "short note if there is no exact date, otherwise empty",
    "examDate": "YYYY-MM-DD or null",
    "examDateNote": "short note if there is no exact date, otherwise empty",
    "resultDate": "YYYY-MM-DD or null",
    "resultDateNote": "short note if there is no exact date, otherwise empty"
  }},
  "description": "4-7 key points, one per line, simple English",
  "links": [
    {{"label": "short English label", "url": "http...", "type": "Apply Online"}},
    {{"label": "short English label", "url": "http...", "type": "Official Notification"}},
    {{"label": "short English label", "url": "http...", "type": "Official Website"}}
  ],
  "faqs": [
    {{"question": "question in simple English", "answer": "direct answer in simple English"}}
  ],
  "seoMetaTitle": "best SEO title - in the words people type in Google (for example 'UPSSSC Junior Assistant Admit Card 2026 Download': organisation/exam name + post type + year). Under 60 characters, main keyword first.",
  "seoMetaDescription": "clear, click-worthy Google description in simple English with the key words (Admit Card, Apply Online, Result): organisation, post/exam, what to do, and the date. Under 160 characters, no keyword stuffing."
}}

For "links", the "type" field must be ONE of these 5 values only (use only those that apply, not all are needed): "Apply Online", "Download Admit Card", "Check Result", "Official Notification", "Official Website"

RAW NOTICE TEXT:
\"\"\"
{raw_text}
\"\"\""""


def _repair_json_text(text):
    """Kai chhoti-chhoti common AI-generated JSON galtiyon ko theek
    karne ki koshish karta hai - jaise } ya ] se pehle faaltu comma,
    ya do values ke beech comma ka chhoot jaana. Yeh sirf ek AAKHRI
    koshish hai, pehle seedhe strict=False try ho chuka hota hai."""
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    text = re.sub(r'([\"\d\}\]])(\s*)\n(\s*\")', r"\1,\2\n\3", text)
    return text


def _try_parse_ai_json(raw_response):
    """Ek AI response ko JSON mein badalne ki poori koshish karta hai
    (cleanup + strict=False + chhoti syntax galtiyan theek karna).
    Safal ho to dict deta hai, warna None (exception nahi uthata -
    caller ise retry ke liye istemal karta hai)."""
    cleaned = raw_response.strip()
    cleaned = re.sub(r"^```json", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^```", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]

    try:
        return json.loads(cleaned, strict=False)
    except json.JSONDecodeError:
        pass

    try:
        return json.loads(_repair_json_text(cleaned), strict=False)
    except json.JSONDecodeError:
        return None


def generate_structured_post(raw_text):
    """Raw scraped text leta hai, AI se structured JSON banwa kar
    Python dict return karta hai.

    \U0001f195 SURAKSHA: AI kabhi-kabhi ek hi baar mein poora sahi JSON nahi
    de paata (ek chhoti si comma/quote ki galti se). Isliye agar
    pehli koshish fail ho, to khud-ba-khud 3 baar tak dobara try
    karte hain (user ko pata bhi nahi chalega, bas thoda time lagega)
    - isse yeh error lagbhag kabhi bhi user tak nahi pahunchti."""
    prompt = PROMPT_TEMPLATE.format(raw_text=raw_text[:8000])

    last_error = "koi jawab nahi mila"
    for attempt in range(1, 4):
        try:
            raw_response = _call_ai(prompt, max_tokens=3800)
        except AIBudgetExceeded as e:
            #  Samay-seema khatam - aur koshish nahi, seedha saaf error
            raise Exception(
                f"AI ko jawab dene ka samay nahi bacha ({e}). AI models dheere chal rahe hain - "
                f"1-2 minute baad dobara 'Draft banayein' dabayein. (Koshish {attempt}/3)"
            )
        except Exception as e:
            last_error = str(e)
            print(f"    [AI] Koshish {attempt}/3: AI call hi fail hua ({e}), dobara try kar rahe hain...")
            continue

        parsed = _try_parse_ai_json(raw_response)
        if parsed is not None:
            return parsed

        last_error = "AI ka jawab valid JSON mein convert nahi ho paaya"
        print(f"    [AI] Koshish {attempt}/3: JSON galat aaya, dobara try kar rahe hain...")

    hint = ""
    if "429" in last_error or "rate limit" in last_error.lower():
        hint = " | SUJHAV: sabhi AI ki muft seema (quota) khatam lag rahi hai - kuch der baad dobara karein, ya Variables mein aur AI companies ki key jodein (Groq/Cerebras/Mistral/NVIDIA/Gemini)"
    raise Exception(f"AI se 3 koshishon ke baad bhi sahi jawab nahi mila - {last_error}{hint}")


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

    \U0001f527 FIX 1: Hindi (Devanagari) title se slugify() karne par sab akshar
    hat jaate hain aur khaali/'post' jaisa bekaar slug ban jaata tha -
    ab caller (_compute_base_slug) English slug-hint ko priority deta hai.

    \U0001f527 FIX 2: 'exclude_doc_id' pass karne se, agar SAME post dobara
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


# ============================================================================
#  ORGANIZATION MATCHING (duplicate Organization rokne ke liye)
# Pehle har naye naam par nayi Organization ban jaati thi (SSC / Staff Selection
# Commission / SSC (Staff Selection Commission) - sab alag). Ab pehle maujooda
# Organization mein se sabse sahi wali dhoondhi jaati hai. Na mile tabhi nayi
# Organization banti hai (ORG_AUTO_CREATE=0 se purana 'Other Departments' tareeka).
# ============================================================================
FALLBACK_ORG_ID = "org-other-departments"
FALLBACK_ORG_NAME = "Other Departments"


def _org_parts(name):
    """Naam se (normalized text, acronyms ka set, bina-acronym wale shabd) nikalta hai."""
    raw = _as_text(name).strip()
    acronyms = set(re.findall(r"\b[A-Z][A-Z0-9]{1,9}\b", raw))
    norm = " ".join(re.sub(r"[^0-9a-z\u0900-\u097f]+", " ", raw.lower()).split())
    acr_lower = {a.lower() for a in acronyms}
    core = " ".join(w for w in norm.split() if w not in acr_lower)
    return norm, acronyms, core


def _is_contained(short, long_):
    return bool(short) and f" {short} " in f" {long_} "


_ORG_STOPWORDS = {"of", "the", "and", "for", "in", "a", "an", "&"}


def _initials(core):
    """'staff selection commission' -> 'ssc'; 'rajasthan university of health sciences' -> 'ruhs'"""
    words = [w for w in core.split() if w not in _ORG_STOPWORDS]
    return "".join(w[0] for w in words if w and w[0].isascii())


def _orgs_match(ai_name, existing_name):
    a_norm, a_acr, a_core = _org_parts(ai_name)
    e_norm, e_acr, e_core = _org_parts(existing_name)
    if not a_norm or not e_norm:
        return False
    if a_norm == e_norm:
        return True

    # Ek taraf SIRF acronym ("SSC") aur doosri taraf poora naam: tabhi match jab
    # acronym poore naam ke shabdon ke pehle akshar se banta ho
    # (Staff Selection Commission -> SSC ; 'Bihar SSC' ya 'UP SSC' -> match NAHI)
    if not a_core and len(a_acr) == 1 and e_core:
        if any(x.lower() == _initials(e_core) for x in a_acr):
            return True
    if not e_core and len(e_acr) == 1 and a_core:
        if any(x.lower() == _initials(a_core) for x in e_acr):
            return True

    shared = a_acr & e_acr
    if shared:
        # lamba/khaas acronym (DSSSB, UPSSSC, RSMSSB...) - kaafi pakka sanket
        if any(len(x) >= 4 for x in shared):
            return True
        # chhota acronym (SSC, RRB...) - dono taraf shabd hon to ek doosre mein samaye hon
        if a_core and e_core:
            return _is_contained(a_core, e_core) or _is_contained(e_core, a_core)
        return False

    # acronym nahi - poora naam (kam se kam 2 shabd) ek doosre mein samaya ho
    short, long_ = (a_norm, e_norm) if len(a_norm) <= len(e_norm) else (e_norm, a_norm)
    return len(short.split()) >= 2 and _is_contained(short, long_)


def _ensure_fallback_org():
    doc = {
        "_id": FALLBACK_ORG_ID,
        "_type": "organization",
        "name": FALLBACK_ORG_NAME,
        "slug": {"_type": "slug", "current": "other-departments"},
        "website": "https://www.india.gov.in",
    }
    _sanity_mutate([{"createIfNotExists": doc}])
    return FALLBACK_ORG_ID


def get_or_create_organization(name, fallback_website, about_text=None):
    """Pehle Sanity mein maujooda Organization dhoondhta hai (naam YA shortName
    se, jaise 'SSC' ya 'Staff Selection Commission'). Mil jaye to wahi purani
    Organization use hoti hai. SIRF tab nayi banti hai jab list mein us vibhag
    ka koi match na ho. (Purana 'Other Departments' wala tareeka chahiye to
    Vercel Variable ORG_AUTO_CREATE=0 rakhein.)"""
    name = _as_text(name).strip()

    orgs = _sanity_query('*[_type == "organization"]{_id, name, shortName}') or []
    published_ids = {o.get("_id") for o in orgs if not o.get("_id", "").startswith("drafts.")}
    if name:
        best = None
        for org in orgs:
            oid = org.get("_id", "")
            candidates = [org.get("name", ""), org.get("shortName", "")]
            if any(c and _orgs_match(name, c) for c in candidates):
                # published wali ko draft wali par tarjeeh
                base_id = oid[len("drafts."):] if oid.startswith("drafts.") else oid
                chosen = base_id if base_id in published_ids else oid
                best = chosen
                if not oid.startswith("drafts."):
                    break
        if best:
            return best

    if os.environ.get("ORG_AUTO_CREATE", "1") == "0":
        print(f"    [ORG] '{name}' ka koi match nahi mila - 'Other Departments' laga rahe hain")
        return _ensure_fallback_org()

    name = name or "Sarkari Vibhag"
    print(f"    [ORG] '{name}' list mein nahi mila - nayi Organization bana rahe hain")
    org_id = f"org-{hashlib.md5(name.encode()).hexdigest()[:12]}"
    org_slug = slugify(name) or org_id
    doc = {
        "_id": org_id,
        "_type": "organization",
        "name": name,
        "slug": {"_type": "slug", "current": org_slug},
        "website": fallback_website or "https://www.india.gov.in",
    }
    if re.fullmatch(r"[A-Z][A-Z0-9 ()&.-]{1,14}", name):
        doc["shortName"] = name
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
    liye zaroori). \U0001f527 FIX: text agar list ho (AI kabhi aisa bhej deta
    hai) to pehle usse string mein badal lete hain, warna .split() par
    crash ho jaata tha."""
    text = _as_text(text)
    blocks = []
    for line in text.split("\n"):
        line = line.strip().lstrip("-\u2022").strip()
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


LINK_LABEL = {
    "Apply Online": "Apply Online",
    "Download Admit Card": "Download Admit Card",
    "Check Result": "Check Result / Answer Key",
    "Official Notification": "Official Notification (PDF)",
    "Official Website": "Official Website",
}
LINK_LABEL_HI = LINK_LABEL   # old name kept so nothing else breaks


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
            "label": (
                LINK_LABEL.get(link_type, link_type)
                if _needs_english(item.get("label")) else _as_text(item.get("label")).strip()
            )[:60],
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
                "text": f"Q: {question}", "marks": ["strong"],
            }],
        })
        # Jawab - Normal
        content_blocks.append({
            "_type": "block",
            "_key": _random_key(),
            "style": "normal",
            "children": [{
                "_type": "span", "_key": _random_key(),
                "text": f"A: {answer}",
            }],
        })

    if not content_blocks:
        return None

    return {
        "_type": "object",
        "_key": _random_key(),
        "heading": "Frequently Asked Questions (FAQ)",
        "content": content_blocks,
    }


def _build_custom_section(heading, text):
    """Eligibility, How-to-Apply jaisi cheezon ko jobPost.ts ke
    'customSectionsBeforeLinks' format mein ek proper section (heading +
    content box) banata hai - description ke andar generic text ki
    jagah website par alag, saaf dikhne wala box banta hai."""
    text = _as_text(text).strip()
    if _is_blank_info(text):
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
    isse Sanity ko kabhi galat/tuta hua date bhej\u0915\u0930 400 error nahi aata."""
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
        if note and note != "\u091c\u093e\u0928\u0915\u093e\u0930\u0940 \u0909\u092a\u0932\u092c\u094d\u0927 \u0928\u0939\u0940\u0902 \u0939\u0948":
            result[note_key] = note[:100]

    return result if result else None


def _safe_int(value):
    """AI se mili sankhya ko surakshit tareeke se number mein badalta
    hai - agar woh number na ho (jaise '\u091c\u093e\u0928\u0915\u093e\u0930\u0940 \u0909\u092a\u0932\u092c\u094d\u0927 \u0928\u0939\u0940\u0902 \u0939\u0948' ya
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
    '\u091c\u093e\u0928\u0915\u093e\u0930\u0940 \u0909\u092a\u0932\u092c\u094d\u0927 \u0928\u0939\u0940\u0902 \u0939\u0948' likh diya to khaali string deta hai (taaki
    website par khaali/bekaar field na dikhe)."""
    value = _as_text(value).strip()
    if _is_blank_info(value):
        return ""
    return value


GENERIC_HOW_TO_APPLY = (
    "1. Go to the official website of the department.\n"
    "2. Click the recruitment link and read the notification carefully.\n"
    "3. If asked, register first and then log in.\n"
    "4. Fill in all the details in the application form correctly.\n"
    "5. Scan and upload the required documents, photo and signature.\n"
    "6. Pay the application fee online (if applicable).\n"
    "7. Submit the form and keep a printout for future use."
)

GENERIC_HOW_TO_DOWNLOAD_ADMIT_CARD = (
    "1. Go to the official website of the department.\n"
    "2. Click the \"Download Admit Card\" link.\n"
    "3. Enter your Registration Number / Roll Number and date of birth (or password).\n"
    "4. Your admit card will appear on the screen. Download it and take a printout.\n"
    "5. Carry the admit card and a photo ID to the exam centre."
)

GENERIC_HOW_TO_CHECK_ANSWER_KEY = (
    "1. Go to the official website of the department.\n"
    "2. Click the \"Answer Key\" link.\n"
    "3. Enter your Roll Number / Registration Number to view or download the answer key.\n"
    "4. If you have an objection to any answer, raise it online before the last date."
)

GENERIC_HOW_TO_CHECK_RESULT = (
    "1. Go to the official website of the department.\n"
    "2. Click the \"Result\" or \"Check Result\" link.\n"
    "3. Enter your Roll Number / Registration Number to see your result.\n"
    "4. Download the result and keep a printout or screenshot for future use."
)

GENERIC_HOW_TO_CHECK_SYLLABUS = (
    "1. Go to the official website of the department / exam.\n"
    "2. Click the \"Syllabus\" link.\n"
    "3. Download the PDF and read the subject-wise syllabus carefully.\n"
    "4. The Exam Pattern (number of questions, marks, time) is also given in the same PDF."
)

HOW_TO_SECTION_CONFIG = {
    "job": ("How to Apply", GENERIC_HOW_TO_APPLY),
    "admit_card": ("How to Download Admit Card", GENERIC_HOW_TO_DOWNLOAD_ADMIT_CARD),
    "answer_key": ("How to Check Answer Key", GENERIC_HOW_TO_CHECK_ANSWER_KEY),
    "result": ("How to Check Result", GENERIC_HOW_TO_CHECK_RESULT),
    "final_selection": ("How to Check Result", GENERIC_HOW_TO_CHECK_RESULT),
    "syllabus": ("How to Check Syllabus", GENERIC_HOW_TO_CHECK_SYLLABUS),
}
ELIGIBILITY_HEADING = "Eligibility Criteria"
# Old (Hindi/bilingual) headings - still recognised so older drafts can be edited
LEGACY_ELIGIBILITY_HEADINGS = {"\u092a\u093e\u0924\u094d\u0930\u0924\u093e \u092e\u093e\u0928\u0926\u0902\u0921 (Eligibility Criteria)", "Eligibility Criteria"}
LEGACY_HOWTO_HEADINGS = {
    "\u0906\u0935\u0947\u0926\u0928 \u0915\u0948\u0938\u0947 \u0915\u0930\u0947\u0902 (How to Apply)", "\u090f\u0921\u092e\u093f\u091f \u0915\u093e\u0930\u094d\u0921 \u0915\u0948\u0938\u0947 \u0921\u093e\u0909\u0928\u0932\u094b\u0921 \u0915\u0930\u0947\u0902 (How to Download)",
    "\u0909\u0924\u094d\u0924\u0930 \u0915\u0941\u0902\u091c\u0940 \u0915\u0948\u0938\u0947 \u0926\u0947\u0916\u0947\u0902 (How to Check Answer Key)", "\u092a\u0930\u093f\u0923\u093e\u092e \u0915\u0948\u0938\u0947 \u0926\u0947\u0916\u0947\u0902 (How to Check Result)",
    "\u0938\u093f\u0932\u0947\u092c\u0938 \u0915\u0948\u0938\u0947 \u0926\u0947\u0916\u0947\u0902 (How to Check Syllabus)",
} | {v[0] for v in HOW_TO_SECTION_CONFIG.values()}


def _ensure_core_links(ai_links, source_link, status, official_links=None, raw_text=""):
    """\U0001f195 PURA BADLA HUA: Important Links mein ab SIRF aadhikarik links jaate
    hain, jo post-page se asli mein nikaale gaye (ya sarkari link jo text mein
    maujood tha). Pehle jo links na milte the, unki jagah us PRIVATE site ka
    apna link (jahan se aapne post uthayi) bhar diya jaata tha - woh ab KABHI
    nahi hota. Link na mile to khana khaali rehta hai (draft summary mein
    chetavani aati hai) - galat link se behtar khaali khana.
    """
    official_links = official_links or {}
    by_type = official_links.get("by_type", {}) or {}
    all_found = official_links.get("all", []) or []
    allowed_urls = {c["url"] for c in all_found} | {c["url"] for c in by_type.values()}
    raw_text = raw_text or ""
    has_source = bool(source_link) and str(source_link).startswith("http")

    result = []
    seen_urls = set()

    def _add(url, label, link_type):
        if not url or url in seen_urls:
            return
        seen_urls.add(url)
        result.append({
            "_type": "object", "_key": _random_key(),
            "label": label, "url": url, "linkType": link_type,
        })

    primary_type = {
        "job": "Apply Online",
        "admit_card": "Download Admit Card",
        "answer_key": "Check Result",
        "result": "Check Result",
        "final_selection": "Check Result",
        "syllabus": "Official Notification",
    }.get(status, "Apply Online")

    # 1) AI ke diye links - sirf wahi jo page par sach mein mile the, ya
    #    aadhikarik domain ke hon aur text mein likhe hue hon (AI ki gadhi
    #    hui link nahi chalegi)
    for l in (ai_links or []):
        u = str(l.get("url") or "").strip()
        verified = (u in allowed_urls) or u.rstrip("/") in raw_text
        #  SIRF aadhikarik domain - koi private/platform/exam-vendor link nahi
        # sirf isi post ke status wala main link (admit card post par 'Check Result' nahi)
        main_types = {"Apply Online", "Download Admit Card", "Check Result"}
        other_main = l.get("linkType") in main_types and l.get("linkType") != primary_type
        if verified and is_official_url(u) and u not in seen_urls and not other_main:
            seen_urls.add(u)
            result.append(l)
    types_present = {l.get("linkType") for l in result}

    labels = dict(LINK_LABEL)

    # 2) Page se nikale gaye aadhikarik links
    for ltype in (primary_type, "Official Notification", "Official Website"):
        if ltype in types_present:
            continue
        c = by_type.get(ltype)
        if c and c.get("official"):      #  sirf aadhikarik domain
            _add(c["url"], labels.get(ltype, ltype), ltype)
            types_present.add(ltype)

    #  Baaki aadhikarik links (Correction, Syllabus, Exam City/Status,
    # Candidate Login) - sirf aadhikarik domain wale, schema ke liye
    # linkType "Official Website" ke saath
    extra_labels = {
        "Correction Link": "Application Correction Window",
        "Syllabus": "Syllabus",
        "Exam City / Status": "Exam City / Application Status",
        "Candidate Login": "Candidate Login",
    }
    for ltype, lbl in extra_labels.items():
        c = by_type.get(ltype)
        if c and c.get("official") and c["url"] not in seen_urls:
            _add(c["url"], lbl, "Official Website")

    # Ek aur notification PDF (jaise Short Notice) agar mili ho
    for c in all_found:
        if c["type"] == "Official Notification" and c.get("official") and c["url"] not in seen_urls:
            _add(c["url"], "Additional Notice (PDF)", "Official Notification")
            break

    # 3) Agar aapne seedha SARKARI page ka link diya tha, to wahi page
    #    aadhikarik hai - use fallback maanna theek hai
    if has_source and is_official_url(source_link):
        for ltype in (primary_type, "Official Notification"):
            if ltype not in types_present:
                _add(source_link, labels.get(ltype, ltype), ltype)
                types_present.add(ltype)
        if "Official Website" not in types_present:
            root = official_root(source_link)
            if root:
                _add(root, labels["Official Website"], "Official Website")

    #  PERMANENT: WhatsApp aur Telegram channel link - har post mein
    # hamesha, chahe AI ne kuch bhi diya ho. Note: Sanity schema
    # (jobPost.ts) ke importantLinks.linkType mein abhi sirf 5 values
    # allowed hain - agar Studio mein yeh dropdown se select nahi ho
    # rahe (red dikhein), to schema mein "WhatsApp Channel" aur
    # "Telegram Channel" do options aur jodne honge.
    result.append({
        "_type": "object", "_key": _random_key(),
        "label": "Join our WhatsApp Channel",
        "url": "https://whatsapp.com/channel/0029VbC7Adf7tkj3LRmYuk0h",
        "linkType": "WhatsApp Channel",
    })
    result.append({
        "_type": "object", "_key": _random_key(),
        "label": "Join our Telegram Channel",
        "url": "https://t.me/OfficialSarkariPatrika",
        "linkType": "Telegram Channel",
    })

    return result


def _generate_fallback_faqs(structured, existing_count):
    """FAQ should always be at least 5. If the AI gave fewer, build the rest
    from data we already have (vacancy, dates, fee, organisation) plus a few
    always-true general questions. Nothing new is invented."""
    needed = max(0, 5 - existing_count)
    if needed == 0:
        return []

    candidates = []
    org = _as_text(structured.get("organization")).strip()
    vacancy = str(structured.get("vacancy") or "").strip()
    dates = structured.get("importantDates") or {}
    fee = _clean_short_text(structured.get("applicationFeeGeneral"))
    location = _clean_short_text(structured.get("jobLocation"))

    if org:
        candidates.append((
            "Which department or organisation has released this notice?",
            f"This notice has been released by {org}.",
        ))
    if vacancy and vacancy.isdigit():
        candidates.append((
            "How many posts are there in total?",
            f"There are {vacancy} posts in total.",
        ))
    if isinstance(dates, dict) and dates.get("applicationEnd"):
        candidates.append((
            "What is the last date to apply?",
            f"The last date to apply is {(_pretty_date(dates['applicationEnd']) or dates['applicationEnd'])}.",
        ))
    if isinstance(dates, dict) and dates.get("applicationStart"):
        candidates.append((
            "When will the application start?",
            f"The application starts on {(_pretty_date(dates['applicationStart']) or dates['applicationStart'])}.",
        ))
    if fee:
        candidates.append((
            "What is the application fee?",
            f"The application fee for General / OBC candidates is {fee}.",
        ))
    if isinstance(dates, dict) and dates.get("examDate"):
        candidates.append((
            "What is the exam date?",
            f"The exam will be held on {(_pretty_date(dates['examDate']) or dates['examDate'])}.",
        ))
    if location:
        candidates.append((
            "Which state or region is this notice for?",
            f"This notice is for {location}.",
        ))
    status = structured.get("status") or ""
    if status in ("result", "final_selection"):
        action_q = "Where can I check the result?"
        action_a = "You can check the result with the Check Result link given in the Important Links section."
    elif status == "admit_card":
        action_q = "Where can I download the admit card?"
        action_a = "You can download the admit card with the Download Admit Card link given in the Important Links section."
    elif status == "answer_key":
        action_q = "Where can I see the answer key?"
        action_a = "You can see the answer key with the link given in the Important Links section."
    else:
        action_q = "Where can I get more information and apply?"
        action_a = "Use the Official Website and Apply Online links given in the Important Links section to see full details and apply."
    candidates.append((action_q, action_a))

    # Always-true general questions (no new date, number or fee)
    candidates += [
        ("Which website should I use to apply or get information?",
         "Use only the official website. The link is given in the Important Links section."),
        ("Where can I find the correct eligibility and selection process?",
         "The full and correct eligibility, age limit and selection process are given in the Official Notification."),
        ("Which documents should I keep ready while filling the form?",
         "Usually you need an ID proof, educational certificates, photo, signature and category certificate. Please check the Official Notification for the exact list."),
        ("Can the details of this notice change later?",
         "Yes. The department may sometimes change a date or a rule. Please check the official website for the latest update and stay connected with our WhatsApp / Telegram channel."),
        ("How can I get such government job updates first?",
         "Join the Official Sarkari Patrika WhatsApp Channel and Telegram Channel. The links are given in the Important Links section."),
    ]

    return [{"question": q, "answer": a} for q, a in candidates[:needed]]


def _get_or_build_description(structured, status):
    """description (Post Details summary) kabhi khaali na jaaye -
    agar AI ne poori tarah nahi bhara, to available structured data
    (title, org, vacancy, dates, location, status) se ek theek-thaak
    summary khud bana lete hain, status ke hisaab se alag."""
    existing = _as_text(structured.get("description")).strip()
    # Kam se kam 3 non-empty lines hon tabhi "poora bhara hua" maante hain
    non_empty_lines = [l for l in existing.split("\n") if l.strip()]
    if len(non_empty_lines) >= 3 and _deva_ratio(existing) <= 0.2 and not _is_blank_info(existing):
        return existing

    title = _as_text(structured.get("title")).strip()
    org = _as_text(structured.get("organization")).strip()
    vacancy = str(structured.get("vacancy") or "").strip()
    location = _clean_short_text(structured.get("jobLocation")) or "All India"
    if _deva_ratio(location) > 0.2:
        location = "All India"
    dates = structured.get("importantDates") or {}

    lines = []
    if org:
        lines.append(f"This notice has been released by {org}.")
    if title:
        lines.append(f"Full details of {title} are given below.")
    if vacancy and vacancy.isdigit():
        lines.append(f"There are {vacancy} posts in total.")
    lines.append(f"This opportunity is open to candidates from {location}.")

    if status == "job":
        if isinstance(dates, dict) and dates.get("applicationEnd"):
            lines.append(f"The last date to apply is {(_pretty_date(dates['applicationEnd']) or dates['applicationEnd'])}.")
        lines.append("Eligibility, application fee and how to apply are explained below.")
    elif status == "admit_card":
        lines.append("The steps to download the admit card are given below.")
        if isinstance(dates, dict) and dates.get("examDate"):
            lines.append(f"The exam will be held on {(_pretty_date(dates['examDate']) or dates['examDate'])}.")
    elif status == "answer_key":
        lines.append("How to see the answer key and raise an objection is explained below.")
    elif status in ("result", "final_selection"):
        lines.append("How to check the result and what to do next is explained below.")
        if isinstance(dates, dict) and dates.get("resultDate"):
            lines.append(f"The result was declared on {(_pretty_date(dates['resultDate']) or dates['resultDate'])}.")
    elif status == "syllabus":
        lines.append("The full syllabus and exam pattern can be downloaded from the Important Links below.")

    lines.append("Please see the Important Links below for more information.")
    return "\n".join(lines)


# ============================================================================
#  SHORT SUMMARY ("  ") - Sanity ke jobPost.shortSummary ke liye
# Sanity Studio ke niyam: sirf text, max 450 akshar, koi Link nahi. Bot seedha API
# se likhta hai (Studio ki jaanch lagu nahi hoti), isliye yahin saaf kiya jaata hai.
# ============================================================================
SHORT_SUMMARY_MAX = 440          # Studio ki seema 450 hai, thodi jagah chhodi
SHORT_SUMMARY_MIN = 60

_URL_RE = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]")


def clean_short_summary(value):
    """Link/emoji hatata hai, saaf karta hai, 420 akshar ke andar vaakya ki
    seema par kaat deta hai."""
    text = _as_text(value)
    text = _URL_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"[#*_`>]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > SHORT_SUMMARY_MAX:
        cut = text[:SHORT_SUMMARY_MAX]
        end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "), cut.rfind("\u0964"))
        text = cut[:end + 1] if end >= SHORT_SUMMARY_MIN else cut.rsplit(" ", 1)[0] + "..."
    return text.strip()


_EN_MONTHS = ["", "January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
_HI_MONTHS = ["", "\u091c\u0928\u0935\u0930\u0940", "\u092b\u0930\u0935\u0930\u0940", "\u092e\u093e\u0930\u094d\u091a", "\u0905\u092a\u094d\u0930\u0948\u0932", "\u092e\u0908", "\u091c\u0942\u0928", "\u091c\u0941\u0932\u093e\u0908",
              "\u0905\u0917\u0938\u094d\u0924", "\u0938\u093f\u0924\u0902\u092c\u0930", "\u0905\u0915\u094d\u091f\u0942\u092c\u0930", "\u0928\u0935\u0902\u092c\u0930", "\u0926\u093f\u0938\u0902\u092c\u0930"]


def _pretty_date(value):
    """'2026-11-18' -> '18 November 2026'."""
    from datetime import datetime
    try:
        d = datetime.strptime(str(value), "%Y-%m-%d")
        return f"{d.day} {_EN_MONTHS[d.month]} {d.year}"
    except Exception:
        return ""


def _fallback_short_summary(structured, status):
    """If the AI gave no usable shortSummary, build a simple English one from the
    facts we already have. Nothing new is invented."""
    org = _as_text(structured.get("organization")).strip() or "The concerned department"
    vacancy = str(structured.get("vacancy") or "").strip()
    dates = structured.get("importantDates") or {}
    if not isinstance(dates, dict):
        dates = {}
    start = _pretty_date(dates.get("applicationStart"))
    end = _pretty_date(dates.get("applicationEnd"))
    exam = _pretty_date(dates.get("examDate"))
    res = _pretty_date(dates.get("resultDate"))
    adm = _pretty_date(dates.get("admitCardDate"))

    parts = []
    if status == "job":
        parts.append(f"{org} has released a new recruitment notice.")
        if vacancy.isdigit():
            parts.append(f"There are {vacancy} posts in total.")
        if start and end:
            parts.append(f"Online application starts on {start} and the last date to apply is {end}.")
        elif end:
            parts.append(f"The last date to apply is {end}.")
        parts.append("Eligibility, fee and how to apply are explained below in simple words.")
    elif status == "admit_card":
        parts.append(f"{org} has released the admit card for the exam.")
        if adm:
            parts.append(f"The admit card was released on {adm}.")
        if exam:
            parts.append(f"The exam will be held on {exam}.")
        parts.append("How to download the admit card and what to carry to the exam centre is explained below.")
    elif status == "answer_key":
        parts.append(f"{org} has released the answer key of the exam.")
        parts.append("How to see the answer key and raise an objection is explained below.")
    elif status == "final_selection":
        parts.append(f"{org} has released the final selection list (merit list).")
        parts.append("How to check your name and what to do next is explained below.")
    elif status == "result":
        parts.append(f"{org} has declared the exam result.")
        if res:
            parts.append(f"The result date is {res}.")
        parts.append("How to check the result and the next step are explained below in simple words.")
    else:
        parts.append(f"{org} has released an important notice.")
    parts.append("Official links are given below.")
    return clean_short_summary(" ".join(parts))


def build_short_summary(structured, status):
    text = clean_short_summary(structured.get("shortSummary"))
    # English and long enough - only then use the AI text
    if len(text) >= SHORT_SUMMARY_MIN and _deva_ratio(text) <= 0.2:
        return text
    return _fallback_short_summary(structured, status)


def _ok_char(ch):
    o = ord(ch)
    return (
        o < 128
        or 0x0900 <= o <= 0x097F          # Devanagari (Hindi)
        or 0x2000 <= o <= 0x206F          # saamanya punctuation (dash, quotes, ZWJ)
        or 0x20A0 <= o <= 0x20CF          # currency (Rupee)
        or 0x2190 <= o <= 0x22FF          # arrows / math
        or o in (0xA0, 0xA9, 0xAE, 0xB0, 0xB1, 0xB7, 0xBC, 0xBD, 0xBE, 0xD7, 0xF7)
    )


def _only_hi_en(text):
    """Sirf Hindi (Devanagari) + English (Roman) + zaroori chinh rakhta hai.
    Dusri lipiyan (Urdu, Bengali, Chinese...) aur toote hue (mojibake) akshar hata deta hai."""
    if not isinstance(text, str):
        return text
    cleaned = "".join(ch for ch in text if _ok_char(ch))
    return re.sub(r"[ \t]{2,}", " ", cleaned)


def _sanitize_structured(obj):
    """AI ke jawab ke har text par _only_hi_en lagata hai (dict/list ke andar tak)."""
    if isinstance(obj, str):
        return _only_hi_en(obj)
    if isinstance(obj, list):
        return [_sanitize_structured(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _sanitize_structured(v) for k, v in obj.items()}
    return obj


def _is_blank_info(value):
    """Empty, N/A, null, or an 'information not available' style sentence."""
    t = _as_text(value).strip()
    if not t:
        return True
    low = t.lower()
    if low in ("n/a", "na", "none", "null", "-"):
        return True
    if len(t) < 60 and (low.startswith("information not available") or low.startswith("not available")
                        or low.startswith("not mentioned") or low.startswith("no information")):
        return True
    return "\u091c\u093e\u0928\u0915\u093e\u0930\u0940 \u0909\u092a\u0932\u092c\u094d\u0927 \u0928\u0939\u0940\u0902 \u0939\u0948" in t and len(t) < 40


_SEO_TYPE_WORD = {
    "job": "Recruitment Apply Online",
    "admit_card": "Admit Card Download",
    "answer_key": "Answer Key",
    "result": "Result",
    "final_selection": "Final Result Merit List",
}
_SEO_TAIL = " Check eligibility, important dates and Apply / Download links on Official Sarkari Patrika."


def _smart_trim(text, limit):
    """Shabd beech mein kaate bina limit ke andar kaat deta hai."""
    text = " ".join(_as_text(text).split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut[int(limit * 0.6):]:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" -|,:;")


def build_seo(structured, title, status):
    """Google ke liye meta title (<=60) aur meta description (<=160) - AI ka diya
    ho to use, par lambai/saaf-safai/keyword (saal + post-type) pakki karke.
    Kabhi khaali ya beech-shabd mein kata hua nahi."""
    now_year = time.gmtime().tm_year
    base = _as_text(structured.get("seoMetaTitle")).strip() or _as_text(title).strip()
    base = re.sub(r"https?://\S+", "", base).strip()
    year_m = re.search(r"\b(20\d\d)\b", base) or re.search(r"\b(20\d\d)\b", _as_text(title))
    year = year_m.group(1) if year_m else str(now_year)
    word = _SEO_TYPE_WORD.get(status, "")

    meta_title = _smart_trim(base, 60)
    if len(meta_title) < 38:
        extra = []
        if year not in meta_title:
            extra.append(year)
        if word and word.split()[0].lower() not in meta_title.lower():
            extra.append(word)
        candidate = " ".join([meta_title] + extra).strip()
        meta_title = _smart_trim(candidate, 60) if len(candidate) > len(meta_title) else meta_title

    desc = re.sub(r"https?://\S+", "", _as_text(structured.get("seoMetaDescription"))).strip()
    desc = " ".join(desc.split())
    if len(desc) < 110:
        lead = desc or f"{title} - {word}".strip(" -")
        desc = lead.rstrip(" \u0964.") + "." + _SEO_TAIL
    return {
        "metaTitle": meta_title or _smart_trim(title, 60),
        "metaDescription": _smart_trim(desc, 160),
    }


def _deva_ratio(text):
    """Text ke akshron mein Devanagari (Hindi) ka hissa (0 se 1)."""
    letters = [c for c in _as_text(text) if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if 0x0900 <= ord(c) <= 0x097F) / len(letters)


def _needs_english(value, max_ratio=0.25):
    """True if the text is empty / 'not available' or is not English (mostly Devanagari)."""
    if _is_blank_info(value):
        return True
    return _deva_ratio(value) > max_ratio


def create_draft_job_post(structured, source_link, status_hint=None, official_links=None, raw_text=""):
    """Structured AI data se ek DRAFT jobPost document Sanity mein banata
    hai. _id 'drafts.' se shuru hota hai - isliye yeh KABHI public website
    par nahi dikhega jab tak Studio mein manually 'Publish' na dabaya jaaye."""

    structured = _sanitize_structured(structured)   # sirf Hindi + English, koi teesri bhasha nahi
    title = _as_text(structured.get("title")).strip() or "Untitled Post"
    status = structured.get("status") if structured.get("status") in VALID_STATUSES else (status_hint or "job")
    # Website ke Sanity schema mein sirf yeh 5 status hain ('syllabus' nahi) - alag status
    # wali post Studio mein galat dikhti aur website ke kisi section mein nahi aati.
    if status not in {"job", "admit_card", "answer_key", "result", "final_selection"}:
        status = "job"
    vacancy_raw = str(structured.get("vacancy") or "").strip()

    # Post ki unique id link se banti hai - isse agar bot galti se same
    # link do baar process kar de, to duplicate draft nahi banega
    doc_id = f"drafts.jobpost-{hashlib.md5(source_link.encode()).hexdigest()[:16]}"

    #  CROSS-SOURCE DUPLICATE CHECK: agar yehi post (jaisa hi title)
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

    #  Organization ki website: pehle page se mili AADHIKARIK website, warna
    # (agar link khud sarkari ho to) uska root; private site ka home kabhi nahi
    org_site = ((official_links or {}).get("by_type", {}).get("Official Website") or {}).get("url")
    if not org_site and source_link and str(source_link).startswith("http") and is_official_url(source_link):
        org_site = official_root(source_link)
    org_id = get_or_create_organization(
        structured.get("organization"), org_site,
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
        "shortSummary": build_short_summary(structured, status),
        "description": _text_to_blocks(_get_or_build_description(structured, status)),
        "importantLinks": _ensure_core_links(
            _build_links_array(structured.get("links")), source_link, status,
            official_links=official_links, raw_text=raw_text,
        ),
        "seo": build_seo(structured, title, status),
        #  publishedAt/updatedAt: Studio mein yeh apne aap aaj ki date bhar
        # deta hai (initialValue), lekin woh sirf Studio UI ka trick hai -
        # seedhe API se likhte waqt yeh khud set karna padta hai, warna
        # khaali reh jaata (jo Schema.org dateModified ke liye zaroori hai)
        "publishedAt": _now_iso(),
        "updatedAt": _now_iso(),
    }

    #  IMPORTANT DATES - Application/Admit Card/Exam/Result dates
    important_dates = _build_important_dates(structured.get("importantDates"))
    if important_dates:
        doc["importantDates"] = important_dates

    #  JOB LOCATION - Google Jobs ke liye zaroori maana jaata hai
    #  jobLocation hamesha bharna chahiye (SEO/indexing ke liye) -
    # sirf Job hi nahi, har status ke liye
    job_location = _clean_short_text(structured.get("jobLocation"))
    if job_location and _deva_ratio(job_location) > 0.2:
        job_location = "All India"
    if not job_location:
        job_location = "All India"
    doc["jobLocation"] = job_location[:100]

    #  APPLICATION FEE - teeno field mein se koi ek bhi mile to jodein
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

    #  SALARY / PAY SCALE
    if status == "job":
        salary_text = _clean_short_text(structured.get("salaryText"))
        salary_min = _safe_int(structured.get("salaryMin"))
        salary_max = _safe_int(structured.get("salaryMax"))
        if not salary_text and not salary_min and not salary_max:
            salary_text = "Please check the official notification for pay scale details."
        salary_obj = {}
        if salary_text:
            salary_obj["payScaleText"] = salary_text[:150]
        if salary_min:
            salary_obj["minAmount"] = salary_min
        if salary_max:
            salary_obj["maxAmount"] = salary_max
        doc["salary"] = salary_obj

    #  CATEGORY-WISE VACANCY (UR/EWS/OBC/SC/ST/Total)
    cat_vacancy_raw = structured.get("categoryWiseVacancy")
    if isinstance(cat_vacancy_raw, dict):
        cat_vacancy = {}
        for key in ("ur", "ews", "obc", "sc", "st", "total"):
            val = _safe_int(cat_vacancy_raw.get(key))
            if val is not None:
                cat_vacancy[key] = val
        if cat_vacancy:
            doc["categoryWiseVacancy"] = cat_vacancy

    #  ADMIT CARD INFO / RESULT INFO - sirf jab status lagu ho
    if status == "admit_card":
        admit_info = _clean_short_text(structured.get("admitCardInfo"))
        if _needs_english(admit_info):
            admit_info = GENERIC_HOW_TO_DOWNLOAD_ADMIT_CARD
        doc["admitCardInfo"] = admit_info[:2000]

    if status in ("result", "final_selection"):
        result_info = _clean_short_text(structured.get("resultInfo"))
        if _needs_english(result_info):
            result_info = GENERIC_HOW_TO_CHECK_RESULT
        doc["resultInfo"] = result_info[:2000]

    #  STATUS TIMELINE - is naye status ko ek entry ke roop mein jod dete
    # hain, taaki website par "kab kya hua" ki history bhi dikhe
    status_labels = {
        "job": "Notification Released",
        "admit_card": "Admit Card Released",
        "answer_key": "Answer Key Released",
        "result": "Result Declared",
        "final_selection": "Final Selection List Released",
    }
    doc["statusTimeline"] = [{
        "_type": "object",
        "_key": _random_key(),
        "status": status_labels.get(status, status),
        "date": _now_iso(),
    }]

    #  ELIGIBILITY + HOW TO APPLY - alag, proper sections ke roop mein
    # (description ke andar generic text ki jagah) - "customSectionsBeforeLinks"
    # mein jaate hain, isliye page par Important Links se PEHLE dikhenge
    before_links_sections = []
    eligibility_text = _clean_short_text(structured.get("eligibilityDetails"))
    if _needs_english(eligibility_text):
        eligibility_text = _clean_short_text(structured.get("eligibilitySummary"))
    if _needs_english(eligibility_text):
        eligibility_text = (
            "Full eligibility details (educational qualification and age limit) are given in the "
            "Official Notification. Please open the notification from the Important Links section."
        )
    eligibility_section = _build_custom_section(
        ELIGIBILITY_HEADING,
        eligibility_text,
    )
    if eligibility_section:
        before_links_sections.append(eligibility_section)

    #  Yeh section hamesha dikhna chahiye, par STATUS ke hisaab se alag
    # (Job -> How to Apply, Result -> How to Check Result, wagairah).
    # Agar AI ne specific steps na diye hon, to us status ka standard
    # generic process use kar lete hain.
    how_to_heading, how_to_fallback = HOW_TO_SECTION_CONFIG.get(status, HOW_TO_SECTION_CONFIG["job"])
    how_to_text = _clean_short_text(structured.get("howToApply"))
    if _needs_english(how_to_text):
        how_to_text = how_to_fallback
    how_to_section = _build_custom_section(how_to_heading, how_to_text)
    if how_to_section:
        before_links_sections.append(how_to_section)

    if before_links_sections:
        doc["customSectionsBeforeLinks"] = before_links_sections

    #  FAQ hamesha kam se kam 5 dikhne chahiye - kam hon to available
    # data se aur bana lete hain
    faqs_list = structured.get("faqs") or []
    if not isinstance(faqs_list, list):
        faqs_list = []
    faqs_list = [f for f in faqs_list if isinstance(f, dict)
                 and not _needs_english(f.get("question")) and not _needs_english(f.get("answer"))]
    if len(faqs_list) < 5:
        faqs_list = faqs_list + _generate_fallback_faqs(structured, len(faqs_list))
    faq_section = _build_faq_section(faqs_list)
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

    #  BANNER: Post ke hisaab se automatic banner banakar seedha
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
    mein reference ki tarah jod\u0924\u0947 h\u0948\u0902\u0964"""
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

def _fill_missing_fields(structured, raw_text):
    """After the first AI attempt, ask ONE short second AI call only for the important
    fields that are still empty (vacancy, fee, eligibility, how-to-apply, salary, dates,
    summary, description, FAQs). Any error / timeout silently returns the data as it was
    (the post is still created)."""
    try:
        if not isinstance(structured, dict):
            return structured
        rem = remaining_seconds()
        if rem is not None and rem < 50:
            return structured

        want = {}
        field_help = {
            "vacancy": "total number of posts - only a number",
            "applicationFeeGeneral": "General/OBC fee, for example 'Rs 100'",
            "applicationFeeScst": "SC/ST/PH fee",
            "applicationFeePaymentMode": "how to pay the fee (simple English)",
            "salaryText": "pay scale / salary",
        }
        for k, hint in field_help.items():
            if _is_blank_info(structured.get(k)):
                want[k] = hint
        text_help = {
            "eligibilityDetails": "education qualification, age limit, age relaxation - simple English, one point per line",
            "howToApply": "steps to apply / download in simple English, one step per line (if the text has none, write the standard steps)",
            "aboutOrganization": "2-4 simple English sentences about this department",
        }
        status = structured.get("status") or ""
        if status == "admit_card":
            text_help["admitCardInfo"] = "how to download the admit card and what to carry to the exam centre - simple English"
        if status in ("result", "final_selection"):
            text_help["resultInfo"] = "how to check the result and the next step - simple English"
        for k, hint in text_help.items():
            if _needs_english(structured.get(k)):
                want[k] = hint
        summ = clean_short_summary(structured.get("shortSummary"))
        if len(summ) < 200 or _deva_ratio(summ) > 0.2:
            want["shortSummary"] = "5-6 short simple English sentences, 330-430 characters: which organisation released what, total posts, application dates, eligibility hint, fee/selection, and where to apply/download (no link, no emoji)"
        desc = _as_text(structured.get("description"))
        if len([l for l in desc.split("\n") if l.strip()]) < 4 or _deva_ratio(desc) > 0.2:
            want["description"] = "5-6 key points, one per line, simple English (organisation, post/exam, dates, eligibility, what to do next)"
        faqs_now = structured.get("faqs") if isinstance(structured.get("faqs"), list) else []
        good_faqs = [f for f in faqs_now if isinstance(f, dict)
                     and not _needs_english(f.get("question")) and not _needs_english(f.get("answer"))]
        if len(good_faqs) < 5:
            want["faqs"] = "JSON list of 5 items, each {question, answer}, both in simple English, only facts from the text or always-true general points"
        structured["faqs"] = good_faqs
        dates = structured.get("importantDates")
        if not isinstance(dates, dict):
            dates = {}
        date_help = {
            "applicationStart": "application start date YYYY-MM-DD",
            "applicationEnd": "application last date YYYY-MM-DD",
            "examDate": "exam date YYYY-MM-DD",
            "admitCardDate": "admit card date YYYY-MM-DD",
            "resultDate": "result date YYYY-MM-DD",
        }
        for k, hint in date_help.items():
            if _is_blank_info(dates.get(k)):
                want["date_" + k] = hint + " (null if not in the text)"
        if not want:
            return structured

        lines = "\n".join(f'  "{k}": "{v}"' for k, v in want.items())
        prompt = (
            "Below is the text of an Indian government notice. Extract ONLY the requested fields from it and "
            "reply with ONLY one JSON object (no extra text, no backticks). NEVER invent a date, number or fee - "
            "if it is not in the text write null for that field. Only for 'howToApply' and 'eligibilityDetails' "
            "you may write the standard / general method when the text has no information (no new facts). "
            "Write in SIMPLE PLAIN INDIAN ENGLISH, English alphabet only (for example: 1. Open the official website). "
            "No Hindi, no Hinglish, no other language.\n\n"
            "REQUESTED FIELDS:\n{\n" + lines + "\n}\n\nNOTICE TEXT:\n\"\"\"\n"
            + _as_text(raw_text)[:7000] + "\n\"\"\""
        )
        parsed = _try_parse_ai_json(_call_ai(prompt, max_tokens=2600))
        if not isinstance(parsed, dict):
            return structured
        for k in list(field_help) + list(text_help):
            if k in want and not _is_blank_info(parsed.get(k)):
                structured[k] = parsed[k]
        if "shortSummary" in want and not _is_blank_info(parsed.get("shortSummary")):
            structured["shortSummary"] = parsed["shortSummary"]
        if "description" in want and not _is_blank_info(parsed.get("description")):
            structured["description"] = parsed["description"]
        if "faqs" in want and isinstance(parsed.get("faqs"), list):
            structured["faqs"] = good_faqs + [f for f in parsed["faqs"] if isinstance(f, dict)]
        for k in date_help:
            v = parsed.get("date_" + k)
            if "date_" + k in want and not _is_blank_info(v):
                dates[k] = v
        structured["importantDates"] = dates
        print(f"    [FILL] second AI pass for empty fields: {', '.join(want.keys())}")
    except AIBudgetExceeded:
        pass
    except Exception as e:
        print(f"    [FILL] second AI pass skipped: {e}")
    return structured


# ============================================================================
# HINDI VERSION (hi) - the main post is in English. A second, separate step
# translates the finished English post into SIMPLE everyday Hindi (Devanagari)
# and stores it in the post's "hi" field. The website then shows it at /hi/...
# with a language button. If this step fails or runs out of time, the post is
# still created in English (the Hindi version can be added later).
# ============================================================================

HI_MIN_SECONDS = 45       # do not start the Hindi step with less time than this
_HI_LAST_ERROR = ""        # last reason the Hindi step did not finish (shown to the user)


def hindi_last_error():
    return _HI_LAST_ERROR


def _hi_fail(msg):
    global _HI_LAST_ERROR
    _HI_LAST_ERROR = msg
    print(f"    [HINDI] {msg}")
    return None

_HI_RULES = (
    "Translate the JSON below from English into SIMPLE EVERYDAY HINDI in Devanagari script - the Hindi that people "
    "across India (UP, Bihar, MP, Rajasthan, Delhi, Maharashtra and all other states) understand easily; "
    "NOT heavy, Sanskrit-style Hindi (say '\u092b\u0949\u0930\u094d\u092e \u0915\u0948\u0938\u0947 \u092d\u0930\u0947\u0902', not '\u0906\u0935\u0947\u0926\u0928 \u092a\u094d\u0930\u0915\u094d\u0930\u093f\u092f\u093e').\n"
    "RULES:\n"
    "- Keep EXACTLY the same JSON structure and keys. Every list must have exactly the same number of items, in the same order.\n"
    "- Do NOT add, remove or change any fact, date, number, amount, name or URL.\n"
    "- Keep names of organisations, exams and abbreviations as they are in English letters (SSC, IBPS SO, UPSC, PDF, OTP). "
    "Common words may be written in Devanagari (Admit Card -> \u090f\u0921\u092e\u093f\u091f \u0915\u093e\u0930\u094d\u0921, Online -> \u0911\u0928\u0932\u093e\u0907\u0928, Result -> \u0930\u093f\u091c\u093c\u0932\u094d\u091f).\n"
    "- Write dates like '18 \u0928\u0935\u0902\u092c\u0930 2026' and money like '\u20b9100'.\n"
    "- NEVER write Hindi words in Roman letters (no Hinglish). No other language or script.\n"
    "- Reply with ONLY the JSON object (no extra text, no backticks).\n"
)


def _blocks_to_lines(blocks):
    """Portable Text blocks -> list of {text, strong} (one per block)."""
    out = []
    for b in (blocks or []):
        if not isinstance(b, dict) or b.get("_type") != "block":
            continue
        kids = b.get("children") or []
        text = "".join(str(k.get("text") or "") for k in kids if isinstance(k, dict)).strip()
        if not text:
            continue
        strong = any("strong" in (k.get("marks") or []) for k in kids if isinstance(k, dict))
        out.append({"text": text, "strong": strong})
    return out


def _lines_to_blocks(lines, strongs=None):
    blocks = []
    for i, line in enumerate(lines):
        line = _as_text(line).strip()
        if not line:
            continue
        span = {"_type": "span", "_key": _random_key(), "text": line}
        if strongs and i < len(strongs) and strongs[i]:
            span["marks"] = ["strong"]
        blocks.append({"_type": "block", "_key": _random_key(), "style": "normal", "children": [span]})
    return blocks


def _hi_ok(text, min_ratio=0.3):
    """The text really is Hindi (Devanagari) - not English / Hinglish."""
    return bool(_as_text(text).strip()) and _deva_ratio(text) >= min_ratio


def translate_post_to_hindi(draft_doc):
    """Takes the finished English post (Sanity document) and returns the 'hi' object
    (or None if nothing usable came back). Uses up to two short AI calls:
    (1) main text fields, (2) the custom sections (eligibility, how-to, FAQ)."""
    if not isinstance(draft_doc, dict):
        return None
    status = draft_doc.get("status") or "job"
    seo = draft_doc.get("seo") or {}
    salary = (draft_doc.get("salary") or {}).get("payScaleText") or ""

    # ---- call 1: the main fields ----
    core_in = {
        "title": draft_doc.get("title") or "",
        "shortSummary": draft_doc.get("shortSummary") or "",
        "jobLocation": draft_doc.get("jobLocation") or "",
        "salaryText": salary,
        "admitCardInfo": draft_doc.get("admitCardInfo") or "",
        "resultInfo": draft_doc.get("resultInfo") or "",
        "description": [x["text"] for x in _blocks_to_lines(draft_doc.get("description"))],
        "metaTitle": seo.get("metaTitle") or "",
        "metaDescription": seo.get("metaDescription") or "",
    }
    core_in = {k: v for k, v in core_in.items() if v}
    extra = (
        "- 'title': Hindi title, but keep the organisation / exam name and the year in English letters "
        "(example: 'IBPS SO XVI Admit Card 2026 \u091c\u093e\u0930\u0940, \u092f\u0939\u093e\u0901 \u0938\u0947 \u0921\u093e\u0909\u0928\u0932\u094b\u0921 \u0915\u0930\u0947\u0902').\n"
        "- 'shortSummary': 5-6 short sentences, at most 430 characters.\n"
        "- 'metaTitle': at most 60 characters. 'metaDescription': at most 160 characters. Keep the key English search "
        "words (Admit Card, Result, Apply Online) and the year so that Hindi readers can find it on Google.\n"
        "- 'jobLocation': 'All India' becomes '\u092a\u0942\u0930\u0947 \u092d\u093e\u0930\u0924 \u092e\u0947\u0902'.\n"
    )
    prompt = _HI_RULES + extra + "\nJSON TO TRANSLATE:\n" + json.dumps(core_in, ensure_ascii=False)
    core = None
    for attempt in (1, 2):
        rem = remaining_seconds()
        if attempt == 2 and rem is not None and rem < 30:
            break
        core = _try_parse_ai_json(_call_ai(prompt, max_tokens=3000))
        if isinstance(core, dict):
            break
        print(f"    [HINDI] attempt {attempt}: AI reply was not valid JSON")
    if not isinstance(core, dict):
        return _hi_fail("AI ka Hindi jawab sahi JSON mein nahi aaya")
    core = _sanitize_structured(core)
    hi = {}
    if _hi_ok(core.get("title"), 0.1):
        hi["title"] = _as_text(core["title"]).strip()[:150]
    summ = clean_short_summary(core.get("shortSummary"))
    if len(summ) >= 40 and _hi_ok(summ, 0.35):
        hi["shortSummary"] = summ
    if "title" not in hi:
        return _hi_fail("AI ne Hindi title nahi diya (title Hindi mein nahi tha)")
    if "shortSummary" not in hi:
        return _hi_fail("AI ne Hindi Short Details nahi diye (Devanagari mein nahi the)")
    for k_out, k_in in (("jobLocation", "jobLocation"), ("salaryText", "salaryText")):
        v = _as_text(core.get(k_in)).strip()
        if v and _deva_ratio(v) >= 0.15:
            hi[k_out] = v[:150]
    if status == "admit_card" and _hi_ok(core.get("admitCardInfo")):
        hi["admitCardInfo"] = _as_text(core["admitCardInfo"]).strip()[:2000]
    if status in ("result", "final_selection") and _hi_ok(core.get("resultInfo")):
        hi["resultInfo"] = _as_text(core["resultInfo"]).strip()[:2000]
    desc_lines = core.get("description")
    if isinstance(desc_lines, str):
        desc_lines = [l for l in desc_lines.split("\n") if l.strip()]
    if isinstance(desc_lines, list) and desc_lines and _hi_ok(" ".join(map(str, desc_lines))):
        hi["description"] = _lines_to_blocks(desc_lines)
    meta_t = _smart_trim(_as_text(core.get("metaTitle")), 65)
    meta_d = _smart_trim(_as_text(core.get("metaDescription")), 165)
    if meta_t or meta_d:
        hi["seo"] = {}
        if _hi_ok(meta_t, 0.1):
            hi["seo"]["metaTitle"] = meta_t
        if _hi_ok(meta_d, 0.3):
            hi["seo"]["metaDescription"] = meta_d
        if not hi["seo"]:
            del hi["seo"]

    # ---- call 2: custom sections (eligibility / how-to / FAQ) ----
    rem = remaining_seconds()
    if rem is None or rem >= 30:
        try:
            sec_in = {}
            originals = {}
            for key, field in (("before", "customSectionsBeforeLinks"), ("after", "customSectionsAfterLinks")):
                items = []
                for sec in (draft_doc.get(field) or []):
                    lines = _blocks_to_lines(sec.get("content"))
                    if not sec.get("heading") or not lines:
                        continue
                    items.append({"heading": sec.get("heading"), "lines": [l["text"] for l in lines]})
                    originals.setdefault(key, []).append(lines)
                if items:
                    sec_in[key] = items
            if sec_in:
                prompt2 = (
                    _HI_RULES
                    + "- In FAQ sections, a line that starts with 'Q:' becomes '\u092a\u094d\u0930\u0936\u094d\u0928:' and 'A:' becomes '\u0909\u0924\u094d\u0924\u0930:'.\n"
                    + "- Translate every 'heading' too (for example 'Eligibility Criteria' -> '\u092a\u093e\u0924\u094d\u0930\u0924\u093e', "
                      "'How to Apply' -> '\u0906\u0935\u0947\u0926\u0928 \u0915\u0948\u0938\u0947 \u0915\u0930\u0947\u0902', 'Frequently Asked Questions (FAQ)' -> '\u0905\u0915\u094d\u0938\u0930 \u092a\u0942\u091b\u0947 \u091c\u093e\u0928\u0947 \u0935\u093e\u0932\u0947 \u0938\u0935\u093e\u0932').\n"
                    + "\nJSON TO TRANSLATE:\n" + json.dumps(sec_in, ensure_ascii=False)
                )
                parsed = _try_parse_ai_json(_call_ai(prompt2, max_tokens=4500))
                if isinstance(parsed, dict):
                    parsed = _sanitize_structured(parsed)
                    for key, field in (("before", "customSectionsBeforeLinks"), ("after", "customSectionsAfterLinks")):
                        got = parsed.get(key)
                        orig = originals.get(key) or []
                        if not isinstance(got, list) or len(got) != len(orig):
                            continue
                        built = []
                        ok_all = True
                        for sec_hi, orig_lines in zip(got, orig):
                            if not isinstance(sec_hi, dict):
                                ok_all = False
                                break
                            lines_hi = sec_hi.get("lines")
                            if (not isinstance(lines_hi, list) or len(lines_hi) != len(orig_lines)
                                    or not _hi_ok(" ".join(map(str, lines_hi)))
                                    or not _hi_ok(sec_hi.get("heading"), 0.3)):
                                ok_all = False
                                break
                            built.append({
                                "_type": "object", "_key": _random_key(),
                                "heading": _as_text(sec_hi.get("heading")).strip()[:120],
                                "content": _lines_to_blocks(lines_hi, [l["strong"] for l in orig_lines]),
                            })
                        if ok_all and built:
                            hi[field] = built
        except AIBudgetExceeded:
            pass
        except Exception as e:
            print(f"    [HINDI] sections translation skipped: {e}")
    return hi


def add_hindi_to_draft(doc_id, force=False):
    """Create (or refresh) the Hindi version of an existing post and save it in the
    post's 'hi' field. Returns True if saved. Never raises - safe to call after the
    English post is already created."""
    try:
        global _HI_LAST_ERROR
        _HI_LAST_ERROR = ""
        rem = remaining_seconds()
        if rem is not None and rem < HI_MIN_SECONDS:
            _hi_fail(f"samay kam bacha tha (sirf {int(rem)} second)")
            return False
        doc = get_draft_by_id(doc_id)
        if not doc:
            _hi_fail("draft Sanity mein nahi mila")
            return False
        if (doc.get("hi") or {}).get("title") and not force:
            return True
        hi = translate_post_to_hindi(doc)
        if not hi:
            if not _HI_LAST_ERROR:
                _hi_fail("AI ne kaam ka Hindi version nahi diya")
            return False
        _sanity_mutate([{"patch": {"id": doc_id, "set": {"hi": hi}}}])
        print(f"    [HINDI] Hindi version saved: {', '.join(hi.keys())}")
        return True
    except AIBudgetExceeded:
        _hi_fail("AI ka samay-seema khatam ho gayi")
        return False
    except Exception as e:
        _hi_fail(f"galti: {str(e)[:200]}")
        return False


def _publish_scraped_post_inner(raw_text, source_link, status_hint=None, official_url=None):
    """Raw text leta hai -> post-page se AADHIKARIK links nikaalta hai -> AI se
    structure karwaata hai -> Sanity mein DRAFT bana deta hai. Koi bhi step
    fail ho, to exception upar (main.py mein) jaake pakdi jaati hai, taaki
    poora bot na ruke.

    status_hint (optional): keyword-based bharosemand status (scraper.py
    ka detect_status()) - agar AI khud koi valid status na de paaye, to
    seedha "job" maan lene ke bajaye isi hint ka istemal hota hai.

    official_url (optional): agar aapko us post ka ASLI sarkari page pata
    hai, to yahan de dein - uske links ko sabse upar prathmikta milegi."""
    official = {}
    try:
        official = collect_official_links(source_link, official_url)
        if official.get("by_type"):
            print(f"    [LINKS] aadhikarik links mile: {', '.join(official['by_type'].keys())}")
        else:
            print(f"    [LINKS] koi aadhikarik link nahi mila ({official.get('error', 'page par nahi tha')})")
    except Exception as e:
        print(f"    [LINKS] aadhikarik links nikaalte waqt dikkat: {e}")

    # Links ka block SABSE UPAR - taaki AI ke 8000-akshar wali seema mein kat na jaye
    raw_with_links = format_links_block(official) + "\n\n" + raw_text
    structured = generate_structured_post(raw_with_links)
    structured = _fill_missing_fields(structured, raw_with_links)
    result = create_draft_job_post(
        structured, source_link, status_hint=status_hint,
        official_links=official, raw_text=raw_with_links,
    )
    # Hindi version (separate step; the English post already exists, so any
    # problem here never breaks the post)
    if isinstance(result, dict) and result.get("draftId") and os.environ.get("HINDI_VERSION", "1") != "0":
        result["hindi"] = add_hindi_to_draft(result["draftId"])
    return result


def publish_scraped_post(raw_text, source_link, status_hint=None, official_url=None):
    """Upar wala kaam, par ek surakshit samay-seema ke saath. Agar webhook ne
    pehle se ghadi chalu nahi ki (purani webhook file), to yahin se 190 second
    ki ghadi chalu ho jaati hai - taaki AI ke saare retry milakar bhi Vercel ke
    280 second se bahar na jaayein. Ghadi pehle se chalu ho to use badalte nahi."""
    owns_clock = remaining_seconds() is None
    if owns_clock:
        start_request_clock(190)
    try:
        return _publish_scraped_post_inner(raw_text, source_link, status_hint, official_url)
    finally:
        if owns_clock:
            clear_request_clock()


#  TELEGRAM REVIEW-BOT KE LIYE - draft ko padhna, sirf-kuch-fields patch
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
    if "shortSummary" in field_set:
        # Studio ki jaanch yahan lagu nahi hoti, isliye yahin saaf karte hain
        field_set = dict(field_set)
        cleaned = clean_short_summary(field_set["shortSummary"])
        if cleaned:
            field_set["shortSummary"] = cleaned
        else:
            field_set.pop("shortSummary")
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
    """Rebuild the Eligibility custom section (it is an array item, so a plain
    text patch is not possible) and save it to Sanity."""
    section = _build_custom_section(ELIGIBILITY_HEADING, new_eligibility_text)
    current = get_draft_by_id(doc_id) or {}
    sections = current.get("customSectionsBeforeLinks", []) or []
    sections = [s for s in sections if s.get("heading") not in LEGACY_ELIGIBILITY_HEADINGS]
    if section:
        sections.insert(0, section)
    patch_sanity_fields(doc_id, {"customSectionsBeforeLinks": sections})


def rebuild_how_to_apply_section(doc_id, new_text):
    """Rebuild the How-to section (heading depends on the post status)."""
    current = get_draft_by_id(doc_id) or {}
    heading = HOW_TO_SECTION_CONFIG.get(current.get("status") or "job", HOW_TO_SECTION_CONFIG["job"])[0]
    section = _build_custom_section(heading, new_text)
    sections = current.get("customSectionsBeforeLinks", []) or []
    sections = [s for s in sections if s.get("heading") not in LEGACY_HOWTO_HEADINGS]
    if section:
        sections.append(section)
    patch_sanity_fields(doc_id, {"customSectionsBeforeLinks": sections})


def rebuild_faq_section(doc_id, faqs_list):
    """FAQ section poora naye sirre se banata hai."""
    section = _build_faq_section(faqs_list)
    patch_sanity_fields(doc_id, {"customSectionsAfterLinks": [section] if section else []})


# ============================================================================
#  VISION AI - scanned PDF/photo se seedha "dekh kar" jaankari nikaalne
# ke liye (Vercel par tesseract/OCR install nahi ho sakta, isliye yeh
# behtar tareeka hai - AI seedha tasveer padh leta hai)
# ============================================================================

_vision_models_cache = None


def _get_vision_models():
    """OpenRouter se LIVE free VISION (image samajhne wale) model list
    mangwata hai - kyunki free vision models kabhi-kabhi band/paid ho
    jaate hain (jaisa mistral-small-3.1-24b ke saath hua), isliye
    hardcoded list ki jagah har baar taaza list check karte hain."""
    global _vision_models_cache
    if _vision_models_cache:
        return _vision_models_cache

    resp = requests.get("https://openrouter.ai/api/v1/models", timeout=_ai_timeout())
    resp.raise_for_status()
    data = resp.json().get("data", [])

    def supports_image(m):
        arch = m.get("architecture", {}) or {}
        modality = str(arch.get("modality", "") or "")
        input_modalities = arch.get("input_modalities", []) or []
        return "image" in modality or "image" in input_modalities

    free_vision = [
        m["id"] for m in data
        if m.get("id", "").endswith(":free") and supports_image(m)
    ]
    if not free_vision:
        raise Exception("Koi free vision model nahi mila")

    priority_keywords = ["qwen2.5-vl", "qwen3-vl", "llama-3.2", "gemma-3", "pixtral", "internvl"]

    def rank(model_id):
        for i, kw in enumerate(priority_keywords):
            if kw in model_id:
                return i
        return 99

    free_vision.sort(key=rank)
    _vision_models_cache = free_vision[:6]
    return _vision_models_cache


def call_vision_ai(prompt, images_base64):
    """Ek ya kai tasveerein (base64 PNG/JPEG) + ek sawaal/prompt AI ko
    bhejta hai, jawab (text) wapas deta hai. Kai free vision-model try
    karta hai (ek fail ho to agla). Koi bhi kaam na kare to Exception
    uthata hai - calling code isse pakad kar bina crash hue aage badh
    jaata hai."""
    if not OPENROUTER_API_KEY:
        raise Exception("OPENROUTER_API_KEY set nahi hai - vision AI ke liye zaroori hai")

    content = [{"type": "text", "text": prompt}]
    for img_b64 in images_base64[:5]:  # zyada se zyada 5 tasveerein ek saath
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
        })

    last_error = "koi model try nahi hua"
    for model in _get_vision_models():
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
                timeout=_vision_timeout(),
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
        except AIBudgetExceeded:
            raise
        except Exception as e:
            last_error = f"{model}: {e}"

    raise Exception(f"Vision AI se jawab nahi mila - {last_error}")
