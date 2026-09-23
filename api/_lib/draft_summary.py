# draft_summary.py
# 🆕 NAYI FILE
#
# Sanity draft document ko ek saaf-suthre Telegram message mein badalta
# hai - taaki user poora review kar sake. Message ke sabse neeche Draft
# ID chhipi hoti hai (HTML comment jaisa nahi, seedha chhota text) -
# jab user is message ko REPLY karega, hum usi se pehchan lenge kaunsa
# draft update karna hai.

STATUS_LABELS = {
    "job": "🟢 Job Notification",
    "admit_card": "🟡 Admit Card",
    "answer_key": "🔵 Answer Key",
    "result": "🔴 Result",
    "final_selection": "⚫ Final Selection",
}


def _field_status(value):
    """Field bhari hai ya khaali - chhota visual indicator."""
    if value and str(value).strip() and str(value).strip() != "जानकारी उपलब्ध नहीं है":
        return "✅"
    return "⬜"


def format_draft_summary(draft_doc):
    """Poora draft document leta hai, ek readable Telegram summary
    (HTML formatting ke saath) banata hai."""
    title = draft_doc.get("title", "(khaali)")
    status = draft_doc.get("status", "job")
    status_label = STATUS_LABELS.get(status, status)
    slug = (draft_doc.get("slug") or {}).get("current", "")
    doc_id = draft_doc.get("_id", "")

    vacancy_details = draft_doc.get("vacancyDetails") or []
    vacancy = vacancy_details[0].get("totalPosts") if vacancy_details else None

    dates = draft_doc.get("importantDates") or {}
    fee = draft_doc.get("applicationFee") or {}
    sections_before = draft_doc.get("customSectionsBeforeLinks") or []
    sections_after = draft_doc.get("customSectionsAfterLinks") or []
    links = draft_doc.get("importantLinks") or []

    has_eligibility = any(s.get("heading", "").startswith("पात्रता") for s in sections_before)
    has_how_to_apply = any(s.get("heading", "").startswith("आवेदन कैसे") for s in sections_before)
    has_faq = any(s.get("heading", "").startswith("अक्सर") for s in sections_after)

    lines = [
        f"📋 <b>{title}</b>",
        f"{status_label}",
        "",
        f"{_field_status(vacancy)} कुल पद: {vacancy or 'जानकारी नहीं'}",
        f"{_field_status(dates.get('applicationStart') or dates.get('applicationStartNote'))} Application Start",
        f"{_field_status(dates.get('applicationEnd') or dates.get('applicationEndNote'))} Application Last Date",
        f"{_field_status(fee.get('general'))} Application Fee",
        f"{'✅' if has_eligibility else '⬜'} Eligibility Criteria",
        f"{'✅' if has_how_to_apply else '⬜'} How to Apply",
        f"{'✅' if has_faq else '⬜'} FAQ",
        f"{_field_status(len(links) > 0)} Important Links ({len(links)})",
        "",
        "✏️ इस message को <b>Reply</b> करके बताइए क्या ठीक करना है",
        "(जैसे: \"eligibility daal do\", \"important date bhi daal do\")",
        "",
        "✅ जब सब ठीक लगे: इसी message को Reply करके लिखें <b>publish कर do</b>",
        "",
        f"<code>Draft ID: {doc_id}</code>",
    ]
    return "\n".join(lines)
