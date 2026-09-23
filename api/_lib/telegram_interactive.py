# telegram_interactive.py
# 🆕 NAYI FILE
#
# Yeh file Telegram Bot API se seedha baat karti hai - naya message
# bhejna, purana message EDIT karna (taaki draft-review ek hi message
# mein update hota rahe, spam na ho), buttons (inline keyboard) dikhana,
# aur user ne jo photo/PDF bheji hai use download karna.
#
# Yeh purane 'telegram_bot.py' (jo sirf ek-tarfa alert bhejta tha) se
# ALAG hai - yeh do-tarfa (interactive) baat cheet ke liye hai.

import requests

from config import TELEGRAM_BOT_TOKEN

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
FILE_BASE = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"


def send_message(chat_id, text, reply_markup=None, reply_to_message_id=None):
    """Naya message bhejta hai. reply_markup se inline buttons ban sakte
    hain. reply_to_message_id se message kisi purane message ka 'reply'
    banta hai (isi trick se hum yaad rakhte hain kaunsa draft chal raha
    hai - koi alag database nahi chahiye)."""
    payload = {
        "chat_id": chat_id,
        "text": text[:4000],  # Telegram ki apni limit
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    try:
        resp = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=20)
        return resp.json()
    except Exception as e:
        print(f"[ERROR] Telegram message bhejte waqt dikkat: {e}")
        return None


def edit_message(chat_id, message_id, text, reply_markup=None):
    """Purana message EDIT karta hai (naya nahi bhejta) - draft-summary
    ko baar-baar update karne ke liye istemal hota hai, taaki chat saaf
    rahe."""
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text[:4000],
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        resp = requests.post(f"{API_BASE}/editMessageText", json=payload, timeout=20)
        return resp.json()
    except Exception as e:
        print(f"[ERROR] Telegram message edit karte waqt dikkat: {e}")
        return None


def answer_callback_query(callback_query_id, text=None):
    """Jab user koi button dabaye, Telegram ko turant 'OK mila' bata dena
    zaroori hai, warna button 'loading' hi dikhta rehta hai."""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        requests.post(f"{API_BASE}/answerCallbackQuery", json=payload, timeout=10)
    except Exception:
        pass


def status_choice_keyboard():
    """Post-type chunne wale buttons (Job/Admit Card/Answer Key/Result/
    Final Selection/Syllabus) - inline keyboard format mein."""
    buttons = [
        [{"text": "🟢 Job", "callback_data": "status:job"},
         {"text": "🟡 Admit Card", "callback_data": "status:admit_card"}],
        [{"text": "🔵 Answer Key", "callback_data": "status:answer_key"},
         {"text": "🔴 Result", "callback_data": "status:result"}],
        [{"text": "⚫ Final Selection", "callback_data": "status:final_selection"}],
    ]
    return {"inline_keyboard": buttons}


def download_telegram_file(file_id):
    """User ne jo PDF ya photo bheji hai, uski asli file bytes download
    karta hai. Telegram mein pehle 'getFile' se path maangna padta hai,
    phir usi path se asli file milti hai."""
    try:
        resp = requests.get(f"{API_BASE}/getFile", params={"file_id": file_id}, timeout=20)
        file_path = resp.json()["result"]["file_path"]
        file_resp = requests.get(f"{FILE_BASE}/{file_path}", timeout=45)
        return file_resp.content
    except Exception as e:
        print(f"[ERROR] Telegram file download karte waqt dikkat: {e}")
        return None
