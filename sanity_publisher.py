# sanity_publisher.py
# ðŸ†• NAYI FILE
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

# ðŸ†• Aadhikarik (gov/nic) link nikalne wala module
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
# ðŸ†• AB DO PROVIDERS: Pehle GROQ try hota hai (tez aur free), agar woh na ho
# ya kisi wajah se fail ho jaaye, to khud-ba-khud GEMINI par switch ho jaata
# hai - isse kisi EK provider ki dikkat se poora system nahi rukta.
# ============================================================================

REQUEST_TIMEOUT_AI = 45

# ============================================================================
# ðŸ†• SAMAY-SEEMA (Vercel ke 280 second ke andar rehne ke liye)
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


# ðŸ†• OPENROUTER - AB SABSE PEHLE TRY HOGA (aasaan sign-up ke liye):
# console.groq.com par account banane mein dikkat aa rahi thi, isliye
# OpenRouter jodà¤¾ gaya - yahan koi phone-verification nahi maangi jaati,
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
    kyunki free models ki list à¤¸à¤®à¤¯-à¤¸à¤®à¤¯ à¤ªà¤° badalti rehti hai."""
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
# ðŸ†• KAI MUFT AI COMPANIES (taaki ek ka quota khatam ho to doosri chal jaye)
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


PROMPT_TEMPLATE = """Tum "Official Sarkari Patrika" naam ke sarkari naukri suchna portal ke liye ek professional content editor ho. Neeche ek raw/kaccha notice text diya gaya hai. Isse ek saaf, professional, accurate, SEO-optimized Hindi job-post mein badlo - bilkul Sarkari Result jaisi professional websites jaisa, jisme HAR field bhari ho (sirf title-link nahi, poori detail).

SAKHT NIYAM:
- Sirf woh jaankari do jo neeche diye gaye text mein maujood hai ya usse seedha nikaali ja sakti hai. Koi bhi tareekh, sankhya, ya fact khud se mat banao/andaza mat lagao.
- Agar "Title:" line diya gaya hai, use hamesha "title" field ke liye istemal karo (SEO ke liye behtar bana sakte ho, lekin poori tarah khud se naya title mat gadhna jab tak asli title bilkul na mile).
- Agar "Likely Status:" diya gaya hai, USI status ko istemal karo jab tak neeche ke content mein saaf-saaf koi DOOSRA status likha ho (jaise agar Likely Status 'job' hai lekin content mein saaf 'Result Declared' likha hai, to 'result' hi à¤šà¥à¤¨à¥‹). Khud se kabhi status ko 'job' mat maan lo sirf isliye ki confidence kam hai - Likely Status ko default maano.
- "aboutOrganization" field ke liye tum apne general knowledge ka istemal kar sakte ho (jaise SSC, UPSC, Railway jaise jaane-maane vibhagon ke baare mein) - yeh field sakht niyam se bahar hai. Agar organization anjaan hai, to ek generic professional line likho (jaise "à¤¯à¤¹ à¤­à¤¾à¤°à¤¤ à¤¸à¤°à¤•à¤¾à¤°/à¤°à¤¾à¤œà¥à¤¯ à¤¸à¤°à¤•à¤¾à¤° à¤•à¤¾ à¤à¤• à¤®à¤¾à¤¨à¥à¤¯à¤¤à¤¾ à¤ªà¥à¤°à¤¾à¤ªà¥à¤¤ à¤µà¤¿à¤­à¤¾à¤— à¤¹à¥ˆ").
- Agar koi field ki jaankari bilkul na mile, to text wale fields mein "à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤‰à¤ªà¤²à¤¬à¥à¤§ à¤¨à¤¹à¥€à¤‚ à¤¹à¥ˆ" likho. Date wale fields (jahan "YYYY-MM-DD" mangi hai) mein jaankari na mile to seedha null likho (khud se koi date mat banao), aur uske "Note" wale field mein agar kuch likha ho (jaise "à¤œà¤²à¥à¤¦ à¤œà¤¾à¤°à¥€ à¤¹à¥‹à¤—à¥€") to wahi likho, warna woh bhi khaali chhod do.
- FAQ mein sirf woh sawaal-jawab likho jinka jawab diye gaye text mein SEEDHA maujood hai - kam se kam 5. Agar kisi sawaal ka jawab text mein nahi mil raha, to woh sawaal hi mat banao (jawab mein "à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤‰à¤ªà¤²à¤¬à¥à¤§ à¤¨à¤¹à¥€à¤‚ à¤¹à¥ˆ" mat bharo - iski jagah koi aisa sawaal chuno jiska jawab sach mein text mein ho).
- Professional Hindi bhasha, common English shabd (Apply Online, Admit Card) chalenge.
- "jobLocation" KABHI khaali mat chhodo - agar text mein saaf-saaf kisi ek state/shehar ka naam na mile, to "All India / à¤ªà¥‚à¤°à¥‡ à¤­à¤¾à¤°à¤¤ à¤®à¥‡à¤‚" likh do (yeh field website ki search/indexing ke liye zaroori hai).
- "eligibilityDetails" mein jo bhi shiksha yogyata/age limit ki jaankari mile, use poori tarah likho - agar bilkul kuch na mile tab hi "à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤‰à¤ªà¤²à¤¬à¥à¤§ à¤¨à¤¹à¥€à¤‚ à¤¹à¥ˆ" likho, warna jitni bhi jaankari text mein maujood hai (chahe adhoori ho) use zaroor shaamil karo.
- SEO (seoMetaTitle, seoMetaDescription) SABSE ZAROORI hai - yeh Google search mein rank karne ke liye hai. Title mein organization/exam ka poora naam + post type (Job/Admit Card/Result) + saal zaroor ho. Description mein bhi saaf, specific aur click-worthy jaankari ho (keyword stuffing nahi) - generic ya khaali kabhi mat rakhna.
- "description" field ek FULL SUMMARY hai - status ke hisaab se likho: Job ho to post, vibhag, vacancy, eligibility, important dates ka overview; Admit Card ho to kis exam ka admit card, kab jaari hua, exam date; Result ho to kis exam ka result, kab ghoshit hua, agla step kya hai. Yeh kabhi khaali ya sirf 1 line ka mat rakhna - kam se kam 4-5 achhe bullet points likho.
- "links" field ke liye: text ke shuru mein "OFFICIAL LINKS FOUND ON THE PAGE" naam ka block hai. "links" mein SIRF usi block ke URL istemal karo (type: Apply Online / Download Admit Card / Check Result / Official Notification / Official Website). Koi URL KHUD MAT BANAO, andaza mat lagao, kisi private website (Sarkari Result, FreeJobAlert jaisi) ka link mat do. Agar block mein "NONE FOUND" likha ho to "links": [] rakho.
- "shortSummary" (post ke sabse upar "Quick Summary" box mein dikhta hai): 2-3 chhote, SIMPLE ENGLISH vaakya, maximum 400 characters. Sirf text mein maujood asli tathya likho: kaun sa vibhag, kya (job / admit card / answer key / result), kul pad (agar diye hon), sabse zaroori tareekh, aur patrata ka ek chhota sanket. KOI URL/link, emoji ya hashtag mat likho. Title ki copy mat karo. Jo tathya text mein na ho use mat likho. Keyword stuffing bilkul nahi - saaf, natural, sachchi jaankari.
- "organization" mein vibhag ka sabse common, chhota, standard naam likho (jaise "SSC", "UPSSSC", "UPSC", "Railway (RRB)", "IBPS", "BPSC", "DSSSB") - har baar ek hi vibhag ke liye ek jaisa naam.
- Sirf neeche diye JSON format mein jawab do - koi extra text, koi markdown backticks, koi preamble nahi.

JSON FORMAT:
{{
  "title": "poora, spasht, SEO-friendly Hindi post title",
  "slugTitle": "sirf ANGREZI (English) mein, chhote akshar, hyphen se jude 4-8 shabd - jaise 'isro-scientist-engineer-recruitment-2026' - URL ke liye, kabhi Hindi mat likhna is field mein",
  "status": "job ya admit_card ya answer_key ya result ya final_selection - upar diye 'Likely Status' ko default maano",
  "organization": "vibhag/sanstha ka sabse common chhota standard naam (jaise SSC, UPSSSC, Railway (RRB)) - har baar ek jaisa",
  "shortSummary": "2-3 simple English sentences, max 400 characters, only facts from the text, no links, no emoji, do not copy the title",
  "aboutOrganization": "2-4 line mein is vibhag/sanstha ke baare mein professional jaankari (general knowledge chalega)",
  "vacancy": "sirf number ya N/A",
  "jobLocation": "jaise 'All India / à¤ªà¥‚à¤°à¥‡ à¤­à¤¾à¤°à¤¤ à¤®à¥‡à¤‚' ya 'Uttar Pradesh' - jahan yeh bharti lagu hoti hai",
  "eligibilitySummary": "1-2 line mein chhota summary (sirf vacancy table ke liye)",
  "eligibilityDetails": "poori shiksha yogyata, age limit, age relaxation - har point naye line mein",
  "howToApply": "aavedan karne ke step-by-step tareeke, har step naya line mein (jaise: 1. Official website kholein 2. Registration karein...)",
  "applicationFeeGeneral": "General/OBC candidates ki fee, jaise 'â‚¹100' - na mile to khaali",
  "applicationFeeScst": "SC/ST/PH candidates ki fee - na mile to khaali",
  "applicationFeePaymentMode": "payment kaise karein, jaise 'Online (Debit Card/Net Banking)' - na mile to khaali",
  "salaryText": "pay scale, jaise 'Level 4 (â‚¹25,500 - â‚¹81,100)' - na mile to khaali",
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
  "seoMetaTitle": "SEO ke liye best title - Google par jaisi bhasha log search karte hain waisa (jaise 'UPSSSC Junior Assistant Admit Card 2026 Download' - organization/exam ka naam + post/kaam ka type + saal). 55-60 character ke andar, keyword sabse pehle rakho.",
  "seoMetaDescription": "SEO meta description - Google search results mein yeh dikhta hai isliye click karne layak, informative aur natural hona chahiye (keyword stuffing nahi). Isme yeh sab shaamil karo: organization ka naam, post/exam ka naam, kya action hai (Apply/Download/Check), aur agar available ho to last date/exam date. 150-160 character ke andar."
}}

"links" ke "type" field ke liye SIRF yahi 5 value istemal karo (jo lagu ho wahi jodo, sabhi zaroori nahi): "Apply Online", "Download Admit Card", "Check Result", "Official Notification", "Official Website"

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

    ðŸ†• SURAKSHA: AI kabhi-kabhi ek hi baar mein poora sahi JSON nahi
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
            # ðŸ†• Samay-seema khatam - aur koshish nahi, seedha saaf error
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

    ðŸ”§ FIX 1: Hindi (Devanagari) title se slugify() karne par sab akshar
    hat jaate hain aur khaali/'post' jaisa bekaar slug ban jaata tha -
    ab caller (_compute_base_slug) English slug-hint ko priority deta hai.

    ðŸ”§ FIX 2: 'exclude_doc_id' pass karne se, agar SAME post dobara
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
# ðŸ†• ORGANIZATION MATCHING (duplicate Organization rokne ke liye)
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
    liye zaroori). ðŸ”§ FIX: text agar list ho (AI kabhi aisa bhej deta
    hai) to pehle usse string mein badal lete hain, warna .split() par
    crash ho jaata tha."""
    text = _as_text(text)
    blocks = []
    for line in text.split("\n"):
        line = line.strip().lstrip("-â€¢").strip()
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
                "text": f"à¤ªà¥à¤°à¤¶à¥à¤¨: {question}", "marks": ["strong"],
            }],
        })
        # Jawab - Normal
        content_blocks.append({
            "_type": "block",
            "_key": _random_key(),
            "style": "normal",
            "children": [{
                "_type": "span", "_key": _random_key(),
                "text": f"à¤‰à¤¤à¥à¤¤à¤°: {answer}",
            }],
        })

    if not content_blocks:
        return None

    return {
        "_type": "object",
        "_key": _random_key(),
        "heading": "à¤…à¤•à¥à¤¸à¤° à¤ªà¥‚à¤›à¥‡ à¤œà¤¾à¤¨à¥‡ à¤µà¤¾à¤²à¥‡ à¤ªà¥à¤°à¤¶à¥à¤¨ (FAQ)",
        "content": content_blocks,
    }


def _build_custom_section(heading, text):
    """Eligibility, How-to-Apply jaisi cheezon ko jobPost.ts ke
    'customSectionsBeforeLinks' format mein ek proper section (heading +
    content box) banata hai - description ke andar generic text ki
    jagah website par alag, saaf dikhne wala box banta hai."""
    text = _as_text(text).strip()
    if not text or text == "à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤‰à¤ªà¤²à¤¬à¥à¤§ à¤¨à¤¹à¥€à¤‚ à¤¹à¥ˆ":
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
    isse Sanity ko kabhi galat/tuta hua date bhejà¤•à¤° 400 error nahi aata."""
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
        if note and note != "à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤‰à¤ªà¤²à¤¬à¥à¤§ à¤¨à¤¹à¥€à¤‚ à¤¹à¥ˆ":
            result[note_key] = note[:100]

    return result if result else None


def _safe_int(value):
    """AI se mili sankhya ko surakshit tareeke se number mein badalta
    hai - agar woh number na ho (jaise 'à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤‰à¤ªà¤²à¤¬à¥à¤§ à¤¨à¤¹à¥€à¤‚ à¤¹à¥ˆ' ya
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
    'à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤‰à¤ªà¤²à¤¬à¥à¤§ à¤¨à¤¹à¥€à¤‚ à¤¹à¥ˆ' likh diya to khaali string deta hai (taaki
    website par khaali/bekaar field na dikhe)."""
    value = _as_text(value).strip()
    if not value or value == "à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤‰à¤ªà¤²à¤¬à¥à¤§ à¤¨à¤¹à¥€à¤‚ à¤¹à¥ˆ":
        return ""
    return value


GENERIC_HOW_TO_APPLY = (
    "1. à¤¸à¤¬à¤¸à¥‡ à¤ªà¤¹à¤²à¥‡ à¤¸à¤‚à¤¬à¤‚à¤§à¤¿à¤¤ à¤µà¤¿à¤­à¤¾à¤— à¤•à¥€ à¤†à¤§à¤¿à¤•à¤¾à¤°à¤¿à¤• à¤µà¥‡à¤¬à¤¸à¤¾à¤‡à¤Ÿ à¤ªà¤° à¤œà¤¾à¤à¤‚à¥¤\n"
    "2. à¤­à¤°à¥à¤¤à¥€/à¤¸à¥‚à¤šà¤¨à¤¾ à¤¸à¥‡ à¤œà¥à¤¡à¤¼à¥€ à¤²à¤¿à¤‚à¤• à¤ªà¤° à¤•à¥à¤²à¤¿à¤• à¤•à¤°à¤•à¥‡ à¤¨à¥‹à¤Ÿà¤¿à¤«à¤¿à¤•à¥‡à¤¶à¤¨ à¤§à¥à¤¯à¤¾à¤¨ à¤¸à¥‡ à¤ªà¤¢à¤¼à¥‡à¤‚à¥¤\n"
    "3. à¤¯à¤¦à¤¿ à¤¨à¤¯à¤¾ à¤°à¤œà¤¿à¤¸à¥à¤Ÿà¥à¤°à¥‡à¤¶à¤¨ à¤®à¤¾à¤‚à¤—à¤¾ à¤œà¤¾à¤ à¤¤à¥‹ à¤ªà¤¹à¤²à¥‡ à¤°à¤œà¤¿à¤¸à¥à¤Ÿà¥à¤°à¥‡à¤¶à¤¨ à¤•à¤°à¥‡à¤‚, à¤«à¤¿à¤° à¤²à¥‰à¤—à¤¿à¤¨ à¤•à¤°à¥‡à¤‚à¥¤\n"
    "4. à¤†à¤µà¥‡à¤¦à¤¨ à¤«à¥‰à¤°à¥à¤® à¤®à¥‡à¤‚ à¤®à¤¾à¤‚à¤—à¥€ à¤—à¤ˆ à¤¸à¤­à¥€ à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤¸à¤¹à¥€-à¤¸à¤¹à¥€ à¤­à¤°à¥‡à¤‚à¥¤\n"
    "5. à¤œà¤°à¥‚à¤°à¥€ à¤¦à¤¸à¥à¤¤à¤¾à¤µà¥‡à¤œà¤¼, à¤«à¥‹à¤Ÿà¥‹ à¤”à¤° à¤¹à¤¸à¥à¤¤à¤¾à¤•à¥à¤·à¤° à¤¸à¥à¤•à¥ˆà¤¨ à¤•à¤°à¤•à¥‡ à¤…à¤ªà¤²à¥‹à¤¡ à¤•à¤°à¥‡à¤‚à¥¤\n"
    "6. à¤†à¤µà¥‡à¤¦à¤¨ à¤¶à¥à¤²à¥à¤• (à¤¯à¤¦à¤¿ à¤²à¤¾à¤—à¥‚ à¤¹à¥‹) à¤•à¤¾ à¤‘à¤¨à¤²à¤¾à¤‡à¤¨ à¤­à¥à¤—à¤¤à¤¾à¤¨ à¤•à¤°à¥‡à¤‚à¥¤\n"
    "7. à¤«à¥‰à¤°à¥à¤® à¤¸à¤¬à¤®à¤¿à¤Ÿ à¤•à¤°à¤•à¥‡ à¤‰à¤¸à¤•à¤¾ à¤ªà¥à¤°à¤¿à¤‚à¤Ÿà¤†à¤‰à¤Ÿ à¤­à¤µà¤¿à¤·à¥à¤¯ à¤•à¥‡ à¤²à¤¿à¤ à¤¸à¥à¤°à¤•à¥à¤·à¤¿à¤¤ à¤°à¤–à¥‡à¤‚à¥¤"
)

GENERIC_HOW_TO_DOWNLOAD_ADMIT_CARD = (
    "1. à¤¸à¤‚à¤¬à¤‚à¤§à¤¿à¤¤ à¤µà¤¿à¤­à¤¾à¤— à¤•à¥€ à¤†à¤§à¤¿à¤•à¤¾à¤°à¤¿à¤• à¤µà¥‡à¤¬à¤¸à¤¾à¤‡à¤Ÿ à¤ªà¤° à¤œà¤¾à¤à¤‚à¥¤\n"
    "2. \"Download Admit Card\" à¤µà¤¾à¤²à¥‡ à¤²à¤¿à¤‚à¤• à¤ªà¤° à¤•à¥à¤²à¤¿à¤• à¤•à¤°à¥‡à¤‚à¥¤\n"
    "3. à¤…à¤ªà¤¨à¤¾ Registration Number/Roll Number à¤”à¤° à¤œà¤¨à¥à¤®à¤¤à¤¿à¤¥à¤¿ à¤¡à¤¾à¤²à¥‡à¤‚à¥¤\n"
    "4. à¤à¤¡à¤®à¤¿à¤Ÿ à¤•à¤¾à¤°à¥à¤¡ à¤¸à¥à¤•à¥à¤°à¥€à¤¨ à¤ªà¤° à¤¦à¤¿à¤– à¤œà¤¾à¤à¤—à¤¾, à¤‰à¤¸à¤•à¤¾ à¤ªà¥à¤°à¤¿à¤‚à¤Ÿà¤†à¤‰à¤Ÿ à¤¨à¤¿à¤•à¤¾à¤² à¤²à¥‡à¤‚à¥¤\n"
    "5. à¤ªà¤°à¥€à¤•à¥à¤·à¤¾ à¤•à¥‡à¤‚à¤¦à¥à¤° à¤ªà¤° à¤à¤¡à¤®à¤¿à¤Ÿ à¤•à¤¾à¤°à¥à¤¡ à¤”à¤° à¤à¤• à¤«à¥‹à¤Ÿà¥‹ ID à¤¸à¤¾à¤¥ à¤²à¥‡ à¤œà¤¾à¤¨à¤¾ à¤…à¤¨à¤¿à¤µà¤¾à¤°à¥à¤¯ à¤¹à¥ˆà¥¤"
)

GENERIC_HOW_TO_CHECK_ANSWER_KEY = (
    "1. à¤¸à¤‚à¤¬à¤‚à¤§à¤¿à¤¤ à¤µà¤¿à¤­à¤¾à¤— à¤•à¥€ à¤†à¤§à¤¿à¤•à¤¾à¤°à¤¿à¤• à¤µà¥‡à¤¬à¤¸à¤¾à¤‡à¤Ÿ à¤ªà¤° à¤œà¤¾à¤à¤‚à¥¤\n"
    "2. \"Answer Key\" à¤µà¤¾à¤²à¥‡ à¤²à¤¿à¤‚à¤• à¤ªà¤° à¤•à¥à¤²à¤¿à¤• à¤•à¤°à¥‡à¤‚à¥¤\n"
    "3. à¤…à¤ªà¤¨à¤¾ Roll Number/Registration Number à¤¡à¤¾à¤²à¤•à¤° à¤‰à¤¤à¥à¤¤à¤° à¤•à¥à¤‚à¤œà¥€ à¤¦à¥‡à¤–à¥‡à¤‚ à¤¯à¤¾ à¤¡à¤¾à¤‰à¤¨à¤²à¥‹à¤¡ à¤•à¤°à¥‡à¤‚à¥¤\n"
    "4. à¤¯à¤¦à¤¿ à¤•à¤¿à¤¸à¥€ à¤‰à¤¤à¥à¤¤à¤° à¤ªà¤° à¤†à¤ªà¤¤à¥à¤¤à¤¿ (objection) à¤¹à¥‹ à¤¤à¥‹ à¤¨à¤¿à¤°à¥à¤§à¤¾à¤°à¤¿à¤¤ à¤¤à¤¿à¤¥à¤¿ à¤¤à¤• à¤‘à¤¨à¤²à¤¾à¤‡à¤¨ à¤†à¤ªà¤¤à¥à¤¤à¤¿ à¤¦à¤°à¥à¤œ à¤•à¤°à¥‡à¤‚à¥¤"
)

GENERIC_HOW_TO_CHECK_RESULT = (
    "1. à¤¸à¤‚à¤¬à¤‚à¤§à¤¿à¤¤ à¤µà¤¿à¤­à¤¾à¤— à¤•à¥€ à¤†à¤§à¤¿à¤•à¤¾à¤°à¤¿à¤• à¤µà¥‡à¤¬à¤¸à¤¾à¤‡à¤Ÿ à¤ªà¤° à¤œà¤¾à¤à¤‚à¥¤\n"
    "2. \"Result\" à¤¯à¤¾ \"Check Result\" à¤µà¤¾à¤²à¥‡ à¤²à¤¿à¤‚à¤• à¤ªà¤° à¤•à¥à¤²à¤¿à¤• à¤•à¤°à¥‡à¤‚à¥¤\n"
    "3. à¤…à¤ªà¤¨à¤¾ Roll Number/Registration Number à¤¡à¤¾à¤²à¤•à¤° à¤ªà¤°à¤¿à¤£à¤¾à¤® à¤¦à¥‡à¤–à¥‡à¤‚à¥¤\n"
    "4. à¤ªà¤°à¤¿à¤£à¤¾à¤® à¤•à¤¾ à¤ªà¥à¤°à¤¿à¤‚à¤Ÿà¤†à¤‰à¤Ÿ à¤¯à¤¾ à¤¸à¥à¤•à¥à¤°à¥€à¤¨à¤¶à¥‰à¤Ÿ à¤­à¤µà¤¿à¤·à¥à¤¯ à¤•à¥‡ à¤²à¤¿à¤ à¤¸à¥à¤°à¤•à¥à¤·à¤¿à¤¤ à¤°à¤– à¤²à¥‡à¤‚à¥¤"
)

# ðŸ†• Status ke hisaab se sahi heading + fallback text chunte hain -
# "How to Apply" sirf Job ke liye lagu hota hai, baaki statuses ke liye
# alag hi tarah ki jaankari (download/check) zyada kaam ki hoti hai
GENERIC_HOW_TO_CHECK_SYLLABUS = (
    "1. à¤¸à¤‚à¤¬à¤‚à¤§à¤¿à¤¤ à¤µà¤¿à¤­à¤¾à¤—/à¤ªà¤°à¥€à¤•à¥à¤·à¤¾ à¤•à¥€ à¤†à¤§à¤¿à¤•à¤¾à¤°à¤¿à¤• à¤µà¥‡à¤¬à¤¸à¤¾à¤‡à¤Ÿ à¤ªà¤° à¤œà¤¾à¤à¤‚à¥¤\n"
    "2. \"Syllabus\" à¤µà¤¾à¤²à¥‡ à¤²à¤¿à¤‚à¤• à¤ªà¤° à¤•à¥à¤²à¤¿à¤• à¤•à¤°à¥‡à¤‚à¥¤\n"
    "3. PDF à¤¡à¤¾à¤‰à¤¨à¤²à¥‹à¤¡ à¤•à¤°à¤•à¥‡ à¤µà¤¿à¤·à¤¯à¤µà¤¾à¤° à¤ªà¤¾à¤ à¥à¤¯à¤•à¥à¤°à¤® à¤§à¥à¤¯à¤¾à¤¨ à¤¸à¥‡ à¤ªà¤¢à¤¼à¥‡à¤‚à¥¤\n"
    "4. Exam Pattern (à¤ªà¥à¤°à¤¶à¥à¤¨à¥‹à¤‚ à¤•à¥€ à¤¸à¤‚à¤–à¥à¤¯à¤¾, à¤…à¤‚à¤•, à¤¸à¤®à¤¯) à¤­à¥€ à¤‡à¤¸à¥€ PDF à¤®à¥‡à¤‚ à¤®à¤¿à¤²à¤¤à¤¾ à¤¹à¥ˆà¥¤"
)

HOW_TO_SECTION_CONFIG = {
    "job": ("à¤†à¤µà¥‡à¤¦à¤¨ à¤•à¥ˆà¤¸à¥‡ à¤•à¤°à¥‡à¤‚ (How to Apply)", GENERIC_HOW_TO_APPLY),
    "admit_card": ("à¤à¤¡à¤®à¤¿à¤Ÿ à¤•à¤¾à¤°à¥à¤¡ à¤•à¥ˆà¤¸à¥‡ à¤¡à¤¾à¤‰à¤¨à¤²à¥‹à¤¡ à¤•à¤°à¥‡à¤‚ (How to Download)", GENERIC_HOW_TO_DOWNLOAD_ADMIT_CARD),
    "answer_key": ("à¤‰à¤¤à¥à¤¤à¤° à¤•à¥à¤‚à¤œà¥€ à¤•à¥ˆà¤¸à¥‡ à¤¦à¥‡à¤–à¥‡à¤‚ (How to Check Answer Key)", GENERIC_HOW_TO_CHECK_ANSWER_KEY),
    "result": ("à¤ªà¤°à¤¿à¤£à¤¾à¤® à¤•à¥ˆà¤¸à¥‡ à¤¦à¥‡à¤–à¥‡à¤‚ (How to Check Result)", GENERIC_HOW_TO_CHECK_RESULT),
    "final_selection": ("à¤ªà¤°à¤¿à¤£à¤¾à¤® à¤•à¥ˆà¤¸à¥‡ à¤¦à¥‡à¤–à¥‡à¤‚ (How to Check Result)", GENERIC_HOW_TO_CHECK_RESULT),
    "syllabus": ("à¤¸à¤¿à¤²à¥‡à¤¬à¤¸ à¤•à¥ˆà¤¸à¥‡ à¤¦à¥‡à¤–à¥‡à¤‚ (How to Check Syllabus)", GENERIC_HOW_TO_CHECK_SYLLABUS),
}


def _ensure_core_links(ai_links, source_link, status, official_links=None, raw_text=""):
    """ðŸ†• PURA BADLA HUA: Important Links mein ab SIRF aadhikarik links jaate
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

    # 1) AI ke diye links - sirf wahi jo page par sach mein mile the, ya
    #    aadhikarik domain ke hon aur text mein likhe hue hon (AI ki gadhi
    #    hui link nahi chalegi)
    for l in (ai_links or []):
        u = str(l.get("url") or "").strip()
        verified = (u in allowed_urls) or u.rstrip("/") in raw_text
        # ðŸ†• SIRF aadhikarik domain - koi private/platform/exam-vendor link nahi
        if verified and is_official_url(u) and u not in seen_urls:
            seen_urls.add(u)
            result.append(l)
    types_present = {l.get("linkType") for l in result}

    primary_type = {
        "job": "Apply Online",
        "admit_card": "Download Admit Card",
        "answer_key": "Check Result",
        "result": "Check Result",
        "final_selection": "Check Result",
        "syllabus": "Official Notification",
    }.get(status, "Apply Online")

    labels = {
        "Official Notification": "à¤†à¤§à¤¿à¤•à¤¾à¤°à¤¿à¤• à¤¸à¥‚à¤šà¤¨à¤¾ (Notification)",
        "Official Website": "à¤†à¤§à¤¿à¤•à¤¾à¤°à¤¿à¤• à¤µà¥‡à¤¬à¤¸à¤¾à¤‡à¤Ÿ (Official Website)",
    }

    # 2) Page se nikale gaye aadhikarik links
    for ltype in (primary_type, "Official Notification", "Official Website"):
        if ltype in types_present:
            continue
        c = by_type.get(ltype)
        if c and c.get("official"):      # ðŸ†• sirf aadhikarik domain
            _add(c["url"], labels.get(ltype, ltype), ltype)
            types_present.add(ltype)

    # ðŸ†• Baaki aadhikarik links (Correction, Syllabus, Exam City/Status,
    # Candidate Login) - sirf aadhikarik domain wale, schema ke liye
    # linkType "Official Website" ke saath
    extra_labels = {
        "Correction Link": "à¤†à¤µà¥‡à¤¦à¤¨ à¤®à¥‡à¤‚ à¤¸à¥à¤§à¤¾à¤° (Correction Window)",
        "Syllabus": "à¤¸à¤¿à¤²à¥‡à¤¬à¤¸ (Syllabus)",
        "Exam City / Status": "à¤ªà¤°à¥€à¤•à¥à¤·à¤¾ à¤¶à¤¹à¤° / à¤†à¤µà¥‡à¤¦à¤¨ à¤¸à¥à¤¥à¤¿à¤¤à¤¿",
        "Candidate Login": "à¤•à¥ˆà¤‚à¤¡à¤¿à¤¡à¥‡à¤Ÿ à¤²à¥‰à¤—à¤¿à¤¨",
    }
    for ltype, lbl in extra_labels.items():
        c = by_type.get(ltype)
        if c and c.get("official") and c["url"] not in seen_urls:
            _add(c["url"], lbl, "Official Website")

    # Ek aur notification PDF (jaise Short Notice) agar mili ho
    for c in all_found:
        if c["type"] == "Official Notification" and c.get("official") and c["url"] not in seen_urls:
            _add(c["url"], "à¤…à¤¤à¤¿à¤°à¤¿à¤•à¥à¤¤ à¤¸à¥‚à¤šà¤¨à¤¾ (PDF)", "Official Notification")
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

    # ðŸ†• PERMANENT: WhatsApp aur Telegram channel link - har post mein
    # hamesha, chahe AI ne kuch bhi diya ho. Note: Sanity schema
    # (jobPost.ts) ke importantLinks.linkType mein abhi sirf 5 values
    # allowed hain - agar Studio mein yeh dropdown se select nahi ho
    # rahe (red dikhein), to schema mein "WhatsApp Channel" aur
    # "Telegram Channel" do options aur jodne honge.
    result.append({
        "_type": "object", "_key": _random_key(),
        "label": "à¤¹à¤®à¤¾à¤°à¤¾ WhatsApp Channel à¤œà¥‰à¤‡à¤¨ à¤•à¤°à¥‡à¤‚",
        "url": "https://whatsapp.com/channel/0029VbC7Adf7tkj3LRmYuk0h",
        "linkType": "WhatsApp Channel",
    })
    result.append({
        "_type": "object", "_key": _random_key(),
        "label": "à¤¹à¤®à¤¾à¤°à¤¾ Telegram Channel à¤œà¥‰à¤‡à¤¨ à¤•à¤°à¥‡à¤‚",
        "url": "https://t.me/OfficialSarkariPatrika",
        "linkType": "Telegram Channel",
    })

    return result


def _generate_fallback_faqs(structured, existing_count):
    """FAQ hamesha kam se kam 5 dikhein isliye - agar AI ne 5 se kam
    diye hon, to jo structured data pehle se maujood hai (vacancy,
    dates, fee, organization) usà¥€ se aur sawaal-jawab bana dete hain,
    koi nayi jaankari khud se nahi banate."""
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
            "à¤¯à¤¹ à¤­à¤°à¥à¤¤à¥€/à¤¸à¥‚à¤šà¤¨à¤¾ à¤•à¤¿à¤¸ à¤µà¤¿à¤­à¤¾à¤— à¤¯à¤¾ à¤¸à¤‚à¤¸à¥à¤¥à¤¾ à¤¸à¥‡ à¤¸à¤‚à¤¬à¤‚à¤§à¤¿à¤¤ à¤¹à¥ˆ?",
            f"à¤¯à¤¹ à¤­à¤°à¥à¤¤à¥€/à¤¸à¥‚à¤šà¤¨à¤¾ {org} à¤¸à¥‡ à¤¸à¤‚à¤¬à¤‚à¤§à¤¿à¤¤ à¤¹à¥ˆà¥¤",
        ))
    if vacancy and vacancy.isdigit():
        candidates.append((
            "à¤‡à¤¸à¤®à¥‡à¤‚ à¤•à¥à¤² à¤•à¤¿à¤¤à¤¨à¥‡ à¤ªà¤¦ à¤¹à¥ˆà¤‚?",
            f"à¤‡à¤¸à¤®à¥‡à¤‚ à¤•à¥à¤² {vacancy} à¤ªà¤¦ à¤¹à¥ˆà¤‚à¥¤",
        ))
    if isinstance(dates, dict) and dates.get("applicationEnd"):
        candidates.append((
            "à¤†à¤µà¥‡à¤¦à¤¨ à¤•à¤°à¤¨à¥‡ à¤•à¥€ à¤…à¤‚à¤¤à¤¿à¤® à¤¤à¤¿à¤¥à¤¿ à¤•à¥à¤¯à¤¾ à¤¹à¥ˆ?",
            f"à¤†à¤µà¥‡à¤¦à¤¨ à¤•à¤°à¤¨à¥‡ à¤•à¥€ à¤…à¤‚à¤¤à¤¿à¤® à¤¤à¤¿à¤¥à¤¿ {dates['applicationEnd']} à¤¹à¥ˆà¥¤",
        ))
    if isinstance(dates, dict) and dates.get("applicationStart"):
        candidates.append((
            "à¤†à¤µà¥‡à¤¦à¤¨ à¤•à¤¬ à¤¸à¥‡ à¤¶à¥à¤°à¥‚ à¤¹à¥‹à¤‚à¤—à¥‡?",
            f"à¤†à¤µà¥‡à¤¦à¤¨ {dates['applicationStart']} à¤¸à¥‡ à¤¶à¥à¤°à¥‚ à¤¹à¥‹à¤‚à¤—à¥‡à¥¤",
        ))
    if fee:
        candidates.append((
            "à¤†à¤µà¥‡à¤¦à¤¨ à¤¶à¥à¤²à¥à¤• à¤•à¤¿à¤¤à¤¨à¤¾ à¤¹à¥ˆ?",
            f"à¤¸à¤¾à¤®à¤¾à¤¨à¥à¤¯/OBC à¤µà¤°à¥à¤— à¤•à¥‡ à¤²à¤¿à¤ à¤†à¤µà¥‡à¤¦à¤¨ à¤¶à¥à¤²à¥à¤• {fee} à¤¹à¥ˆà¥¤",
        ))
    if isinstance(dates, dict) and dates.get("examDate"):
        candidates.append((
            "à¤ªà¤°à¥€à¤•à¥à¤·à¤¾ à¤•à¤¿à¤¸ à¤¤à¤¾à¤°à¥€à¤– à¤•à¥‹ à¤¹à¥‹à¤—à¥€?",
            f"à¤ªà¤°à¥€à¤•à¥à¤·à¤¾ {dates['examDate']} à¤•à¥‹ à¤†à¤¯à¥‹à¤œà¤¿à¤¤ à¤¹à¥‹à¤—à¥€à¥¤",
        ))
    if location:
        candidates.append((
            "à¤¯à¤¹ à¤­à¤°à¥à¤¤à¥€ à¤•à¤¿à¤¸ à¤•à¥à¤·à¥‡à¤¤à¥à¤°/à¤°à¤¾à¤œà¥à¤¯ à¤•à¥‡ à¤²à¤¿à¤ à¤¹à¥ˆ?",
            f"à¤¯à¤¹ à¤­à¤°à¥à¤¤à¥€ {location} à¤•à¥‡ à¤²à¤¿à¤ à¤¹à¥ˆà¥¤",
        ))
    status = structured.get("status") or ""
    if status in ("result", "final_selection"):
        action_q = "à¤ªà¤°à¤¿à¤£à¤¾à¤® à¤•à¤¹à¤¾à¤‚ à¤¦à¥‡à¤–à¤¾ à¤œà¤¾ à¤¸à¤•à¤¤à¤¾ à¤¹à¥ˆ?"
        action_a = "à¤Šà¤ªà¤° à¤¦à¤¿à¤ à¤—à¤ Important Links à¤¸à¥‡à¤•à¥à¤¶à¤¨ à¤®à¥‡à¤‚ Check Result à¤²à¤¿à¤‚à¤• à¤¸à¥‡ à¤ªà¤°à¤¿à¤£à¤¾à¤® à¤¦à¥‡à¤–à¤¾ à¤œà¤¾ à¤¸à¤•à¤¤à¤¾ à¤¹à¥ˆà¥¤"
    elif status == "admit_card":
        action_q = "à¤à¤¡à¤®à¤¿à¤Ÿ à¤•à¤¾à¤°à¥à¤¡ à¤•à¤¹à¤¾à¤‚ à¤¸à¥‡ à¤¡à¤¾à¤‰à¤¨à¤²à¥‹à¤¡ à¤•à¤°à¥‡à¤‚?"
        action_a = "à¤Šà¤ªà¤° à¤¦à¤¿à¤ à¤—à¤ Important Links à¤¸à¥‡à¤•à¥à¤¶à¤¨ à¤®à¥‡à¤‚ Download Admit Card à¤²à¤¿à¤‚à¤• à¤¸à¥‡ à¤à¤¡à¤®à¤¿à¤Ÿ à¤•à¤¾à¤°à¥à¤¡ à¤¡à¤¾à¤‰à¤¨à¤²à¥‹à¤¡ à¤•à¤¿à¤¯à¤¾ à¤œà¤¾ à¤¸à¤•à¤¤à¤¾ à¤¹à¥ˆà¥¤"
    elif status == "answer_key":
        action_q = "à¤‰à¤¤à¥à¤¤à¤° à¤•à¥à¤‚à¤œà¥€ à¤•à¤¹à¤¾à¤‚ à¤¦à¥‡à¤–à¥€ à¤œà¤¾ à¤¸à¤•à¤¤à¥€ à¤¹à¥ˆ?"
        action_a = "à¤Šà¤ªà¤° à¤¦à¤¿à¤ à¤—à¤ Important Links à¤¸à¥‡à¤•à¥à¤¶à¤¨ à¤®à¥‡à¤‚ Check Result à¤²à¤¿à¤‚à¤• à¤¸à¥‡ à¤‰à¤¤à¥à¤¤à¤° à¤•à¥à¤‚à¤œà¥€ à¤¦à¥‡à¤–à¥€ à¤œà¤¾ à¤¸à¤•à¤¤à¥€ à¤¹à¥ˆà¥¤"
    else:
        action_q = "à¤…à¤§à¤¿à¤• à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤”à¤° à¤†à¤µà¥‡à¤¦à¤¨ à¤•à¤¹à¤¾à¤‚ à¤¸à¥‡ à¤•à¤°à¥‡à¤‚?"
        action_a = "à¤Šà¤ªà¤° à¤¦à¤¿à¤ à¤—à¤ Important Links à¤¸à¥‡à¤•à¥à¤¶à¤¨ à¤®à¥‡à¤‚ Official Website à¤”à¤° Apply Online à¤²à¤¿à¤‚à¤• à¤¸à¥‡ à¤ªà¥‚à¤°à¥€ à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤¦à¥‡à¤–à¤•à¤° à¤†à¤µà¥‡à¤¦à¤¨ à¤•à¤° à¤¸à¤•à¤¤à¥‡ à¤¹à¥ˆà¤‚à¥¤"
    candidates.append((action_q, action_a))

    return [{"question": q, "answer": a} for q, a in candidates[:needed]]


def _get_or_build_description(structured, status):
    """description (Post Details summary) kabhi khaali na jaaye -
    agar AI ne poori tarah nahi bhara, to available structured data
    (title, org, vacancy, dates, location, status) se ek theek-thaak
    summary khud bana lete hain, status ke hisaab se alag."""
    existing = _as_text(structured.get("description")).strip()
    # Kam se kam 3 non-empty lines hon tabhi "poora bhara hua" maante hain
    non_empty_lines = [l for l in existing.split("\n") if l.strip()]
    if len(non_empty_lines) >= 3:
        return existing

    title = _as_text(structured.get("title")).strip()
    org = _as_text(structured.get("organization")).strip()
    vacancy = str(structured.get("vacancy") or "").strip()
    location = _clean_short_text(structured.get("jobLocation")) or "All India / à¤ªà¥‚à¤°à¥‡ à¤­à¤¾à¤°à¤¤ à¤®à¥‡à¤‚"
    dates = structured.get("importantDates") or {}

    lines = []
    if org:
        lines.append(f"à¤¯à¤¹ à¤¸à¥‚à¤šà¤¨à¤¾ {org} à¤¦à¥à¤µà¤¾à¤°à¤¾ à¤œà¤¾à¤°à¥€ à¤•à¥€ à¤—à¤ˆ à¤¹à¥ˆà¥¤")
    if title:
        lines.append(f"{title} à¤¸à¥‡ à¤œà¥à¤¡à¤¼à¥€ à¤ªà¥‚à¤°à¥€ à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤¨à¥€à¤šà¥‡ à¤¦à¥€ à¤—à¤ˆ à¤¹à¥ˆà¥¤")
    if vacancy and vacancy.isdigit():
        lines.append(f"à¤‡à¤¸à¤®à¥‡à¤‚ à¤•à¥à¤² {vacancy} à¤ªà¤¦ à¤¹à¥ˆà¤‚à¥¤")
    lines.append(f"à¤¯à¤¹ à¤…à¤µà¤¸à¤° {location} à¤•à¥‡ à¤‰à¤®à¥à¤®à¥€à¤¦à¤µà¤¾à¤°à¥‹à¤‚ à¤•à¥‡ à¤²à¤¿à¤ à¤‰à¤ªà¤²à¤¬à¥à¤§ à¤¹à¥ˆà¥¤")

    if status == "job":
        if isinstance(dates, dict) and dates.get("applicationEnd"):
            lines.append(f"à¤†à¤µà¥‡à¤¦à¤¨ à¤•à¤°à¤¨à¥‡ à¤•à¥€ à¤…à¤‚à¤¤à¤¿à¤® à¤¤à¤¿à¤¥à¤¿ {dates['applicationEnd']} à¤¹à¥ˆà¥¤")
        lines.append("à¤ªà¤¾à¤¤à¥à¤°à¤¤à¤¾, à¤†à¤µà¥‡à¤¦à¤¨ à¤¶à¥à¤²à¥à¤• à¤”à¤° à¤†à¤µà¥‡à¤¦à¤¨ à¤ªà¥à¤°à¤•à¥à¤°à¤¿à¤¯à¤¾ à¤•à¥€ à¤ªà¥‚à¤°à¥€ à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤¨à¥€à¤šà¥‡ à¤¦à¥€ à¤—à¤ˆ à¤¹à¥ˆà¥¤")
    elif status == "admit_card":
        lines.append("à¤à¤¡à¤®à¤¿à¤Ÿ à¤•à¤¾à¤°à¥à¤¡ à¤¡à¤¾à¤‰à¤¨à¤²à¥‹à¤¡ à¤•à¤°à¤¨à¥‡ à¤•à¥€ à¤ªà¥à¤°à¤•à¥à¤°à¤¿à¤¯à¤¾ à¤¨à¥€à¤šà¥‡ à¤¦à¥€ à¤—à¤ˆ à¤¹à¥ˆà¥¤")
        if isinstance(dates, dict) and dates.get("examDate"):
            lines.append(f"à¤ªà¤°à¥€à¤•à¥à¤·à¤¾ {dates['examDate']} à¤•à¥‹ à¤†à¤¯à¥‹à¤œà¤¿à¤¤ à¤¹à¥‹à¤—à¥€à¥¤")
    elif status == "answer_key":
        lines.append("à¤‰à¤¤à¥à¤¤à¤° à¤•à¥à¤‚à¤œà¥€ à¤¦à¥‡à¤–à¤¨à¥‡ à¤”à¤° à¤†à¤ªà¤¤à¥à¤¤à¤¿ à¤¦à¤°à¥à¤œ à¤•à¤°à¤¨à¥‡ à¤•à¥€ à¤ªà¥à¤°à¤•à¥à¤°à¤¿à¤¯à¤¾ à¤¨à¥€à¤šà¥‡ à¤¦à¥€ à¤—à¤ˆ à¤¹à¥ˆà¥¤")
    elif status in ("result", "final_selection"):
        lines.append("à¤ªà¤°à¤¿à¤£à¤¾à¤® à¤¦à¥‡à¤–à¤¨à¥‡ à¤”à¤° à¤†à¤—à¥‡ à¤•à¥€ à¤ªà¥à¤°à¤•à¥à¤°à¤¿à¤¯à¤¾ à¤•à¥€ à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤¨à¥€à¤šà¥‡ à¤¦à¥€ à¤—à¤ˆ à¤¹à¥ˆà¥¤")
        if isinstance(dates, dict) and dates.get("resultDate"):
            lines.append(f"à¤ªà¤°à¤¿à¤£à¤¾à¤® {dates['resultDate']} à¤•à¥‹ à¤˜à¥‹à¤·à¤¿à¤¤ à¤•à¤¿à¤¯à¤¾ à¤—à¤¯à¤¾à¥¤")
    elif status == "syllabus":
        lines.append("à¤ªà¥‚à¤°à¤¾ à¤ªà¤¾à¤ à¥à¤¯à¤•à¥à¤°à¤® (Syllabus) à¤”à¤° à¤ªà¤°à¥€à¤•à¥à¤·à¤¾ à¤ªà¥ˆà¤Ÿà¤°à¥à¤¨ à¤¨à¥€à¤šà¥‡ à¤¦à¤¿à¤ à¤—à¤ Important Links à¤¸à¥‡ à¤¡à¤¾à¤‰à¤¨à¤²à¥‹à¤¡ à¤•à¤¿à¤¯à¤¾ à¤œà¤¾ à¤¸à¤•à¤¤à¤¾ à¤¹à¥ˆà¥¤")

    lines.append("à¤…à¤§à¤¿à¤• à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤•à¥‡ à¤²à¤¿à¤ à¤¨à¥€à¤šà¥‡ à¤¦à¤¿à¤ à¤—à¤ Important Links à¤¸à¥‡à¤•à¥à¤¶à¤¨ à¤œà¤¼à¤°à¥‚à¤° à¤¦à¥‡à¤–à¥‡à¤‚à¥¤")
    return "\n".join(lines)


# ============================================================================
# ðŸ†• SHORT SUMMARY ("ðŸ“ à¤¸à¤‚à¤•à¥à¤·à¤¿à¤ªà¥à¤¤ à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€") - Sanity ke jobPost.shortSummary ke liye
# Sanity Studio ke niyam: sirf text, max 450 akshar, koi Link nahi. Bot seedha API
# se likhta hai (Studio ki jaanch lagu nahi hoti), isliye yahin saaf kiya jaata hai.
# ============================================================================
SHORT_SUMMARY_MAX = 420          # Studio ki seema 450 hai, thodi jagah chhodi
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
        end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "), cut.rfind("à¥¤"))
        text = cut[:end + 1] if end >= SHORT_SUMMARY_MIN else cut.rsplit(" ", 1)[0] + "..."
    return text.strip()


def _pretty_date(value):
    from datetime import datetime
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        return ""


def _fallback_short_summary(structured, status):
    """AI ne shortSummary na di ho (ya bahut chhoti ho) to sirf maujood tathyon se
    ek chhota English summary banata hai - koi nayi baat nahi jodta."""
    org = _as_text(structured.get("organization")).strip() or "The department"
    vacancy = str(structured.get("vacancy") or "").strip()
    dates = structured.get("importantDates") or {}
    if not isinstance(dates, dict):
        dates = {}

    if status == "job":
        first = (f"{org} has invited applications for {vacancy} posts." if vacancy.isdigit()
                 else f"{org} has released a recruitment notification.")
        d = _pretty_date(dates.get("applicationEnd"))
        second = f"The last date to apply is {d}." if d else ""
    elif status == "admit_card":
        first = f"{org} has released the admit card for its exam."
        d = _pretty_date(dates.get("examDate"))
        second = f"The exam is scheduled for {d}." if d else ""
    elif status == "answer_key":
        first = f"{org} has released the answer key."
        second = ""
    elif status == "final_selection":
        first = f"{org} has released the final selection or merit list."
        second = ""
    elif status == "result":
        first = f"{org} has declared the result."
        d = _pretty_date(dates.get("resultDate"))
        second = f"The result date is {d}." if d else ""
    else:
        first = f"{org} has published an official update."
        second = ""
    third = "Check the eligibility, how to apply and the official links below."
    return clean_short_summary(" ".join(x for x in (first, second, third) if x))


def build_short_summary(structured, status):
    text = clean_short_summary(structured.get("shortSummary"))
    if len(text) >= SHORT_SUMMARY_MIN:
        return text
    return _fallback_short_summary(structured, status)


def create_draft_job_post(structured, source_link, status_hint=None, official_links=None, raw_text=""):
    """Structured AI data se ek DRAFT jobPost document Sanity mein banata
    hai. _id 'drafts.' se shuru hota hai - isliye yeh KABHI public website
    par nahi dikhega jab tak Studio mein manually 'Publish' na dabaya jaaye."""

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

    # ðŸ†• CROSS-SOURCE DUPLICATE CHECK: agar yehi post (jaisa hi title)
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

    # ðŸ†• Organization ki website: pehle page se mili AADHIKARIK website, warna
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
        "seo": {
            "metaTitle": _as_text(structured.get("seoMetaTitle") or title)[:60],
            "metaDescription": (
                _as_text(structured.get("seoMetaDescription")).strip()
                or f"{title} - à¤ªà¥‚à¤°à¥€ à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€, à¤œà¤¼à¤°à¥‚à¤°à¥€ à¤¤à¤¾à¤°à¥€à¤–à¥‡à¤‚ à¤”à¤° Apply/Download à¤²à¤¿à¤‚à¤• à¤¯à¤¹à¤¾à¤‚ à¤¦à¥‡à¤–à¥‡à¤‚à¥¤"
            )[:160],
        },
        # ðŸ†• publishedAt/updatedAt: Studio mein yeh apne aap aaj ki date bhar
        # deta hai (initialValue), lekin woh sirf Studio UI ka trick hai -
        # seedhe API se likhte waqt yeh khud set karna padta hai, warna
        # khaali reh jaata (jo Schema.org dateModified ke liye zaroori hai)
        "publishedAt": _now_iso(),
        "updatedAt": _now_iso(),
    }

    # ðŸ†• IMPORTANT DATES - Application/Admit Card/Exam/Result dates
    important_dates = _build_important_dates(structured.get("importantDates"))
    if important_dates:
        doc["importantDates"] = important_dates

    # ðŸ†• JOB LOCATION - Google Jobs ke liye zaroori maana jaata hai
    # ðŸ†• jobLocation hamesha bharna chahiye (SEO/indexing ke liye) -
    # sirf Job hi nahi, har status ke liye
    job_location = _clean_short_text(structured.get("jobLocation"))
    if not job_location:
        job_location = "All India / à¤ªà¥‚à¤°à¥‡ à¤­à¤¾à¤°à¤¤ à¤®à¥‡à¤‚"
    doc["jobLocation"] = job_location[:100]

    # ðŸ†• APPLICATION FEE - teeno field mein se koi ek bhi mile to jodein
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

    # ðŸ†• SALARY / PAY SCALE
    if status == "job":
        salary_text = _clean_short_text(structured.get("salaryText"))
        salary_min = _safe_int(structured.get("salaryMin"))
        salary_max = _safe_int(structured.get("salaryMax"))
        if not salary_text and not salary_min and not salary_max:
            salary_text = "à¤µà¥‡à¤¤à¤¨à¤®à¤¾à¤¨ (Pay Scale) à¤•à¥€ à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤•à¥‡ à¤²à¤¿à¤ à¤†à¤§à¤¿à¤•à¤¾à¤°à¤¿à¤• à¤…à¤§à¤¿à¤¸à¥‚à¤šà¤¨à¤¾ à¤¦à¥‡à¤–à¥‡à¤‚à¥¤"
        salary_obj = {}
        if salary_text:
            salary_obj["payScaleText"] = salary_text[:150]
        if salary_min:
            salary_obj["minAmount"] = salary_min
        if salary_max:
            salary_obj["maxAmount"] = salary_max
        doc["salary"] = salary_obj

    # ðŸ†• CATEGORY-WISE VACANCY (UR/EWS/OBC/SC/ST/Total)
    cat_vacancy_raw = structured.get("categoryWiseVacancy")
    if isinstance(cat_vacancy_raw, dict):
        cat_vacancy = {}
        for key in ("ur", "ews", "obc", "sc", "st", "total"):
            val = _safe_int(cat_vacancy_raw.get(key))
            if val is not None:
                cat_vacancy[key] = val
        if cat_vacancy:
            doc["categoryWiseVacancy"] = cat_vacancy

    # ðŸ†• ADMIT CARD INFO / RESULT INFO - sirf jab status lagu ho
    if status == "admit_card":
        admit_info = _clean_short_text(structured.get("admitCardInfo")) or GENERIC_HOW_TO_DOWNLOAD_ADMIT_CARD
        doc["admitCardInfo"] = admit_info[:2000]

    if status in ("result", "final_selection"):
        result_info = _clean_short_text(structured.get("resultInfo")) or GENERIC_HOW_TO_CHECK_RESULT
        doc["resultInfo"] = result_info[:2000]

    # ðŸ†• STATUS TIMELINE - is naye status ko ek entry ke roop mein jod dete
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

    # ðŸ†• ELIGIBILITY + HOW TO APPLY - alag, proper sections ke roop mein
    # (description ke andar generic text ki jagah) - "customSectionsBeforeLinks"
    # mein jaate hain, isliye page par Important Links se PEHLE dikhenge
    before_links_sections = []
    eligibility_text = _clean_short_text(structured.get("eligibilityDetails"))
    if not eligibility_text:
        eligibility_text = _clean_short_text(structured.get("eligibilitySummary"))
    if not eligibility_text:
        eligibility_text = (
            "à¤ªà¤¾à¤¤à¥à¤°à¤¤à¤¾ à¤¸à¤‚à¤¬à¤‚à¤§à¥€ à¤ªà¥‚à¤°à¥€ à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤†à¤§à¤¿à¤•à¤¾à¤°à¤¿à¤• à¤¸à¥‚à¤šà¤¨à¤¾ (Official Notification) à¤®à¥‡à¤‚ à¤‰à¤ªà¤²à¤¬à¥à¤§ à¤¹à¥ˆ, "
            "à¤•à¥ƒà¤ªà¤¯à¤¾ à¤Šà¤ªà¤° à¤¦à¤¿à¤ à¤—à¤ Important Links à¤¸à¥‡à¤•à¥à¤¶à¤¨ à¤¸à¥‡ à¤¨à¥‹à¤Ÿà¤¿à¤«à¤¿à¤•à¥‡à¤¶à¤¨ à¤¦à¥‡à¤–à¥‡à¤‚à¥¤"
        )
    eligibility_section = _build_custom_section(
        "à¤ªà¤¾à¤¤à¥à¤°à¤¤à¤¾ à¤®à¤¾à¤¨à¤¦à¤‚à¤¡ (Eligibility Criteria)",
        eligibility_text,
    )
    if eligibility_section:
        before_links_sections.append(eligibility_section)

    # ðŸ†• Yeh section hamesha dikhna chahiye, par STATUS ke hisaab se alag
    # (Job -> How to Apply, Result -> How to Check Result, wagairah).
    # Agar AI ne specific steps na diye hon, to us status ka standard
    # generic process use kar lete hain.
    how_to_heading, how_to_fallback = HOW_TO_SECTION_CONFIG.get(status, HOW_TO_SECTION_CONFIG["job"])
    how_to_text = _clean_short_text(structured.get("howToApply"))
    if not how_to_text:
        how_to_text = how_to_fallback
    how_to_section = _build_custom_section(how_to_heading, how_to_text)
    if how_to_section:
        before_links_sections.append(how_to_section)

    if before_links_sections:
        doc["customSectionsBeforeLinks"] = before_links_sections

    # ðŸ†• FAQ hamesha kam se kam 5 dikhne chahiye - kam hon to available
    # data se aur bana lete hain
    faqs_list = structured.get("faqs") or []
    if not isinstance(faqs_list, list):
        faqs_list = []
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

    # ðŸ†• BANNER: Post ke hisaab se automatic banner banakar seedha
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
    mein reference ki tarah jodà¤¤à¥‡ hà¥ˆà¤‚à¥¤"""
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
    result = create_draft_job_post(
        structured, source_link, status_hint=status_hint,
        official_links=official, raw_text=raw_with_links,
    )
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


# ðŸ†• TELEGRAM REVIEW-BOT KE LIYE - draft ko padhna, sirf-kuch-fields patch
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
    """Eligibility wala custom-section poora naye sirre se banata hai
    (kyunki yeh ek 'array' field hai, seedha text patch nahi ho sakta)
    aur Sanity mein set kar deta hai."""
    section = _build_custom_section("à¤ªà¤¾à¤¤à¥à¤°à¤¤à¤¾ à¤®à¤¾à¤¨à¤¦à¤‚à¤¡ (Eligibility Criteria)", new_eligibility_text)
    current = get_draft_by_id(doc_id) or {}
    sections = current.get("customSectionsBeforeLinks", []) or []
    # Purana "Eligibility" section hata kar naya jodà¤¤à¥‡ hà¥ˆà¤‚, baaki jaise-the-waise
    sections = [s for s in sections if s.get("heading") != "à¤ªà¤¾à¤¤à¥à¤°à¤¤à¤¾ à¤®à¤¾à¤¨à¤¦à¤‚à¤¡ (Eligibility Criteria)"]
    if section:
        sections.insert(0, section)
    patch_sanity_fields(doc_id, {"customSectionsBeforeLinks": sections})


def rebuild_how_to_apply_section(doc_id, new_text):
    """How-to-Apply wala custom-section poora naye sirre se banata hai."""
    section = _build_custom_section("à¤†à¤µà¥‡à¤¦à¤¨ à¤•à¥ˆà¤¸à¥‡ à¤•à¤°à¥‡à¤‚ (How to Apply)", new_text)
    current = get_draft_by_id(doc_id) or {}
    sections = current.get("customSectionsBeforeLinks", []) or []
    sections = [s for s in sections if s.get("heading") != "à¤†à¤µà¥‡à¤¦à¤¨ à¤•à¥ˆà¤¸à¥‡ à¤•à¤°à¥‡à¤‚ (How to Apply)"]
    if section:
        sections.append(section)
    patch_sanity_fields(doc_id, {"customSectionsBeforeLinks": sections})


def rebuild_faq_section(doc_id, faqs_list):
    """FAQ section poora naye sirre se banata hai."""
    section = _build_faq_section(faqs_list)
    patch_sanity_fields(doc_id, {"customSectionsAfterLinks": [section] if section else []})


# ============================================================================
# ðŸ†• VISION AI - scanned PDF/photo se seedha "dekh kar" jaankari nikaalne
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
