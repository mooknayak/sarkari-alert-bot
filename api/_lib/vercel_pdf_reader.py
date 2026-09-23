# vercel_pdf_reader.py
# 🆕 NAYI FILE - sirf Vercel wale interactive bot ke liye
#
# GitHub Actions wala bot 'pypdf' + 'pytesseract' + 'poppler' istemal
# karta hai - lekin Vercel ke Python function mein system-level tools
# (tesseract, poppler) install NAHI ho sakte (Vercel isko allow nahi
# karta). Isliye yahan 'PyMuPDF' (fitz) istemal karte hain - yeh ek
# self-contained library hai (koi bhi bahar ka software nahi chahiye),
# aur yeh 2 kaam kar sakti hai:
#   1) Digital (typed) PDF se seedha text nikaalna
#   2) Scanned/photo PDF ka page ek TASVEER (image) mein badalna - jise
#      phir hum seedha ek "vision" AI model ko dikha kar padhwa lete hain
#      (OCR ki jagah, aur yeh zyada behtar bhi hai kyunki AI context bhi
#      samajhta hai, sirf akshar nahi)

import io
import base64

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

MAX_PDF_PAGES = 15
MIN_TEXT_LENGTH_BEFORE_VISION = 200


def extract_pdf_text_or_images(pdf_bytes):
    """
    PDF se pehle seedha text nikaalne ki koshish karta hai (tez, sasta).
    Agar bahut kam text mile (matlab scanned/photo PDF hai), to pehle
    kuch pages ki TASVEEREIN (base64 PNG) bana kar deta hai - taaki
    unhe vision-AI ko dikhaya ja sake.

    Return: (text: str, page_images_base64: list[str])
    - Agar digital text mil gaya: (text, [])
    - Agar scanned nikla: ("", [img1_base64, img2_base64, ...])
    - Kuch bhi galat ho: ("", []) - kabhi crash nahi karta
    """
    if fitz is None:
        print("[CHETAVANI] PyMuPDF (fitz) install nahi hai")
        return "", []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        print(f"[ERROR] PDF kholte waqt dikkat: {e}")
        return "", []

    text_parts = []
    for page_num in range(min(len(doc), MAX_PDF_PAGES)):
        try:
            text_parts.append(doc[page_num].get_text())
        except Exception:
            continue

    full_text = "\n".join(text_parts).strip()

    if len(full_text) >= MIN_TEXT_LENGTH_BEFORE_VISION:
        doc.close()
        return full_text, []

    # Kam text mila - shayad scanned PDF hai. Pehle 5 page ki tasveerein
    # banate hain (vision-AI ko dikhane ke liye) - zyada page bhejna
    # mehenga/dhima hota hai, isliye seemित rakhte hain
    print("    [PDF] Bahut kam text mila - scanned lag raha hai, tasveerein bana rahe hain...")
    images_b64 = []
    try:
        for page_num in range(min(len(doc), 5)):
            page = doc[page_num]
            pix = page.get_pixmap(dpi=150)  # 150 dpi kaafi hota hai padhne ke liye
            img_bytes = pix.tobytes("png")
            images_b64.append(base64.b64encode(img_bytes).decode("ascii"))
    except Exception as e:
        print(f"[ERROR] PDF ko tasveer mein badalte waqt dikkat: {e}")
    finally:
        doc.close()

    return "", images_b64


def photo_bytes_to_base64(photo_bytes):
    """User ne jo photo/screenshot bheji hai, use vision-AI ko dene ke
    liye base64 mein badalta hai."""
    return base64.b64encode(photo_bytes).decode("ascii")
