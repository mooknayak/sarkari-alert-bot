# database.py
# Yahan hum track karte hain ki kaun sa post pehle bhej chuke hain,
# kaun sa department pehli baar check ho raha hai, round-robin group index,
# aur ab yeh bhi ki kaunsa source baar-baar fail ho raha hai (cooldown).

import sqlite3
import hashlib
import re
import threading
from config import DATABASE_FILE

# Jab ek saath kai websites check hoti hain (parallel), sabhi ek hi
# database mein likhna chahte hain - yeh "lock" ek waqt mein sirf ek
# hi likhawat hone deta hai, taaki "database is locked" jaisi error na aaye
DB_LOCK = threading.Lock()


def get_connection():
    """Database se connection banata hai - WAL mode aur timeout ke saath
    taaki parallel (ek saath kai jagah se) access mein bhi dikkat na ho"""
    conn = sqlite3.connect(DATABASE_FILE, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

# Yeh generic/promotional shabd title se hata diye jaate hain duplicate-check
# se pehle - taaki "Answer Key Out" aur "Answer Key Released" jaise
# mamooli farak wale titles ek hi post pehchane jaayein
NOISE_WORDS = [
    "out", "released", "declared", "check", "now", "download", "new",
    "latest", "here", "details", "notice", "update", "updated", "click",
    "जारी", "देखें", "अभी", "नया", "डाउनलोड", "सूचना",
]


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            title_hash TEXT,
            core_words TEXT,
            department TEXT,
            title TEXT,
            link TEXT,
            category TEXT,
            vacancy TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seeded_sources (
            department TEXT PRIMARY KEY,
            seeded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    # Naya table: kaunsa source kitni baar lagataar (consecutive) fail
    # hua hai - taaki baar-baar block hone waali site (jaise SSC/UPSC)
    # ko kuch samay ke liye chhod diya jaaye, waqt bachaane ke liye
    conn.execute("""
        CREATE TABLE IF NOT EXISTS source_failures (
            department TEXT PRIMARY KEY,
            fail_count INTEGER DEFAULT 0,
            last_failed_at TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def make_post_id(link):
    return hashlib.md5(link.encode()).hexdigest()


def normalize_title(title):
    cleaned = re.sub(r'[^a-z0-9\u0900-\u097F ]', '', title.lower())
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def get_core_words(title):
    """
    Title se mamooli/promotional shabd hata kar sirf "core" (asli
    pehchaan wale) shabd nikalta hai - jaise vibhag ka naam, exam ka
    naam, post ka naam. Isse "Answer Key Out" aur "Answer Key
    Released" dono ke core words lagbhag same ban jaate hain.
    """
    normalized = normalize_title(title)
    words = [w for w in normalized.split() if w not in NOISE_WORDS and len(w) > 2]
    return " ".join(sorted(words))


def make_title_hash(title):
    return hashlib.md5(normalize_title(title).encode()).hexdigest()


def word_overlap_ratio(words_a, words_b):
    """Do word-sets kitne milte-julte hain, 0 se 1 ke beech mein batata hai"""
    set_a, set_b = set(words_a.split()), set(words_b.split())
    if not set_a or not set_b:
        return 0
    intersection = set_a & set_b
    smaller = min(len(set_a), len(set_b))
    return len(intersection) / smaller if smaller else 0


def is_new_post(link, title):
    """
    Check karta hai ki yeh post pehle bhej chuke hain ya nahi. Ab 3
    tarah se check hota hai:
      1) Same link pehle aaya ho
      2) Same title-hash pehle aaya ho
      3) Core-words (noise-words hataye hue) 80% se zyada milte-julte
         hon usi department ke kisi purane post se - taaki "Answer Key
         Out" vs "Answer Key Released" jaisa farak duplicate na bane
    """
    post_id = make_post_id(link)
    title_hash = make_title_hash(title)
    core = get_core_words(title)

    conn = get_connection()
    cursor = conn.execute(
        "SELECT 1 FROM posts WHERE id = ? OR title_hash = ?",
        (post_id, title_hash)
    )
    if cursor.fetchone():
        conn.close()
        return False

    # Fuzzy check - pichle kuch dinon ke isi jaise core-words wale posts dekho
    cursor = conn.execute(
        "SELECT core_words FROM posts WHERE core_words IS NOT NULL "
        "ORDER BY sent_at DESC LIMIT 200"
    )
    rows = cursor.fetchall()
    conn.close()

    for (existing_core,) in rows:
        if existing_core and word_overlap_ratio(core, existing_core) >= 0.8:
            return False

    return True


def save_post(department, title, link, category, vacancy):
    post_id = make_post_id(link)
    title_hash = make_title_hash(title)
    core = get_core_words(title)
    with DB_LOCK:
        conn = get_connection()
        conn.execute("""
            INSERT OR IGNORE INTO posts (id, title_hash, core_words, department, title, link, category, vacancy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (post_id, title_hash, core, department, title, link, category, vacancy))
        conn.commit()
        conn.close()


def is_source_seeded(department):
    conn = get_connection()
    cursor = conn.execute(
        "SELECT 1 FROM seeded_sources WHERE department = ?", (department,)
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None


def mark_source_seeded(department):
    with DB_LOCK:
        conn = get_connection()
        conn.execute(
            "INSERT OR IGNORE INTO seeded_sources (department) VALUES (?)", (department,)
        )
        conn.commit()
        conn.close()


def cleanup_old_posts(days=60):
    conn = get_connection()
    conn.execute(
        "DELETE FROM posts WHERE sent_at < datetime('now', ?)",
        (f'-{days} days',)
    )
    conn.commit()
    conn.close()


def get_current_group_index():
    conn = get_connection()
    cursor = conn.execute("SELECT value FROM bot_state WHERE key = 'group_index'")
    result = cursor.fetchone()
    conn.close()
    return int(result[0]) if result else 0


def set_current_group_index(index):
    conn = get_connection()
    conn.execute(
        "INSERT INTO bot_state (key, value) VALUES ('group_index', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(index),)
    )
    conn.commit()
    conn.close()


def get_fail_count(department):
    conn = get_connection()
    cursor = conn.execute(
        "SELECT fail_count FROM source_failures WHERE department = ?", (department,)
    )
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0


def record_source_failure(department):
    """Jab koi source fail ho, uska fail-count 1 badha deta hai"""
    with DB_LOCK:
        conn = get_connection()
        conn.execute("""
            INSERT INTO source_failures (department, fail_count, last_failed_at)
            VALUES (?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(department) DO UPDATE SET
                fail_count = fail_count + 1,
                last_failed_at = CURRENT_TIMESTAMP
        """, (department,))
        conn.commit()
        conn.close()


def record_source_success(department):
    """Jab koi source safal ho, uska fail-count wapas 0 kar deta hai"""
    with DB_LOCK:
        conn = get_connection()
        conn.execute(
            "DELETE FROM source_failures WHERE department = ?", (department,)
        )
        conn.commit()
        conn.close()


def is_source_in_cooldown(department, threshold=5, cooldown_hours=6):
    """
    Agar koi source lagataar 'threshold' baar (default 5) fail ho chuka hai,
    aur pichhli koshish 'cooldown_hours' (default 6 ghante) se kam samay
    pehle hui thi, to use abhi ke liye chhod dete hain (waqt bachaane ke
    liye) - kyunki baar-baar koshish karna waise bhi bekaar hai agar
    site IP-block kar chuki hai.
    """
    conn = get_connection()
    cursor = conn.execute(
        "SELECT fail_count, last_failed_at FROM source_failures WHERE department = ?",
        (department,)
    )
    result = cursor.fetchone()
    conn.close()

    if not result or result[0] < threshold:
        return False

    cursor_conn = get_connection()
    check = cursor_conn.execute(
        "SELECT 1 FROM source_failures WHERE department = ? "
        "AND last_failed_at > datetime('now', ?)",
        (department, f'-{cooldown_hours} hours')
    ).fetchone()
    cursor_conn.close()
    return check is not None
