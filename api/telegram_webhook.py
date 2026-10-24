import os
import sys
import json
import re
import base64
import time
import requests
from http.server import BaseHTTPRequestHandler

_current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_current_dir, ".."))       # repo root
sys.path.insert(0, os.path.join(_current_dir, "_lib"))     # api/_lib

from config import TELEGRAM_CHAT_ID, TELEGRAM_WEBHOOK_SECRET
from scraper import fetch_full_details_with_pdf, fetch_page_title
from sanity_publisher import (
    publish_scraped_post, get_draft_by_id, patch_sanity_fields,
    publish_draft_now, rebuild_eligibility_section,
    rebuild_how_to_apply_section, rebuild_faq_section, call_vision_ai,
    start_request_clock, clear_request_clock, add_hindi_to_draft, hindi_last_error,
)
from telegram_interactive import (
    send_message, edit_message, answer_callback_query,
    status_choice_keyboard, download_telegram_file,
)
from vercel_pdf_reader import extract_pdf_text_or_images, photo_bytes_to_base64
from command_interpreter import interpret_command
from draft_summary import format_draft_summary


DRAFT_ID_PATTERN = re.compile(r"Draft ID:\s*([a-zA-Z0-9._-]+)")


_HINDI_CMD_RE = re.compile(r"hindi|hin\u0926\u0940|\u0939\u093f\u0902\u0926\u0940|\u0939\u093f\u0928\u094d\u0926\u0940", re.IGNORECASE)


def _extract_draft_id(message_obj):
    if not message_obj:
        return None
    text = message_obj.get("text", "")
    match = DRAFT_ID_PATTERN.search(text)
    return match.group(1) if match else None


def _is_authorized(chat_id):
    return str(chat_id) == str(TELEGRAM_CHAT_ID)


def handle_new_input(chat_id, message):
    if "document" in message:
        prompt = "\U0001f4c4 PDF mili. Yeh post kis type ka hai?"
    elif "photo" in message:
        prompt = "\U0001f5bc\ufe0f Photo mili. Yeh post kis type ka hai?"
    else:
        prompt = "\U0001f517 Link mila. Yeh post kis type ka hai?"

    send_message(
        chat_id, prompt,
        reply_markup=status_choice_keyboard(),
        reply_to_message_id=message["message_id"],
    )


def _get_source_text_and_title(original_message):
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

    url = original_message.get("text", "").strip()
    page_title = fetch_page_title(url)
    full_text = fetch_full_details_with_pdf(url)
    return full_text, (page_title or url)


def handle_status_chosen(chat_id, callback_query):
    status = callback_query["data"].replace("status:", "")
    prompt_message = callback_query["message"]
    original_message = prompt_message.get("reply_to_message")

    answer_callback_query(callback_query["id"], "\u23f3 Kaam shuru...")
    edit_message(chat_id, prompt_message["message_id"], f"\u23f3 Post ban raha hai ({status})...")

    if not original_message:
        edit_message(chat_id, prompt_message["message_id"], "\u274c Galti: asli message nahi mila, dobara try karein")
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
                         f"\u26a0\ufe0f Yeh post pehle se maujood hai (duplicate): {result['title']}")
            return

        draft_doc = get_draft_by_id(result["draftId"])
        summary = format_draft_summary(draft_doc)
        edit_message(chat_id, prompt_message["message_id"], summary)

    except Exception as e:
        edit_message(chat_id, prompt_message["message_id"], f"\u274c Galti aayi: {e}")


def handle_review_command(chat_id, message):
    draft_id = _extract_draft_id(message.get("reply_to_message"))
    if not draft_id:
        send_message(chat_id, "\u26a0\ufe0f Yeh message kisi draft-summary ka reply nahi lag raha - "
                              "kripya draft wale message ko hi reply karein.")
        return

    user_command = message.get("text", "").strip()
    draft_doc = get_draft_by_id(draft_id)
    if not draft_doc:
        send_message(chat_id, "\u274c Yeh draft ab nahi mil raha (shayad publish ho chuka hai)")
        return

    if re.search(r"\bpublish\b", user_command, re.IGNORECASE):
        try:
            published_id = publish_draft_now(draft_id)
            send_message(chat_id, f"\U0001f389 Publish ho gaya! ID: {published_id}",
                        reply_to_message_id=message["message_id"])
        except Exception as e:
            send_message(chat_id, f"\u274c Publish karte waqt galti: {e}",
                        reply_to_message_id=message["message_id"])
        return

    if _HINDI_CMD_RE.search(user_command):
        send_message(chat_id, "\u23f3 Hindi version bana raha hoon...", reply_to_message_id=message["message_id"])
        ok = add_hindi_to_draft(draft_id, force=True)
        send_message(chat_id, ("\u2705 Hindi version taiyaar ho gaya.\n\n" + format_draft_summary(get_draft_by_id(draft_id)))
                     if ok else "\u274c Hindi version nahi ban paaya. Wajah: " + (hindi_last_error() or "pata nahi") + ". Thodi der baad dobara likhein: hindi banao")
        return

    send_message(chat_id, "\u23f3 Samajh raha hoon...", reply_to_message_id=message["message_id"])

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
            send_message(chat_id, f"\U0001f914 {instructions.get('explanation', 'Samajh nahi aaya, phir se koshish karein')}")
            return

        if action == "publish":
            published_id = publish_draft_now(draft_id)
            send_message(chat_id, f"\U0001f389 Publish ho gaya! ID: {published_id}")
            return

        simple_fields = instructions.get("simple_fields") or {}
        simple_fields = {k: v for k, v in simple_fields.items() if v}
        if simple_fields:
            patch_sanity_fields(draft_id, simple_fields)

        if instructions.get("eligibilityDetails"):
            rebuild_eligibility_section(draft_id, instructions["eligibilityDetails"])
        if instructions.get("howToApply"):
            rebuild_how_to_apply_section(draft_id, instructions["howToApply"])
        if instructions.get("faqs"):
            rebuild_faq_section(draft_id, instructions["faqs"])

        updated_doc = get_draft_by_id(draft_id)
        summary = format_draft_summary(updated_doc)
        send_message(chat_id, f"\u2705 {instructions.get('explanation', 'Update ho gaya')}\n\n{summary}")

    except Exception as e:
        send_message(chat_id, f"\u274c Update karte waqt galti aayi: {e}")


def process_update(update):
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

    send_message(chat_id, "\U0001f44b Kisi notice ka link bhejein, PDF upload karein, ya screenshot bhejein.")


def _text_from_dashboard_input(input_type, content, files):
    """files: list of {"fileBase64", "fileMime", "fileName"} - ab EK SE
    ZYADA files (jaise 2-3 screenshots ek saath) bhi handle karta hai.
    Saari PDF ka text jod\u0924\u0947 hain, aur saari images ko EK HI vision-AI
    call mein ek saath bhej\u0924\u0947 hain (taaki AI poori jaankari ek jagah
    dekh kar sahi se combine kar sake)."""
    if input_type == "file" and files:
        pdf_texts = []
        image_b64_list = []
        names = []

        for f in files:
            file_b64 = f.get("fileBase64")
            file_mime = f.get("fileMime", "")
            file_name = f.get("fileName", "")
            if not file_b64:
                continue
            is_pdf = "pdf" in (file_mime or "").lower() or (file_name or "").lower().endswith(".pdf")
            if is_pdf:
                raw_bytes = base64.b64decode(file_b64)
                text, images_b64 = extract_pdf_text_or_images(raw_bytes)
                if text:
                    pdf_texts.append(text)
                elif images_b64:
                    image_b64_list.extend(images_b64)
                names.append(file_name or "Uploaded PDF")
            else:
                image_b64_list.append(file_b64)
                names.append(file_name or "Uploaded Screenshot")

        combined_text = "\n\n".join(pdf_texts)
        if image_b64_list:
            vision_text = call_vision_ai(
                "Yeh ek sarkari naukri notice ke ek ya kai pages/screenshots hain "
                "(agar ek se zyada hain to sabko ek saath padhkar poori jaankari "
                "milakar do). Inme jo bhi Hindi/English text likha hai, use jaisa "
                "hai waisa hi (poora, bina chhode) likh kar do.",
                image_b64_list,
            )
            combined_text = (combined_text + "\n\n" + vision_text).strip()

        title = ", ".join(names) if names else "Uploaded Files"
        return combined_text, title

    content = (content or "").strip()
    if content.startswith("http"):
        page_title = fetch_page_title(content)
        full_text = fetch_full_details_with_pdf(content)
        return full_text, (page_title or content)
    return content, "Dashboard Text Input"


_DASHBOARD_STATUS_MAP = {
    "job": "job",
    "admit card": "admit_card",
    "answer key": "answer_key",
    "result": "result",
    "final selection": "final_selection",
    "syllabus": "syllabus",
}


def _normalize_status(raw_status):
    """Dashboard ke dropdown se 'Admit Card' jaisi Capitalized label
    aati hai, par backend/AI ko 'admit_card' jaisa snake_case chahiye -
    yeh function sahi conversion karta hai. Isi galat mapping ki wajah
    se pehle sirf Job/Result hi sahi se kaam kar rahe the."""
    key = (raw_status or "job").strip().lower()
    return _DASHBOARD_STATUS_MAP.get(key, "job")


def _plain_summary(text):
    """Telegram ke liye bani HTML summary (<b>, <i>, <code>) ko Dashboard ke
    liye saaf text mein badalta hai - taaki screen par tag na dikhein."""
    t = re.sub(r"</?(b|i|u|code|pre|strong|em)>", "", str(text or ""))
    return t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def handle_dashboard_generate(body):
    status = _normalize_status(body.get("status"))
    input_type = body.get("inputType", "text")
    content = body.get("content", "")

    #  Naya format: "files" ek list hai (multi-upload support). Purane
    # single-file format (fileBase64/fileMime/fileName) ko bhi sambhaal
    # lete hain, taaki kisi purani caller se koi dikkat na ho.
    files = body.get("files") or []
    if not files and body.get("fileBase64"):
        files = [{
            "fileBase64": body.get("fileBase64"),
            "fileMime": body.get("fileMime", ""),
            "fileName": body.get("fileName", ""),
        }]

    #  Dashboard ke box mein agar DO link hon (pehla = jahan se post uthayi,
    # doosra = us post ka ASLI sarkari page), to doosra aadhikarik page maana
    # jaata hai - uske links sabse upar prathmikta paate hain.
    official_url_from_box = None
    if input_type == "link":
        urls_in_box = re.findall(r"https?://[^\s]+", content or "")
        if len(urls_in_box) >= 2:
            content = urls_in_box[0]
            official_url_from_box = urls_in_box[1]

    full_text, title = _text_from_dashboard_input(input_type, content, files)

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
    #  Optional: agar dashboard se "officialUrl" (us post ka asli sarkari page) aaye
    # to uske links ko sabse upar prathmikta milti hai
    official_url = (body.get("officialUrl") or "").strip() or official_url_from_box
    result = publish_scraped_post(raw_for_ai, source_link, status_hint=status, official_url=official_url)

    if result.get("duplicate"):
        return {"error": f"Yeh post pehle se maujood hai (duplicate): {result.get('title')}"}, 409

    draft_doc = get_draft_by_id(result["draftId"])
    summary = format_draft_summary(draft_doc)
    return {"draftId": result["draftId"], "draft": _plain_summary(summary)}, 200


def handle_dashboard_publish(body):
    """\U0001f195 SURAKSHA: Dashboard se KABHI seedha website par LIVE nahi
    karte - post Sanity mein hamesha DRAFT hi rehta hai. Isse aap
    khud Sanity Studio mein jaakar dekh-parakh kar "Publish" button
    dabayenge, tabhi woh website par jayega (bilkul shuru se yahi
    design tha)."""
    draft_id = body.get("draftId")
    if not draft_id:
        return {"error": "draftId zaroori hai"}, 400
    draft_doc = get_draft_by_id(draft_id)
    if not draft_doc:
        return {"error": "Yeh draft nahi mila (shayad already publish ho chuka hai)"}, 404
    return {"savedAsDraft": True, "draftId": draft_id}, 200


def handle_dashboard_list_posts(body):
    limit = int(body.get("limit", 15))
    from config import SANITY_PROJECT_ID, SANITY_DATASET, SANITY_API_TOKEN, SANITY_API_VERSION
    query = (
        '*[_type == "jobPost"] | order(_createdAt desc)[0...%d]'
        '{_id, title, status, _createdAt, "orgName": organization->name}' % limit
    )
    url = f"https://{SANITY_PROJECT_ID}.api.sanity.io/v{str(SANITY_API_VERSION).lstrip('v')}/data/query/{SANITY_DATASET}"
    resp = requests.get(
        url,
        params={"query": query},
        headers={"Authorization": f"Bearer {SANITY_API_TOKEN}"},
        timeout=15,
    )
    resp.raise_for_status()
    posts = resp.json().get("result", [])
    return {"posts": posts}, 200


def handle_dashboard_edit(body):
    """Dashboard se aaya hua sudhaar/edit command - bilkul Telegram
    reply-command jaisa hi kaam karta hai (interpret_command +
    patch/rebuild), bas UI Dashboard hai.

    \U0001f195 Ab command ke saath screenshot(s) bhi bhej sakte hain (jaise
    "yeh date galat hai, is screenshot se sahi kar do") - vision AI se
    screenshot ka text nikaal kar command samajhne wale AI ko diya
    jaata hai, taaki sahi jaankari (jaise sahi tareekh) wahan se mil
    sake."""
    draft_id = body.get("draftId")
    user_command = (body.get("command") or "").strip()
    files = body.get("files") or []

    if not draft_id or (not user_command and not files):
        return {"error": "draftId aur command/screenshot mein se kam se kam ek zaroori hai"}, 400

    draft_doc = get_draft_by_id(draft_id)
    if not draft_doc:
        return {"error": "Yeh draft ab nahi mil raha (shayad publish ho chuka hai)"}, 404

    #  Dashboard se post KABHI live nahi hoti - "publish" likhne par bhi nahi.
    # Live karne ke liye sirf Sanity Studio mein haath se Publish dabana hai.
    if user_command and re.search(r"\bpublish\b", user_command, re.IGNORECASE):
        return {
            "draftId": draft_id,
            "draft": _plain_summary(format_draft_summary(draft_doc)),
            "explanation": "Dashboard se Publish nahi hota - draft Sanity mein surakshit hai. Live karne ke liye Sanity Studio kholkar wahan Publish dabayein.",
        }, 200

    # Hindi version: "hindi banao" / "hindi version" / Devanagari equivalents. Rebuilds the
    # Hindi (/hi/) version from the current English post.
    if user_command and _HINDI_CMD_RE.search(user_command):
        ok = add_hindi_to_draft(draft_id, force=True)
        updated_doc = get_draft_by_id(draft_id)
        return {
            "draftId": draft_id,
            "draft": _plain_summary(format_draft_summary(updated_doc)),
            "explanation": ("Hindi version taiyaar ho gaya (Sanity mein 'Hindi Version' khane mein hai)." if ok else
                            "Hindi version nahi ban paaya. Wajah: " + (hindi_last_error() or "pata nahi") + ". 1-2 minute baad dobara \"hindi banao\" likhein."),
        }, 200

    source_link = draft_doc.get("sourceUrl", "")
    source_text = fetch_full_details_with_pdf(source_link) if source_link.startswith("http") else ""

    if files:
        image_b64_list = [f.get("fileBase64") for f in files if f.get("fileBase64")]
        if image_b64_list:
            try:
                vision_text = call_vision_ai(
                    "Yeh ek sarkari naukri notice se related sudhaar/correction ka "
                    "screenshot hai. Ismein jo bhi Hindi/English text likha hai "
                    "(khaaskar tareekhein, sankhya, naam), use jaisa hai waisa hi "
                    "poora likh kar do.",
                    image_b64_list,
                )
                source_text = (
                    source_text + "\n\n[Screenshot se nikaali gayi jaankari:]\n" + vision_text
                ).strip()
            except Exception as e:
                print(f"    [EDIT] Screenshot padhne mein galti: {e}")

    if not user_command:
        user_command = "upar diye gaye screenshot ke hisaab se galat ya chhuti hui jaankari sahi/update kar do"

    org_ref = draft_doc.get("organization")
    org_name = org_ref.get("name") if isinstance(org_ref, dict) else ""

    instructions = interpret_command(
        user_command, source_text,
        draft_doc.get("title"), draft_doc.get("status"), org_name,
    )

    action = instructions.get("action", "unclear")
    if action == "unclear":
        return {"error": instructions.get("explanation", "Samajh nahi aaya, phir se koshish karein")}, 200

    #  FIX: Dashboard se AI khud-ba-khud "publish" kabhi NAHI karega -
    # chahe interpret_command khud action="publish" bhi bataye. Publish
    # SIRF tabhi hoga jab user ne apne command mein khud saaf-saaf
    # "publish" shabd likha ho (upar wali check mein already ho chuka
    # hota agar aisa hota). Yahan hum sirf field-updates apply karte
    # hain, taaki screenshot se sudhaar karte waqt galti se site par
    # live na ho jaaye.
    simple_fields = instructions.get("simple_fields") or {}
    simple_fields = {k: v for k, v in simple_fields.items() if v}
    if simple_fields:
        patch_sanity_fields(draft_id, simple_fields)

    if instructions.get("eligibilityDetails"):
        rebuild_eligibility_section(draft_id, instructions["eligibilityDetails"])
    if instructions.get("howToApply"):
        rebuild_how_to_apply_section(draft_id, instructions["howToApply"])
    if instructions.get("faqs"):
        rebuild_faq_section(draft_id, instructions["faqs"])

    updated_doc = get_draft_by_id(draft_id)
    summary = format_draft_summary(updated_doc)
    return {
        "draftId": draft_id,
        "draft": _plain_summary(summary),
        "explanation": instructions.get("explanation", "Update ho gaya"),
    }, 200


def handle_dashboard_request(body):
    action = body.get("action")
    try:
        if action == "generate":
            return handle_dashboard_generate(body)
        if action == "publish":
            return handle_dashboard_publish(body)
        if action == "list_posts":
            return handle_dashboard_list_posts(body)
        if action == "edit":
            return handle_dashboard_edit(body)
        return {"error": "unknown action"}, 400
    except Exception as e:
        return {"error": str(e)}, 500


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        #  Har request ke shuru mein ghadi chalu: AI ko Vercel ke 280 second ke
        # andar hi khatam karna hai (235 second tak AI, baaki Sanity/jawab ke liye)
        start_request_clock(235)
        try:
            self._do_post_inner()
        finally:
            clear_request_clock()

    def _do_post_inner(self):
        length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(length)

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

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Telegram webhook is running.")
