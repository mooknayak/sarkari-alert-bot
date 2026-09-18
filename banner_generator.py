# banner_generator.py
#
# 🎨 AB HAR STATUS KA APNA ALAG DESIGN HAI - sirf badge ka rang nahi,
# poora background/motif/layout badal jaata hai. Isse Sanity Studio ki
# list mein banner ki chhoti tasveer (thumbnail) dekhte hi pata chal
# jaata hai ki yeh Job hai, Admit Card hai, Result hai, ya kya hai -
# bina post khole hue.
#
# Post ke title/organization/vacancy/status ke hisaab se ek professional
# banner image (1200x675px, jaisa Google News/Discover ke liye
# recommend hota hai) khud bana deti hai - Python ki Pillow library se,
# seedha server par, bina kisi browser/AI-image-model ke.
#
# ⚠️ ZAROORI: Is file ko kaam karne ke liye EK Hindi (Devanagari) font
# file chahiye - "fonts/NotoSansDevanagari-Bold.ttf" is repository mein
# honi chahiye. Agar font file na mile, to banner nahi banega (lekin
# post phir bhi ban jaayega - sanity_publisher.py mein yeh already
# try/except mein hai, isliye bot kabhi crash nahi hota).
#
# FONT KAISE DOWNLOAD KAREIN (ek baar ka kaam):
#   1) fonts.google.com/noto/specimen/Noto+Sans+Devanagari kholein
#   2) "Download family" dabayein (zip file milegi)
#   3) Us zip ke andar se "NotoSansDevanagari-Bold.ttf" file nikaal lein
#   4) Apni GitHub repository mein "fonts" naam ka naya folder banayein
#   5) Us folder ke andar yeh font file upload/commit kar dein
#      (poora path: fonts/NotoSansDevanagari-Bold.ttf)

import os
import math
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1200, 675

FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "NotoSansDevanagari-Bold.ttf")

WHITE = (255, 255, 255)
SAFFRON = (232, 114, 12)

# ============================================================================
# HAR STATUS KA APNA ALAG "THEME" - background color, badge color, motif
# aur stat-box ka default label - isse har type ka banner turant pehchana
# ja sake, sirf thumbnail dekh kar bhi.
# ============================================================================
THEMES = {
    "job": {
        "label": "Job Notification",
        "bg_deep": (11, 29, 56), "bg_light": (18, 42, 78),
        "badge": (15, 123, 77), "accent": (255, 217, 160),
        "motif": "vacancy_box", "stat_label": "कुल पद",
    },
    "admit_card": {
        "label": "Admit Card",
        "bg_deep": (46, 32, 10), "bg_light": (79, 55, 16),
        "badge": (199, 146, 10), "accent": (255, 224, 130),
        "motif": "ticket", "stat_label": "प्रवेश पत्र",
    },
    "answer_key": {
        "label": "Answer Key",
        "bg_deep": (8, 26, 56), "bg_light": (14, 50, 104),
        "badge": (31, 99, 196), "accent": (150, 200, 255),
        "motif": "checklist", "stat_label": "उत्तर कुंजी",
    },
    "result": {
        "label": "Result",
        "bg_deep": (46, 10, 14), "bg_light": (82, 22, 28),
        "badge": (192, 57, 43), "accent": (255, 190, 170),
        "motif": "star", "stat_label": "परिणाम",
    },
    "final_selection": {
        "label": "Final Selection",
        "bg_deep": (12, 12, 16), "bg_light": (32, 32, 38),
        "badge": (168, 133, 38), "accent": (230, 200, 110),
        "motif": "gold_frame", "stat_label": "अंतिम सूची",
    },
}

MUTED = (180, 190, 210)
FOOTER = (150, 158, 178)


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


def _draw_gradient_bg(img, deep, light):
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(deep[0] + (light[0] - deep[0]) * ratio)
        g = int(deep[1] + (light[1] - deep[1]) * ratio)
        b = int(deep[2] + (light[2] - deep[2]) * ratio)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))
    return draw


def _draw_tricolor_strip(draw):
    """Sabhi banners mein common - brand consistency ke liye."""
    strip_h = 10
    third = WIDTH // 3
    draw.rectangle([0, 0, third, strip_h], fill=SAFFRON)
    draw.rectangle([third, 0, 2 * third, strip_h], fill=WHITE)
    draw.rectangle([2 * third, 0, WIDTH, strip_h], fill=(15, 123, 77))


def _draw_star(draw, cx, cy, r_outer, r_inner, color):
    """5-point star draw karta hai - Result banner ke motif ke liye."""
    points = []
    for i in range(10):
        angle = math.pi / 5 * i - math.pi / 2
        r = r_outer if i % 2 == 0 else r_inner
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(points, fill=color)


# ============================================================================
# HAR STATUS KE LIYE ALAG MOTIF (background decoration) - taaki thumbnail
# mein hi farak dikhe. Sab RGB-safe hain (koi alpha/transparency nahi
# istemal karte, taaki koi rendering error kabhi na aaye)
# ============================================================================

def _motif_ticket(draw, bg_light):
    """Admit Card - daayi taraf ek 'ticket stub' jaisi dashed-perforation
    line, jaise asli admit card/ticket mein kaata hua hissa hota hai."""
    x = WIDTH - 90
    hole_color = tuple(min(255, c + 28) for c in bg_light)
    y = 40
    while y < HEIGHT - 40:
        draw.ellipse([x - 7, y - 7, x + 7, y + 7], outline=hole_color, width=2)
        y += 34


def _motif_checklist(draw, bg_light):
    """Answer Key - upar-daayi taraf halke checkmark ticks ka pattern."""
    tick_color = tuple(min(255, c + 30) for c in bg_light)
    start_x, start_y = WIDTH - 260, 40
    for row in range(3):
        for col in range(3):
            cx = start_x + col * 40
            cy = start_y + row * 40
            draw.line([(cx - 8, cy), (cx - 2, cy + 8), (cx + 10, cy - 10)],
                      fill=tick_color, width=3, joint="curve")


def _motif_gold_frame(draw, accent_color):
    """Final Selection - poore banner ke chaaron taraf ek elegant gold
    double-border, taaki 'premium/final' feel aaye."""
    margin = 18
    draw.rectangle([margin, margin, WIDTH - margin, HEIGHT - margin], outline=accent_color, width=2)
    margin2 = margin + 6
    draw.rectangle([margin2, margin2, WIDTH - margin2, HEIGHT - margin2], outline=accent_color, width=1)


def generate_banner(title, organization, vacancy, status):
    """Poora banner banata hai aur PNG bytes return karta hai. Status ke
    hisaab se poora alag theme (color + motif + stat-box) istemal hota
    hai, taaki har post-type turant pehchana ja sake."""
    theme = THEMES.get(status, THEMES["job"])

    img = Image.new("RGB", (WIDTH, HEIGHT), theme["bg_light"])
    draw = _draw_gradient_bg(img, theme["bg_deep"], theme["bg_light"])
    _draw_tricolor_strip(draw)

    motif = theme["motif"]
    if motif == "ticket":
        _motif_ticket(draw, theme["bg_light"])
    elif motif == "checklist":
        _motif_checklist(draw, theme["bg_light"])
    elif motif == "star":
        star_color = tuple(min(255, c + 22) for c in theme["bg_light"])
        _draw_star(draw, WIDTH - 140, 150, 95, 42, star_color)
    elif motif == "gold_frame":
        _motif_gold_frame(draw, theme["accent"])

    # Status badge (pill)
    badge_font = _font(28)
    badge_text = theme["label"]
    text_w = draw.textlength(badge_text, font=badge_font)
    badge_w = int(text_w) + 60
    badge_h = 56
    badge_x, badge_y = 60, 60
    _rounded_rect(draw, [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], radius=28, fill=theme["badge"])
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

    # Stat box (bottom-left) - status ke hisaab se alag jaankari dikhati hai
    box_y = HEIGHT - 140
    box_color = tuple(min(255, c + 20) for c in theme["bg_light"])
    show_vacancy = bool(vacancy) and status == "job"
    stat_value = str(vacancy) if show_vacancy else theme["stat_label"]
    stat_sub = theme["stat_label"] if show_vacancy else "जारी"
    box_width = 320 if show_vacancy else 260
    _rounded_rect(draw, [60, box_y, 60 + box_width, box_y + 84], radius=14, fill=box_color)
    value_font = _font(34 if len(stat_value) <= 12 else 24)
    label_font = _font(18)
    draw.text((84, box_y + 14), stat_value, font=value_font, fill=theme["accent"])
    draw.text((84, box_y + 58), stat_sub, font=label_font, fill=MUTED)

    # Footer brand - website ke header jaisa hi "OSP" gol logo badge +
    # wordmark, taaki banner par bhi wahi branding dikhe jo asli website
    # ke header mein hai (safed circle + navy border + "OSP" letters)
    logo_cx, logo_cy, logo_r = WIDTH - 300, HEIGHT - 32, 20
    draw.ellipse(
        [logo_cx - logo_r, logo_cy - logo_r, logo_cx + logo_r, logo_cy + logo_r],
        fill=WHITE, outline=(200, 210, 225), width=2,
    )
    osp_font = _font(16)
    draw.text((logo_cx, logo_cy), "OSP", font=osp_font, fill=theme["bg_deep"], anchor="mm")

    footer_font = _font(20)
    draw.text((logo_cx + logo_r + 14, HEIGHT - 42), "Official Sarkari Patrika", font=footer_font, fill=FOOTER)

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
