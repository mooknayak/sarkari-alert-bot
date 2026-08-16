# telegram_bot.py
# Yahan se Telegram par aapke mobile per alert bheja jaata hai

import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_alert(department, title, category, vacancy, link, source_site, apply_link=None):
    """Ek naya post milne par Telegram par short-form message bhejta hai"""
    apply_line = apply_link if apply_link else f"{link} (isi notice link par jaakar dekhein)"

    message = (
        f"📢 {department}\n"
        f"पद/शीर्षक: {title}\n"
        f"कुल पद: {vacancy}\n"
        f"स्थिति: {category}\n"
        f"🔗 नोटिस लिंक: {link}\n"
        f"📝 Apply Online: {apply_line}\n"
        f"🏢 विभाग की वेबसाइट: {source_site}"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}

    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code != 200:
            print(f"[ERROR] Telegram message nahi bheja gaya: {response.text}")
    except Exception as e:
        print(f"[ERROR] Telegram bhejte waqt dikkat: {e}")
