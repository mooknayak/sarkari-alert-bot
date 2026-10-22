# draft_summary.py
# ðŸ†• NAYI FILE
#
# Sanity draft document ko ek saaf-suthre Telegram message mein badalta
# hai - taaki user poora review kar sake. Message ke sabse neeche Draft
# ID chhipi hoti hai (HTML comment jaisa nahi, seedha chhota text) -
# jab user is message ko REPLY karega, hum usi se pehchan lenge kaunsa
# draft update karna hai.

import html

STATUS_LABELS = {
    "job": "ðŸŸ¢ Job Notification",
    "admit_card": "ðŸŸ¡ Admit Card",
    "answer_key": "ðŸ”µ Answer Key",
    "result": "ðŸ”´ Result",
    "final_selection": "âš« Final Selection",
    "syllabus": "ðŸ“˜ Syllabus",
}


def _field_status(value):
    """Field bhari hai ya khaali - chhota visual indicator."""
    if value and str(value).strip() and str(value).strip() != "à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤‰à¤ªà¤²à¤¬à¥à¤§ à¤¨à¤¹à¥€à¤‚ à¤¹à¥ˆ":
        return "âœ…"
    return "â¬œ"


def _summary_block(summary):
    """Quick Summary ka ASLI text dikhata hai taaki aap padhkar hi approve karein."""
    text = str(summary or "").strip()
    if not text:
        return ["â¬œ Quick Summary (à¤¸à¤‚à¤•à¥à¤·à¤¿à¤ªà¥à¤¤ à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€): à¤–à¤¾à¤²à¥€ â€” \"quick summary daal do\" likh kar bharwayein"]
    return ["âœ… Quick Summary (à¤¸à¤‚à¤•à¥à¤·à¤¿à¤ªà¥à¤¤ à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€):", f"<i>{html.escape(text)}</i>"]


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

    all_sections = list(sections_before) + list(sections_after)

    def _has(*keywords):
        return any(any(k in (s.get("heading") or "") for k in keywords) for s in all_sections)

    has_eligibility = _has("à¤ªà¤¾à¤¤à¥à¤°à¤¤à¤¾", "Eligibility")
    # status ke hisaab se heading alag hoti hai (à¤†à¤µà¥‡à¤¦à¤¨ à¤•à¥ˆà¤¸à¥‡ / à¤ªà¤°à¤¿à¤£à¤¾à¤® à¤•à¥ˆà¤¸à¥‡ à¤¦à¥‡à¤–à¥‡à¤‚ / ...)
    has_how_to_apply = _has("à¤•à¥ˆà¤¸à¥‡", "How to")
    has_faq = _has("à¤…à¤•à¥à¤¸à¤°", "FAQ")

    lines = [
        f"ðŸ“‹ <b>{title}</b>",
        f"{status_label}",
        "",
        *_summary_block(draft_doc.get("shortSummary")),
        "",
        f"{_field_status(vacancy)} à¤•à¥à¤² à¤ªà¤¦: {vacancy or 'à¤œà¤¾à¤¨à¤•à¤¾à¤°à¥€ à¤¨à¤¹à¥€à¤‚'}",
        f"{_field_status(dates.get('applicationStart') or dates.get('applicationStartNote'))} Application Start",
        f"{_field_status(dates.get('applicationEnd') or dates.get('applicationEndNote'))} Application Last Date",
        f"{_field_status(fee.get('general'))} Application Fee",
        f"{'âœ…' if has_eligibility else 'â¬œ'} Eligibility Criteria",
        f"{'âœ…' if has_how_to_apply else 'â¬œ'} How to Apply",
        f"{'âœ…' if has_faq else 'â¬œ'} FAQ",
        f"{_field_status(len(links) > 0)} Important Links ({len(links)})",
    ]

    # ðŸ†• Aadhikarik link na mila to saaf chetavani (private site ka link ab
    # kabhi apne-aap nahi bharta - khaali rehta hai, haath se bharna hoga)
    primary_by_status = {
        "job": "Apply Online", "admit_card": "Download Admit Card",
        "answer_key": "Check Result", "result": "Check Result",
        "final_selection": "Check Result", "syllabus": "Official Notification",
    }
    org_ref = (draft_doc.get("organization") or {}).get("_ref")
    if org_ref == "org-other-departments":
        lines.append("âš ï¸ Organization: 'Other Departments' à¤²à¤—à¤¾ à¤¹à¥ˆ â€” Sanity Studio à¤®à¥‡à¤‚ à¤¸à¤¹à¥€ à¤µà¤¿à¤­à¤¾à¤— à¤šà¥à¤¨à¥‡à¤‚")
    present_types = {l.get("linkType") for l in links}
    needed = [primary_by_status.get(status, "Apply Online"), "Official Notification"]
    missing = [t for t in dict.fromkeys(needed) if t not in present_types]
    if missing:
        lines.append(f"âš ï¸ à¤†à¤§à¤¿à¤•à¤¾à¤°à¤¿à¤• à¤²à¤¿à¤‚à¤• à¤¨à¤¹à¥€à¤‚ à¤®à¤¿à¤²à¤¾: {', '.join(missing)} â€” Sanity Studio à¤®à¥‡à¤‚ à¤¹à¤¾à¤¥ à¤¸à¥‡ à¤œà¥‹à¤¡à¤¼à¥‡à¤‚")

    lines += [
        "",
        "âœï¸ à¤‡à¤¸ message à¤•à¥‹ <b>Reply</b> à¤•à¤°à¤•à¥‡ à¤¬à¤¤à¤¾à¤‡à¤ à¤•à¥à¤¯à¤¾ à¤ à¥€à¤• à¤•à¤°à¤¨à¤¾ à¤¹à¥ˆ",
        "(à¤œà¥ˆà¤¸à¥‡: \"eligibility daal do\", \"important date bhi daal do\")",
        "",
        "âœ… à¤œà¤¬ à¤¸à¤¬ à¤ à¥€à¤• à¤²à¤—à¥‡: à¤‡à¤¸à¥€ message à¤•à¥‹ Reply à¤•à¤°à¤•à¥‡ à¤²à¤¿à¤–à¥‡à¤‚ <b>publish à¤•à¤° do</b>",
        "",
        f"<code>Draft ID: {doc_id}</code>",
    ]
    return "\n".join(lines)
