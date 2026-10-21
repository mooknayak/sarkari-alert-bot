# command_interpreter.py
# 🆕 NAYI FILE
#
# User Telegram par jo natural-language command likhta hai (jaise
# "ismein eligibility daal do" ya "important date bhi daal do notification
# se") - yeh file use samajh kar batata hai ki KAUNSA field, KYA value
# se update karna hai. Isi se poora "Human-in-the-Loop" review-and-fix
# system chalta hai.

import re
import json

from sanity_publisher import _call_ai, VALID_STATUSES

COMMAND_PROMPT_TEMPLATE = """Tum ek Sanity CMS ke liye smart editing-assistant ho. User ne Hindi/Hinglish mein ek command diya hai ki draft post mein kya badlaav/jaankari jodni hai. Tumhara kaam hai: (1) user ka command samajhna, (2) neeche diye gaye ASLI NOTICE TEXT mein se sahi jaankari dhoondhna, (3) sahi field mein sahi value bharna.

USER KA COMMAND: "{user_command}"

ASLI NOTICE TEXT (jahan se sach ki jaankari nikaalni hai):
\"\"\"
{source_text}
\"\"\"

ABHI KE POST KI KUCH JAANKARI (context ke liye):
Title: {current_title}
Status: {current_status}
Organization: {current_organization}

SAKHT NIYAM:
- Sirf ASLI NOTICE TEXT mein se jaankari lo. Khud se kuch mat banao.
- Agar user ne "publish kar do" / "publish" jaisa kaha hai, to "action":"publish" do, "updates" khaali rakho.
- Agar command bilkul samajh na aaye ya notice text mein woh jaankari na mile, "action":"unclear" do aur "explanation" mein bata do kya dikkat hai.
- Warna "action":"update" do.

Sirf neeche JSON format mein jawab do - koi extra text nahi:
{{
  "action": "update" ya "publish" ya "unclear",
  "explanation": "1 chhoti line Hindi mein - user ko dikhegi ki kya kiya/kyun nahi ho paaya",
  "simple_fields": {{
    "title": "agar title badalna hai",
    "vacancy": "sirf number",
    "jobLocation": "...",
    "salaryText": "...",
    "salaryMin": "sirf number",
    "salaryMax": "sirf number",
    "applicationFee.general": "...",
    "applicationFee.scst": "...",
    "applicationFee.paymentMode": "...",
    "importantDates.applicationStart": "YYYY-MM-DD",
    "importantDates.applicationEnd": "YYYY-MM-DD",
    "importantDates.admitCardDate": "YYYY-MM-DD",
    "importantDates.examDate": "YYYY-MM-DD",
    "importantDates.resultDate": "YYYY-MM-DD"
  }},
  "eligibilityDetails": "agar eligibility/patrata update karni hai to poora text yahan, warna is key ko chhod do",
  "howToApply": "agar how-to-apply update karna hai to poora text yahan, warna is key ko chhod do",
  "faqs": [{{"question": "...", "answer": "..."}}]
}}

Sirf woh keys do jo command se related hain - baaki chhod do (khaali object bhi mat bhejo agar zaroorat nahi)."""


def interpret_command(user_command, source_text, current_title, current_status, current_organization):
    """User ke command ko AI se samjhwa kar structured update-instructions
    (dict) mein badalta hai."""
    prompt = COMMAND_PROMPT_TEMPLATE.format(
        user_command=user_command,
        source_text=(source_text or "")[:8000],
        current_title=current_title or "",
        current_status=current_status or "",
        current_organization=current_organization or "",
    )
    raw_response = _call_ai(prompt, max_tokens=1500)

    cleaned = raw_response.strip()
    cleaned = re.sub(r"^```json", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^```", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        return {
            "action": "unclear",
            "explanation": f"AI ka jawab samajh nahi aaya, dobara try karein ({e})",
            "simple_fields": {},
        }
