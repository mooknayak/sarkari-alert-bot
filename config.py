# config.py
#
# SURAKSHA: Telegram Token/Chat ID ab is file mein NAHI likhe - Railway ke
# "Variables" tab se (environment variable ke through) aate hain. Isse
# GitHub par code dekhne wale kisi ko bhi aapka asli token nahi dikhega.

import os

SOURCE_GROUPS = {

    # ============================================================
    # 🔧 CURATED (chhota, tez): Pehle 137 sources thay - ab sirf
    # sabse zaroori 38 rakhe hain, taaki har check jaldi (kam samay
    # mein) poora ho jaaye. 3 group hain: Top National Sansthan,
    # UP ke Mukhya Vibhag, aur Vishwasniya Private Portal.
    # ============================================================

    "Top 20 Rashtriya Sansthan": [
        {"department": "UPSC", "type": "scrape", "url": "https://www.upsc.gov.in"},
        {"department": "SSC", "type": "scrape", "url": "https://ssc.gov.in"},
        {"department": "RRB / RRC (Railway)", "type": "scrape", "url": "https://www.rrcb.gov.in"},
        {"department": "IBPS (Banking)", "type": "scrape", "url": "https://www.ibps.in"},
        {"department": "Indian Army", "type": "scrape", "url": "https://joinindianarmy.nic.in"},
        {"department": "Indian Navy", "type": "scrape", "url": "https://joinindiannavy.gov.in"},
        {"department": "Indian Air Force", "type": "scrape", "url": "https://careerairforce.gov.in"},
        {"department": "SBI", "type": "scrape", "url": "https://sbi.co.in"},
        {"department": "RBI", "type": "scrape", "url": "https://www.rbi.org.in"},
        {"department": "LIC", "type": "scrape", "url": "https://licindia.in"},
        {"department": "EPFO", "type": "scrape", "url": "https://www.epfindia.gov.in"},
        {"department": "ESIC", "type": "scrape", "url": "https://www.esic.nic.in"},
        {"department": "AIIMS", "type": "scrape", "url": "https://www.aiims.edu"},
        {"department": "ISRO", "type": "scrape", "url": "https://www.isro.gov.in"},
        {"department": "DRDO", "type": "scrape", "url": "https://www.drdo.gov.in"},
        {"department": "Postal Department (India Post)", "type": "scrape", "url": "https://www.indiapost.gov.in"},
        {"department": "FCI", "type": "scrape", "url": "https://fci.gov.in"},
        {"department": "NVS (Navodaya Vidyalaya)", "type": "scrape", "url": "https://navodaya.gov.in"},
        {"department": "KVS (Kendriya Vidyalaya)", "type": "scrape", "url": "https://kvsangathan.nic.in"},
        {"department": "National Career Service", "type": "scrape", "url": "https://www.ncs.gov.in"},
    ],

    "Uttar Pradesh - Mukhya Vibhag": [
        {"department": "UPPSC", "type": "scrape", "url": "https://uppsc.up.nic.in"},
        {"department": "UPSSSC", "type": "scrape", "url": "https://upsssc.gov.in"},
        {"department": "UP Police (UPPRPB)", "type": "scrape", "url": "https://uppbpb.gov.in"},
        {"department": "UP Basic Shiksha Board (UPEB)", "type": "scrape", "url": "http://basiceduboard.up.gov.in"},
        {"department": "UP Madhyamik Shiksha Parishad (UPMSP)", "type": "scrape", "url": "https://upmsp.edu.in"},
        {"department": "UPPCL (Power Corporation)", "type": "scrape", "url": "https://www.uppcl.org"},
        {"department": "Sewayojan UP (Rojgar Portal)", "type": "scrape", "url": "https://sewayojan.up.nic.in"},
        {"department": "UPHESC (College Teachers)", "type": "scrape", "url": "https://uphesc.org"},
    ],

    "Vishwasniya Private Portal (Top 10)": [
        {"department": "Sarkari Result", "type": "scrape", "url": "https://www.sarkariresult.com/"},
        {"department": "Free Job Alert", "type": "scrape", "url": "https://www.freejobalert.com/"},
        {"department": "Sarkari Result (.com.cm)", "type": "scrape", "url": "https://sarkariresult.com.cm/"},
        {"department": "Sarkari Exam", "type": "scrape", "url": "https://www.sarkariexam.com/"},
        {"department": "Sarkari Job Find", "type": "scrape", "url": "https://sarkarijobfind.com/"},
        {"department": "Amar Ujala - Jobs", "type": "rss", "url": "https://results.amarujala.com/rss/jobs.xml"},
        {"department": "Amar Ujala - Admit Card", "type": "rss", "url": "https://results.amarujala.com/rss/admit-card.xml"},
        {"department": "Amar Ujala - Result", "type": "rss", "url": "https://results.amarujala.com/rss/results-alert.xml"},
        {"department": "Amar Ujala - Answer Key", "type": "rss", "url": "https://results.amarujala.com/rss/answer-keys.xml"},
        {"department": "Amar Ujala - Exam Alert", "type": "rss", "url": "https://results.amarujala.com/rss/exam-alerts.xml"},
    ],
}

GROUP_NAMES = list(SOURCE_GROUPS.keys())

ALLOWED_CATEGORIES = ["Notification", "Admit Card", "Result", "Answer Key"]

# ============ SURAKSHIT TAREEKA: Token/ID ab yahan nahi likha ============
# Yeh Railway ke "Variables" tab se (environment variable se) aayega.
# GitHub par is file mein ab koi bhi asli token/ID nahi dikhega.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print("[CHETAVANI] TELEGRAM_BOT_TOKEN ya TELEGRAM_CHAT_ID nahi mila! "
          "Railway ke 'Variables' tab mein jaakar dono add karein.")

CHECK_INTERVAL_MINUTES = 20

# Ab GROUPS_PER_CYCLE ki jagah - ek saath (parallel) max kitni websites
# check ho sakti hain. Isse zyada nahi rakhna, warna Railway ke server
# (1GB RAM) par load zyada ho sakta hai.
MAX_CONCURRENT_SOURCES = 15
CLEANUP_AFTER_DAYS = 90
# Database file ka path - agar Railway par Volume mount kiya ho, to woh
# path use hoga (taaki data redeploy par na mite), warna local file.
DATABASE_FILE = os.environ.get("DATABASE_FILE", "posts.db")


# ============================================================================
# 🆕 NAYA HISSA: Bot ko seedhe Sanity CMS (website ke backend) se jodne ke
# liye zaroori settings. Yeh sab bhi Railway ke "Variables" tab se aayenge -
# is file mein koi asli key/token nahi likhi jaati.
# ============================================================================

# Website ke Sanity project ki details - yeh website ke .env mein
# NEXT_PUBLIC_SANITY_PROJECT_ID / NEXT_PUBLIC_SANITY_DATASET jaisi hi honi
# chahiye (Sanity ke Manage Project dashboard se bhi mil jaayengi).
SANITY_PROJECT_ID = os.environ.get("SANITY_PROJECT_ID", "")
SANITY_DATASET = os.environ.get("SANITY_DATASET", "production")
SANITY_API_VERSION = os.environ.get("SANITY_API_VERSION", "2024-01-01")

# ⚠️ IMPORTANT: Yeh token website ke SANITY_API_TOKEN se ALAG rakhna behtar
# hai - Sanity Manage Dashboard > API > Tokens mein jaakar "Editor"
# permission wala ek naya token banayein (Admin permission mat dein).
SANITY_API_TOKEN = os.environ.get("SANITY_API_TOKEN", "")

# Post ka content likhne/format karne ke liye AI - ab TEEN providers rakhe
# hain taaki ek fail ho (jaisa Gemini/Groq ke saath ho raha tha) to bot
# khud-ba-khud agle par switch ho jaaye:
#
#  1) OPENROUTER - PEHLI PASAND (primary): sabse aasaan sign-up (Google/
#     GitHub se, koi phone-verification nahi), openrouter.ai/keys se free
#     key ban jaati hai.
#  2) GROQ - dusra backup (agar account bana ho to)
#  3) GEMINI - aakhri backup
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# 🔒 SURAKSHA SWITCH: Jab tak yeh "true" na ho, bot sirf Telegram alert
# bhejega - Sanity mein kuch nahi likhega. Pehle isse OFF (false) rakh kar
# test karein, sab theek lage tabhi Railway Variables mein "true" set karein.
AUTO_PUBLISH_TO_SANITY = os.environ.get("AUTO_PUBLISH_TO_SANITY", "false").lower() == "true"
