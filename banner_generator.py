# banner_generator.py
#
# 🎨 v3 - Ab user ke diye HUE reference banner jaisa design: diagonal
# rangeen gradient, "OSP VERIFIED" badge, gold-border wala black
# highlight box (jisme asli title chamakta hai), sparkle decorations,
# aur neeche website ka safed pill. Har status (Job/Admit Card/Answer
# Key/Result/Final Selection) ka apna alag color-theme hai, taaki
# Sanity Studio ki list mein thumbnail dekhte hi pehchaana ja sake.
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

import os
import math
import random
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1200, 675

FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "NotoSansDevanagari-Bold.ttf")

WHITE = (255, 255, 255)

# ============================================================================
# HAR STATUS KA APNA ALAG "THEME" - gradient (3 stop, diagonal), badge/accent
# color, aur label - isse har type ka banner turant pehchana ja sake.
# ============================================================================
THEMES = {
    "job": {
        "label": "Job Notification",
        "gradient": [(10, 30, 85), (30, 70, 130), (15, 95, 75)],
        "accent": (46, 204, 113), "gold": (255, 209, 102),
    },
    "admit_card": {
        "label": "Admit Card",
        "gradient": [(55, 35, 10), (120, 75, 15), (90, 40, 10)],
        "accent": (230, 165, 30), "gold": (255, 224, 130),
    },
    "answer_key": {
        "label": "Answer Key",
        "gradient": [(10, 20, 65), (35, 65, 150), (70, 35, 130)],
        "accent": (66, 133, 244), "gold": (170, 210, 255),
    },
    "result": {
        "label": "Result",
        "gradient": [(60, 10, 20), (110, 20, 65), (150, 20, 40)],
        "accent": (231, 76, 60), "gold": (255, 205, 150),
    },
    "final_selection": {
        "label": "Final Selection",
        "gradient": [(15, 12, 10), (55, 42, 12), (20, 16, 8)],
        "accent": (201, 162, 39), "gold": (240, 210, 130),
    },
}

MUTED = (225, 230, 245)
DOMAIN_TEXT = (120, 30, 30)


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


def _rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _diagonal_gradient(colors):
    """3-stop diagonal gradient (upar-baayen se neeche-daayen) - tez
    banane ke liye pehle ek CHHOTI image par banate hain, phir usse
    poore size tak smoothly 'stretch' kar dete hain (bahut tez, kyunki
    per-pixel Python loop sirf ~2000 baar chalta hai, 810000 baar nahi)."""
    small_w, small_h = 60, 34
    small = Image.new("RGB", (small_w, small_h))
    px = small.load()
    n = len(colors) - 1
    for y in range(small_h):
        for x in range(small_w):
            t = (x / (small_w - 1) + y / (small_h - 1)) / 2
            t = min(max(t, 0), 1)
            seg = min(int(t * n), n - 1)
            local_t = (t * n) - seg
            c0, c1 = colors[seg], colors[seg + 1]
            r = int(c0[0] + (c1[0] - c0[0]) * local_t)
            g = int(c0[1] + (c1[1] - c0[1]) * local_t)
            b = int(c0[2] + (c1[2] - c0[2]) * local_t)
            px[x, y] = (r, g, b)
    return small.resize((WIDTH, HEIGHT), Image.BILINEAR)


def _draw_sparkle(draw, cx, cy, size, color):
    """4-point sparkle (✦) - halka decorative touch, reference banner
    jaisa."""
    pts = [
        (cx, cy - size), (cx + size * 0.28, cy - size * 0.28),
        (cx + size, cy), (cx + size * 0.28, cy + size * 0.28),
        (cx, cy + size), (cx - size * 0.28, cy + size * 0.28),
        (cx - size, cy), (cx - size * 0.28, cy - size * 0.28),
    ]
    draw.polygon(pts, fill=color)


def _draw_decorations(img, draw, accent):
    """Dotted texture + halke bokeh circles + sparkles - reference
    banner jaisa 'lively' background, bina text padhne mein dikkat kiye
    (sab halke/dark corners mein hi rakhte hain)."""
    rng = random.Random(42)  # fixed seed - har baar wahi consistent pattern

    # Dotted texture (bottom-left corner mein)
    dot_color = tuple(min(255, c + 40) for c in accent)
    for i in range(60):
        x = rng.randint(20, 320)
        y = rng.randint(HEIGHT - 160, HEIGHT - 20)
        r = rng.choice([1, 1, 2])
        draw.ellipse([x - r, y - r, x + r, y + r], fill=dot_color)

    # Soft bokeh circles (halka, alag jagah) - image par seedha paste
    # karte hain (low-opacity mask ke saath), taaki halka 'glow' dikhe
    bokeh_color = tuple(min(255, c + 25) for c in accent)
    for cx, cy, r in [(WIDTH - 80, 60, 70), (WIDTH - 220, HEIGHT - 100, 50)]:
        overlay = Image.new("RGB", (r * 2, r * 2), bokeh_color)
        mask = Image.new("L", (r * 2, r * 2), 0)
        mdraw = ImageDraw.Draw(mask)
        mdraw.ellipse([0, 0, r * 2, r * 2], fill=28)  # low opacity
        img.paste(overlay, (cx - r, cy - r), mask)

    # Sparkles (chhote taare)
    for cx, cy, size in [(WIDTH - 60, HEIGHT - 60, 10), (WIDTH - 140, HEIGHT - 40, 6)]:
        _draw_sparkle(draw, cx, cy, size, WHITE)


def generate_banner(title, organization, vacancy, status):
    """Poora banner banata hai aur PNG bytes return karta hai - reference
    design (diagonal gradient + OSP badge + gold highlight box + sparkle)
    ke hisaab se, status ke color-theme ke saath."""
    theme = THEMES.get(status, THEMES["job"])

    img = _diagonal_gradient(theme["gradient"])
    draw = ImageDraw.Draw(img)

    _draw_decorations(img, draw, theme["accent"])

    # "OSP VERIFIED" circular badge (top-left)
    badge_cx, badge_cy, badge_r = 68, 68, 40
    draw.ellipse(
        [badge_cx - badge_r, badge_cy - badge_r, badge_cx + badge_r, badge_cy + badge_r],
        fill=WHITE, outline=theme["accent"], width=4,
    )
    osp_font = _font(24)
    verified_font = _font(11)
    draw.text((badge_cx, badge_cy - 8), "OSP", font=osp_font, fill=(20, 30, 60), anchor="mm")
    draw.text((badge_cx, badge_cy + 16), "VERIFIED", font=verified_font, fill=theme["accent"], anchor="mm")

    # Top headline (organization + status label) - badge ke saath ek line mein
    headline_font = _font(34)
    org_text = (organization or "सरकारी विभाग")[:45]
    headline = f"{org_text} {theme['label']}"
    hx = badge_cx + badge_r + 20
    draw.text((hx, badge_cy), headline, font=headline_font, fill=WHITE, anchor="lm")

    # Vacancy chip (agar mile) - headline ke neeche chhota badge
    y_cursor = badge_cy + badge_r + 30
    if vacancy and status == "job":
        vac_font = _font(22)
        vac_text = f"{vacancy} पद"
        vw = draw.textlength(vac_text, font=vac_font)
        _rounded_rect(draw, [62, y_cursor, 62 + vw + 36, y_cursor + 42], radius=21, fill=theme["accent"])
        draw.text((62 + 18, y_cursor + 21), vac_text, font=vac_font, fill=WHITE, anchor="lm")
        y_cursor += 60

    # ========== GOLD-BORDER BLACK HIGHLIGHT BOX (asli title) ==========
    box_x1, box_x2 = 62, WIDTH - 62
    title_font_size = 46 if len(title) <= 45 else 36
    title_font = _font(title_font_size)
    max_text_width = (box_x2 - box_x1) - 60
    lines = _wrap_text(draw, title or "पोस्ट का शीर्षक", title_font, max_text_width)[:3]
    line_height = int(title_font_size * 1.3)
    box_h = len(lines) * line_height + 50
    box_y1 = y_cursor + 20
    box_y2 = box_y1 + box_h

    _rounded_rect(draw, [box_x1, box_y1, box_x2, box_y2], radius=14, fill=(10, 10, 12))
    draw.rounded_rectangle([box_x1, box_y1, box_x2, box_y2], radius=14, outline=theme["gold"], width=3)

    ty = box_y1 + 25
    for line in lines:
        draw.text((box_x1 + 30, ty), line, font=title_font, fill=theme["gold"])
        ty += line_height

    # ========== BOTTOM: website domain white pill ==========
    domain_font = _font(26)
    domain_text = "officialsarkaripatrika.com"
    dw = draw.textlength(domain_text, font=domain_font)
    pill_y = box_y2 + 30
    if pill_y + 60 < HEIGHT:
        _rounded_rect(draw, [62, pill_y, 62 + dw + 50, pill_y + 52], radius=26, fill=WHITE)
        draw.text((62 + 25, pill_y + 26), domain_text, font=domain_font, fill=DOMAIN_TEXT, anchor="lm")

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
