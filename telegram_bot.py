# telegram_bot.py
# Yahan se Telegram par aapke mobile per alert bheja jaata hai
#
# 🆕 SUDHAR:
#  - Alert mein ab teeno cheezein: Apply/Admit/Result link (AADHIKARIK),
#    Official Notification (PDF) link, aur Official Website.
#  - send_alert() ab True/False lautata hai - taaki bhejna fail hone par post
#    "dekhi hui" na maani jaaye aur agli baar phir koshish ho.
#  - send_text() - bot ki sehat-report jaise sade message ke liye.

import time
import threading
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# Jab ek saath kai websites check ho rahi hon aur ek saath 2-3 naye
# alerts bane, to yeh lock unhe ek-ek karke (order se) Telegram par
# bhejta hai - Telegram ki apni rate-limit se bachne ke liye
SEND_LOCK = threading.Lock()

NOT_FOUND = "नहीं मिला (पोस्ट लिंक खोलकर देखें)"


def _post_message(text):
    """Ek message bhejta hai. Safal ho to True. Telegram 429 (bahut tezi)
    de to bataye gaye second ruk kar ek baar phir koshish karta hai."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    for attempt in (1, 2):
        try:
            response = requests.post(url, data=payload, timeout=15)
            if response.status_code == 200:
                return True
            if response.status_code == 429 and attempt == 1:
                try:
                    wait = int(response.json().get("parameters", {}).get("retry_after", 5))
                except Exception:
                    wait = 5
                time.sleep(min(wait, 30))
                continue
            print(f"[ERROR] Telegram message nahi bheja gaya: {response.text}")
            return False
        except Exception as e:
            print(f"[ERROR] Telegram bhejte waqt dikkat: {e}")
            return False
    return False


def send_alert(department, title, category, vacancy, link, source_site,
               apply_link=None, notification_link=None, primary_label="📝 Apply Online"):
    """Ek naya post milne par Telegram par short-form message bhejta hai.
    link = us post ka link (jahan se mili), apply_link = AADHIKARIK
    Apply/Admit Card/Result link, notification_link = aadhikarik
    notification (aksar PDF), source_site = vibhag ki aadhikarik website."""
    lines = [
        f"📢 {department}",
        f"पद/शीर्षक: {title}",
    ]
    if vacancy and vacancy != "N/A":
        lines.append(f"कुल पद: {vacancy}")
    lines += [
        f"स्थिति: {category}",
        f"🔗 पोस्ट लिंक: {link}",
        f"{primary_label}: {apply_link or NOT_FOUND}",
        f"📄 आधिकारिक नोटिफिकेशन: {notification_link or NOT_FOUND}",
        f"🏢 आधिकारिक वेबसाइट: {source_site or 'नहीं मिली'}",
    ]
    message = "\n".join(lines)

    with SEND_LOCK:
        ok = _post_message(message)
        time.sleep(1)  # Telegram ki rate-limit se bachne ke liye thoda gap
        return ok


def send_text(text):
    """Koi bhi sada text message (jaise sehat-report) bhejta hai."""
    with SEND_LOCK:
        ok = _post_message(text)
        time.sleep(1)
        return ok
