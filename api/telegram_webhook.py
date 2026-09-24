# telegram_webhook.py
# 🆕 NAYI FILE - MUKHYA FILE
#
# Yeh Vercel Python function hai jo Telegram se aane wale har message ko
# pakadती hai (webhook ke through). Yahi poore "Human-in-the-Loop" review
# system ka dimaag hai:
#
#   1) User URL/PDF/Photo bhejta hai
#      -> Bot "yeh kis type ka post hai?" wale buttons dikhata hai
#   2) User button dabata hai (Job/Admit Card/Answer Key/Result/Final Selection)
#      -> Bot poora pipeline chalakar Sanity mein DRAFT banata hai
#      -> Draft ka summary Telegram par bhejta hai (Draft ID chhupi hoti hai)
#   3) User us summary-message ko REPLY karke natural-language command deta hai
#      (jaise "eligibility daal do", "important date bhi daal do")
#      -> Bot samajh kar sirf woh field update karta hai, naya summary bhejta hai
#   4) User "publish kar do" likh kar reply kare
#      -> Bot seedha Sanity mein PUBLISH kar deta hai
#
# 🆕 AB YEH FILE DASHBOARD SE BHI REQUEST LE SAKTI HAI:
#   Agar request mein "X-Dashboard-Secret" header sahi ho, to Telegram
#   wale purane logic ko chhoo tak nahi, ek bilkul alag (naya) rasta
#   istemal hota hai - handle_dashboard_request().

import os
import sys
import json
import re
import base64
import time
import requests
from http.server import BaseHTTPRequestHandler

# 🔧 ZAROORI: Do jagah se files import karni hain -
#   1) Repo ke ROOT se (scraper.py, sanity_publisher.py, config.py,
#      banner_generator.py) - yeh WAHI files hain jo GitHub Actions wala
#      bot (main.py) bhi istemal karta hai, isliye kahin bhi duplicate
#      nahi karna pada
#   2) api/_lib se - yahan sirf woh NAYI files hain jo sirf is
#      interactive Telegram-bot ke liye banayi gayi hain
_current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_current_dir, ".."))       # repo root
sys.path.insert(0, os.path.join(_current_dir, "_lib"))     # api/_lib

from config import (
    TELEGRAM_CHAT_ID, TELEGRAM_WEBHOOK_SECRET,
    SANITY_PROJECT_ID, SANITY_DATASET, SANITY_API_TOKEN, SANITY_API_VERSION,
)
from scraper import fetch_full_details_with_pdf, fetch_page_title
from sanity_publisher import (
    publish_scraped_post, get_draft_by_id, patch_sanity_fields,
    publish_draft_now, rebuild_eligibility_section,
    rebuild_how_to_apply_section, rebuild_faq_section, call_vision_ai,
)
from telegram_interactive import (
    send_message, edit_message, answer_callback_query,
    status_choice_keyboard, download_telegram_file,
)
from vercel_pdf_reader import extract_pdf_text_or_images, photo_bytes_to_base64
from command_interpreter import interpret_command
from draft_summary import format_draft_summary


DRAFT_ID_PATTERN = re.compile(r"Draft ID:\s*([a-zA-Z0-9._-]+)")


def _extract_draft_id(message_obj):
    """Reply kiye gaye message ke text mein se Draft ID nikaalta hai -
    isi trick se hume pata chalta hai kaunsa draft update karna hai,
    koi alag database nahi chahiye."""
    if not message_obj:
        return None
    text = message_obj.get("text", "")
    match = DRAFT_ID_PATTERN.search(text)
    return match.group(1) if match else None


def _is_authorized(chat_id):
    """Sirf aapka apna Telegram chat hi is bot se baat kar sakta hai -
    koi aur nahi."""
    return str(chat_id) == str(TELEGRAM_CHAT_ID)


# Pending input ko "status choose karne" tak yaad rakhne ke liye - hum
# yeh bhi seedha Telegram ke reply-chain se karte hain: jab bot status
# choose karne wale buttons bhejta hai, woh message user ke ASLI
# (URL/PDF/Photo wale) message ka REPLY hota hai. Jab user button
# dabata hai, callback_query.message.reply_to_message mein woh asli
# message wapas mil jaata hai.

def handle_new_input(chat_id, message):
    """User ne URL/PDF/Photo bheja - status choose karne wale buttons
    dikhata hai (asli message ko REPLY karte hue)."""
    if "document" in message:
        prompt = "📄 PDF mili. Yeh post kis type ka hai?"
    elif "photo" in message:
        prompt = "🖼️ Photo mili. Yeh post kis type ka hai?"
    else:
        prompt = "🔗 Link mila. Yeh post kis type ka hai?"

    send_message(
        chat_id, prompt,
        reply_markup=status_choice_keyboard(),
        reply_to_message_id=message["message_id"],
    )


def _get_source_text_and_title(original_message):
    """URL/PDF/Photo teeno tareekon se asli text (ya vision-AI se
    nikaala hua jawab) aur ek title nikaalta hai."""
    if "document" in original_message:
        file_id = original_message["document"]["file_id"]
        pdf_bytes = download_telegram_file(file_id)
        if not pdf_bytes:
            return "", "(PDF download nahi ho paayi)"
        text, images_b64 = extract_pdf_text_or_images(pdf_bytes)
        if text:
            return text, original_message["document"].get("file_name", "Uploaded PDF")
        if images_b64:
            vision_text = call_vision_ai(
                "Yeh ek sarkari naukri notice ke pages hain. Inme jo bhi Hindi/English "
                "text likha hai, use jaisa hai waisa hi (poora, bina chhode) likh kar do.",
                images_b64,
            )
            return vision_text, original_message["document"].get("file_name", "Uploaded PDF")
        return "", "(PDF se kuch nahi mila)"

    if "photo" in original_message:
        # Telegram photo ke kai sizes bhejta hai - sabse badi (aakhri) lete hain
        file_id = original_message["photo"][-1]["file_id"]
        photo_bytes = download_telegram_file(file_id)
        if not photo_bytes:
            return "", "(Photo download nahi ho paayi)"
        img_b64 = photo_bytes_to_base64(photo_bytes)
        vision_text = call_vision_ai(
            "Yeh ek sarkari naukri notice ka screenshot hai. Ismein jo bhi Hindi/English "
            "text likha hai, use jaisa hai waisa hi (poora, bina chhode) likh kar do.",
            [img_b64],
        )
        return vision_text, "Uploaded Screenshot"

    # Warna, yeh ek text/URL message hai
    url = original_message.get("text", "").strip()
    page_title = fetch_page_title(url)
    full_text = fetch_full_details_with_pdf(url)
    return full_text, (page_title or url)


def handle_status_chosen(chat_id, callback_query):
    """User ne status button dabaya - poora pipeline chalata hai aur
    draft summary bhejta hai."""
    status = callback_query["data"].replace("status:", "")
    prompt_message = callback_query["message"]
    original_message = prompt_message.get("reply_to_message")

    answer_callback_query(callback_query["id"], "⏳ Kaam shuru...")
    edit_message(chat_id, prompt_message["message_id"], f"⏳ Post ban raha hai ({status})...")

    if not original_message:
        edit_message(chat_id, prompt_message["message_id"], "❌ Galti: asli message nahi mila, dobara try karein")
        return

    source_link = original_message.get("text", "") or "https://manual-upload.local/" + str(prompt_message["message_id"])

    try:
        full_text, title = _get_source_text_and_title(original_message)
        raw_for_ai = (
            f"Title: {title}\n"
            f"Likely Status: {status} (user ne khud chuna hai, ISI ko istemal karo)\n"
            f"Notice Link: {source_link}\n\n"
            f"Page Content:\n{full_text}"
        )
        result = publish_scraped_post(raw_for_ai, source_link, status_hint=status)

        if result.get("duplicate"):
            edit_message(chat_id, prompt_message["message_id"],
                         f"⚠️ Yeh post pehle se maujood hai (duplicate): {result['title']}")
            return

        draft_doc = get_draft_by_id(result["draftId"])
        summary = format_draft_summary(draft_doc)
        edit_message(chat_id, prompt_message["message_id"], summary)

    except Exception as e:
        edit_message(chat_id, prompt_message["message_id"], f"❌ Galti aayi: {e}")


def handle_review_command(chat_id, message):
    """User ne draft-summary message ko reply karke command diya hai -
    AI se samjhwa kar sahi field update karta hai."""
    draft_id = _extract_draft_id(message.get("reply_to_message"))
    if not draft_id:
        send_message(chat_id, "⚠️ Yeh message kisi draft-summary ka reply nahi lag raha - "
                              "kripya draft wale message ko hi reply karein.")
        return

    user_command = message.get("text", "").strip()
    draft_doc = get_draft_by_id(draft_id)
    if not draft_doc:
        send_message(chat_id, "❌ Yeh draft ab nahi mil raha (shayad publish ho chuka hai)")
        return

    # "publish kar do" jaisa seedha shortcut bhi pakad lete hain, bina AI call kiye
    if re.search(r"\bpublish\b", user_command, re.IGNORECASE):
        try:
            published_id = publish_draft_now(draft_id)
            send_message(chat_id, f"🎉 Publish ho gaya! ID: {published_id}",
                        reply_to_message_id=message["message_id"])
        except Exception as e:
            send_message(chat_id, f"❌ Publish karte waqt galti: {e}",
                        reply_to_message_id=message["message_id"])
        return

    send_message(chat_id, "⏳ Samajh raha hoon...", reply_to_message_id=message["message_id"])

    try:
        source_link = draft_doc.get("sourceUrl", "")
        source_text = fetch_full_details_with_pdf(source_link) if source_link.startswith("http") else ""

        org_ref = draft_doc.get("organization")
        org_name = org_ref.get("name") if isinstance(org_ref, dict) else ""

        instructions = interpret_command(
            user_command, source_text,
            draft_doc.get("title"), draft_doc.get("status"), org_name,
        )

        action = instructions.get("action", "unclear")
        if action == "unclear":
            send_message(chat_id, f"🤔 {instructions.get('explanation', 'Samajh nahi aaya, phir se koshish karein')}")
            return

        if action == "publish":
            published_id = publish_draft_now(draft_id)
            send_message(chat_id, f"🎉 Publish ho gaya! ID: {published_id}")
            return

        # Simple (seedhe patch ho sakne wale) fields
        simple_fields = instructions.get("simple_fields") or {}
        simple_fields = {k: v for k, v in simple_fields.items() if v}
        if simple_fields:
            patch_sanity_fields(draft_id, simple_fields)

        # Array-based sections - inhe poora naye sirre se banana padta hai
        if instructions.get("eligibilityDetails"):
            rebuild_eligibility_section(draft_id, instructions["eligibilityDetails"])
        if instructions.get("howToApply"):
            rebuild_how_to_apply_section(draft_id, instructions["howToApply"])
        if instructions.get("faqs"):
            rebuild_faq_section(draft_id, instructions["faqs"])

        updated_doc = get_draft_by_id(draft_id)
        summary = format_draft_summary(updated_doc)
        send_message(chat_id, f"✅ {instructions.get('explanation', 'Update ho gaya')}\n\n{summary}")

    except Exception as e:
        send_message(chat_id, f"❌ Update karte waqt galti aayi: {e}")


def process_update(update):
    """Ek Telegram update (message ya button-press) ko sahi jagah bhejta hai."""
    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        if not _is_authorized(chat_id):
            return
        if cq.get("data", "").startswith("status:"):
            handle_status_chosen(chat_id, cq)
        return

    if "message" not in update:
        return

    message = update["message"]
    chat_id = message["chat"]["id"]
    if not _is_authorized(chat_id):
        return

    if "reply_to_message" in message:
        handle_review_command(chat_id, message)
        return

    if "document" in message or "photo" in message or message.get("text", "").startswith("http"):
        handle_new_input(chat_id, message)
        return

    send_message(chat_id, "👋 Kisi notice ka link bhejein, PDF upload karein, ya screenshot bhejein.")


# ============================================================
# 🆕 DASHBOARD BRIDGE - neeche sab kuch NAYA hai
# Yeh Telegram flow se bilkul alag hai, isliye upar wale kisi
# bhi function ko chhoo nahi raha.
# ============================================================

def _text_from_dashboard_input(input_type, content, file_b64, file_mime, file_name):
    """Dashboard se seedha aaya hua input (link/text/file) se poora text
    aur ek title nikaalta hai - Telegram wale _get_source_text_and_title
    jaisa hi kaam, bas Telegram message format ke bina."""
    if input_type == "file" and file_b64:
        is_pdf = "pdf" in (file_mime or "").lower() or (file_name or "").lower().endswith(".pdf")
        if is_pdf:
            raw_bytes = base64.b64decode(file_b64)
            text, images_b64 = extract_pdf_text_or_images(raw_bytes)
            if text:
                return text, (file_name or "Uploaded PDF")
            if images_b64:
                vision_text = call_vision_ai(
                    "Yeh ek sarkari naukri notice ke pages hain. Inme jo bhi Hindi/English "
                    "text likha hai, use jaisa hai waisa hi (poora, bina chhode) likh kar do.",
                    images_b64,
                )
                return vision_text, (file_name or "Uploaded PDF")
            return "", "(PDF se kuch nahi mila)"
        else:
            # Photo/Screenshot - client base64 pehle se bina "data:" prefix ke bhejega
            vision_text = call_vision_ai(
                "Yeh ek sarkari naukri notice ka screenshot hai. Ismein jo bhi Hindi/English "
                "text likha hai, use jaisa hai waisa hi (poora, bina chhode) likh kar do.",
                [file_b64],
            )
            return vision_text, (file_name or "Uploaded Screenshot")

    content = (content or "").strip()
    if content.startswith("http"):
        page_title = fetch_page_title(content)
        full_text = fetch_full_details_with_pdf(content)
        return full_text, (page_title or content)
    return content, "Dashboard Text Input"


def handle_dashboard_generate(body):
    status = body.get("status") or "Job"
    input_type = body.get("inputType", "text")
    content = body.get("content", "")
    file_b64 = body.get("fileBase64")
    file_mime = body.get("fileMime", "")
    file_name = body.get("fileName", "")

    full_text, title = _text_from_dashboard_input(input_type, content, file_b64, file_mime, file_name)

    if input_type == "link" and content.strip().startswith("http"):
        source_link = content.strip()
    else:
        source_link = "https://dashboard-upload.local/" + str(int(time.time()))

    raw_for_ai = (
        f"Title: {title}\n"
        f"Likely Status: {status} (user ne khud chuna hai, ISI ko istemal karo)\n"
        f"Notice Link: {source_link}\n\n"
        f"Page Content:\n{full_text}"
    )
    result = publish_scraped_post(raw_for_ai, source_link, status_hint=status)

    if result.get("duplicate"):
        return {"error": f"Yeh post pehle se maujood hai (duplicate): {result.get('title')}"}, 409

    draft_doc = get_draft_by_id(result["draftId"])
    summary = format_draft_summary(draft_doc)
    return {"draftId": result["draftId"], "draft": summary}, 200


def handle_dashboard_publish(body):
    draft_id = body.get("draftId")
    if not draft_id:
        return {"error": "draftId zaroori hai"}, 400
    published_id = publish_draft_now(draft_id)
    return {"publishedId": published_id}, 200


def handle_dashboard_list_posts(body):
    limit = int(body.get("limit", 15))
    query = (
        '*[_type == "jobPost"] | order(_createdAt desc)[0...%d]'
        '{_id, title, status, _createdAt, "orgName": organization->name}' % limit
    )
    url = f"https://{SANITY_PROJECT_ID}.api.sanity.io/{SANITY_API_VERSION}/data/query/{SANITY_DATASET}"
    resp = requests.get(
        url,
        params={"query": query},
        headers={"Authorization": f"Bearer {SANITY_API_TOKEN}"},
        timeout=15,
    )
    resp.raise_for_status()
    posts = resp.json().get("result", [])
    return {"posts": posts}, 200


def handle_dashboard_request(body):
    action = body.get("action")
    try:
        if action == "generate":
            return handle_dashboard_generate(body)
        if action == "publish":
            return handle_dashboard_publish(body)
        if action == "list_posts":
            return handle_dashboard_list_posts(body)
        return {"error": "unknown action"}, 400
    except Exception as e:
        return {"error": str(e)}, 500


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(length)

        # 🆕 Dashboard se aaya hua request - alag tarike se handle karte hain,
        # Telegram wale purane flow ko bilkul touch nahi karte
        dashboard_secret_header = self.headers.get("X-Dashboard-Secret", "")
        expected_dashboard_secret = os.environ.get("DASHBOARD_SHARED_SECRET", "")

        if expected_dashboard_secret and dashboard_secret_header == expected_dashboard_secret:
            try:
                body = json.loads(body_bytes)
                result, status_code = handle_dashboard_request(body)
            except Exception as e:
                result, status_code = {"error": str(e)}, 500
            self.send_response(status_code)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
            return

        # 🔒 Suraksha: Telegram ka secret-token header check karte hain
        # taaki koi aur random URL na hit kar sake (PURANA FLOW, waisa hi hai)
        secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if TELEGRAM_WEBHOOK_SECRET and secret != TELEGRAM_WEBHOOK_SECRET:
            self.send_response(403)
            self.end_headers()
            return

        try:
            update = json.loads(body_bytes)
            process_update(update)
        except Exception as e:
            print(f"[ERROR] Webhook process karte waqt dikkat: {e}")

        # Telegram ko hamesha turant 200 bhej dena chahiye, warna woh
        # baar-baar wahi message dobara bhejta rahega
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Telegram webhook is running.")
