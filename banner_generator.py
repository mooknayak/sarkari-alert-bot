# banner_generator.py
# 🆕 NAYI FILE
#
# Yeh file post ke title/organization/vacancy/status ke hisaab se ek
# professional banner image (1200x675px, jaisa Google News/Discover ke
# liye recommend hota hai) khud bana deti hai - Python ki Pillow library
# se, seedha server par, bina kisi browser/AI-image-model ke.
#
# ⚠️ ZAROORI: Is file ko kaam karne ke liye EK Hindi (Devanagari) font
# file chahiye - "fonts/NotoSansDevanagari-Bold.ttf" is repository mein
# honi chahiye. Agar font file na mile, to banner nahi banega (lekin
# post phir bhi ban jaayega - sanity_publisher.py mein yeh already
# try/except mein hai).
#
# FONT KAISE DOWNLOAD KAREIN (ek baar ka kaam):
#   1) fonts.google.com/noto/specimen/Noto+Sans+Devanagari kholein
#   2) "Download family" dabayein (zip file milegi)
#   3) Us zip ke andar se "NotoSansDevanagari-Bold.ttf" file nikaal lein
#   4) Apni GitHub repository mein "fonts" naam ka naya folder banayein
#   5) Us folder ke andar yeh font file upload/commit kar dein
#      (poora path: fonts/NotoSansDevanagari-Bold.ttf)

import os
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1200, 675

FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "NotoSansDevanagari-Bold.ttf")

# website ke jobPost schema jaisi hi status colors (consistency ke liye)
STATUS_META = {
    "job": {"color": (15, 123, 77), "label": "Job Notification"},
    "admit_card": {"color": (199, 146, 10), "label": "Admit Card"},
    "answer_key": {"color": (31, 99, 196), "label": "Answer Key"},
    "result": {"color": (192, 57, 43), "label": "Result"},
    "final_selection": {"color": (44, 52, 68), "label": "Final Selection"},
}

NAVY_DEEP = (11, 29, 56)
NAVY = (18, 42, 78)
SAFFRON = (232, 114, 12)
WHITE = (255, 255, 255)
MUTED = (159, 179, 209)
FOOTER = (124, 139, 168)


def _font(size):
    """Font load karta hai - file na mile to seedha Exception uthata hai,
    taaki calling code ko pata chale banner nahi ban paayega (chup-chaap
    galat/tuta hua banner nahi banega)."""
    if not os.path.exists(FONT_PATH):
        raise Exception(
            f"Font file nahi mili: {FONT_PATH} - repository mein "
            f"'fonts/NotoSansDevanagari-Bold.ttf' add karein"
        )
    return ImageFont.truetype(FONT_PATH, size)


def _wrap_text(draw, text, font, max_width):
    """Lambi line ko kai chhoti lines mein todता hai taaki banner ke
    andar sahi se fit ho jaaye."""
    words = text.split(" ")
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        if draw.textlength(test, font=font) <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _rounded_rect(draw, xy, radius, fill):
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


def generate_banner(title, organization, vacancy, status):
    """Poora banner banata hai aur PNG bytes return karta hai."""
    meta = STATUS_META.get(status, STATUS_META["job"])

    img = Image.new("RGB", (WIDTH, HEIGHT), NAVY)
    draw = ImageDraw.Draw(img)

    # Halka vertical gradient (upar se neeche halka sa color badlaav)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(NAVY_DEEP[0] + (NAVY[0] - NAVY_DEEP[0]) * ratio)
        g = int(NAVY_DEEP[1] + (NAVY[1] - NAVY_DEEP[1]) * ratio)
        b = int(NAVY_DEEP[2] + (NAVY[2] - NAVY_DEEP[2]) * ratio)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

    # Top tricolor strip (Bharosemand/desi touch, koi official emblem nahi)
    strip_h = 10
    third = WIDTH // 3
    draw.rectangle([0, 0, third, strip_h], fill=SAFFRON)
    draw.rectangle([third, 0, 2 * third, strip_h], fill=WHITE)
    draw.rectangle([2 * third, 0, WIDTH, strip_h], fill=(15, 123, 77))

    # Status badge (pill)
    badge_font = _font(28)
    badge_text = meta["label"]
    text_w = draw.textlength(badge_text, font=badge_font)
    badge_w = int(text_w) + 60
    badge_h = 56
    badge_x, badge_y = 60, 60
    _rounded_rect(draw, [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], radius=28, fill=meta["color"])
    draw.text((badge_x + 30, badge_y + badge_h // 2), badge_text, font=badge_font, fill=WHITE, anchor="lm")

    # Organization
    org_font = _font(32)
    org_text = (organization or "सरकारी विभाग")[:60]
    draw.text((62, 170), org_text, font=org_font, fill=MUTED)

    # Title (auto-wrap + auto-shrink)
    title = title or "पोस्ट का शीर्षक"
    title_size = 50 if len(title) <= 55 else 40
    title_font = _font(title_size)
    max_title_width = 780
    lines = _wrap_text(draw, title, title_font, max_title_width)[:4]
    y = 235
    line_height = int(title_size * 1.25)
    for line in lines:
        draw.text((62, y), line, font=title_font, fill=WHITE)
        y += line_height

    # Vacancy stat box (bottom-left) - halka lighter-navy solid box (koi
    # complex alpha-blending nahi, taaki simple aur bug-free rahे)
    if vacancy:
        box_y = HEIGHT - 140
        box_color = (32, 56, 94)  # NAVY se thoda halka
        _rounded_rect(draw, [60, box_y, 320, box_y + 84], radius=14, fill=box_color)
        vac_font = _font(38)
        label_font = _font(18)
        draw.text((84, box_y + 14), str(vacancy), font=vac_font, fill=(255, 217, 160))
        draw.text((84, box_y + 58), "कुल पद", font=label_font, fill=MUTED)

    # 🆕 Footer brand - website ke header jaisa hi "OSP" gol logo badge +
    # wordmark, taaki banner par bhi wahi branding dikhe jo asli website
    # ke header mein hai (safed circle + navy border + "OSP" letters)
    logo_cx, logo_cy, logo_r = WIDTH - 300, HEIGHT - 32, 20
    draw.ellipse(
        [logo_cx - logo_r, logo_cy - logo_r, logo_cx + logo_r, logo_cy + logo_r],
        fill=WHITE, outline=(200, 210, 225), width=2,
    )
    osp_font = _font(16)
    draw.text((logo_cx, logo_cy), "OSP", font=osp_font, fill=NAVY_DEEP, anchor="mm")

    footer_font = _font(20)
    draw.text((logo_cx + logo_r + 14, HEIGHT - 42), "Official Sarkari Patrika", font=footer_font, fill=FOOTER)

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
