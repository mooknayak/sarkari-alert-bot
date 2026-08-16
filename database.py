# database.py
# Yahan hum track karte hain ki kaun sa post pehle bhej chuke hain (duplicate rokne ke liye)
# aur kaun sa department pehli baar check ho raha hai (purani jankari na bheje isliye)

import sqlite3
import hashlib
import re
from config import DATABASE_FILE


def init_db():
    """Database aur tables banata hai (agar pehle se nahi hain)"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            title_hash TEXT,
            department TEXT,
            title TEXT,
            link TEXT,
            category TEXT,
            vacancy TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Yeh table yaad rakhta hai ki kaun se department (source) pehli baar
    # check ho chuke hain - taaki purani jankari sirf "seed" ho, alert na ho
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seeded_sources (
            department TEXT PRIMARY KEY,
            seeded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def make_post_id(link):
    """Har link ka ek unique ID banata hai, taaki duplicate pehchana ja sake"""
    return hashlib.md5(link.encode()).hexdigest()


def normalize_title(title):
    """
    Title ko saaf karta hai (chhote-bade letters, extra spaces, punctuation
    hata kar) taaki agar 2 alag websites/RSS ek hi notification ko thoda
    alag naam se dikhayein, tab bhi hum use "same" pehchan sakein aur
    dobara alert na bhejein.
    """
    cleaned = re.sub(r'[^a-z0-9\u0900-\u097F ]', '', title.lower())
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def make_title_hash(title):
    return hashlib.md5(normalize_title(title).encode()).hexdigest()


def is_new_post(link, title):
    """
    Check karta hai ki yeh post pehle bhej chuke hain ya nahi.
    2 tarah se check hota hai:
      1) Same link pehle aaya ho
      2) Same (ya milta-julta) title kisi doosre source se pehle aa chuka ho
         (isse ek hi notification ka baar-baar alag sources se alert nahi aata)
    """
    post_id = make_post_id(link)
    title_hash = make_title_hash(title)

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.execute(
        "SELECT 1 FROM posts WHERE id = ? OR title_hash = ?",
        (post_id, title_hash)
    )
    result = cursor.fetchone()
    conn.close()
    return result is None


def save_post(department, title, link, category, vacancy):
    """Naya post database mein save karta hai, taaki dobara na bheje"""
    post_id = make_post_id(link)
    title_hash = make_title_hash(title)
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute("""
        INSERT OR IGNORE INTO posts (id, title_hash, department, title, link, category, vacancy)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (post_id, title_hash, department, title, link, category, vacancy))
    conn.commit()
    conn.close()


def is_source_seeded(department):
    """Check karta hai ki is department ko pehle kabhi check kiya gaya hai ya nahi"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.execute(
        "SELECT 1 FROM seeded_sources WHERE department = ?", (department,)
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None


def mark_source_seeded(department):
    """Department ko 'pehli baar check ho gaya' mark kar deta hai"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute(
        "INSERT OR IGNORE INTO seeded_sources (department) VALUES (?)", (department,)
    )
    conn.commit()
    conn.close()


def cleanup_old_posts(days=60):
    """
    Purani entries (jitne din se koi kaam ki nahi rahi) database se hata deta hai,
    taaki database file zyada bhaari na ho. Naye/duplicate-check per asar nahi padta
    kyunki itne purane post ab website per bhi shayad na dikhein.
    """
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute(
        "DELETE FROM posts WHERE sent_at < datetime('now', ?)",
        (f'-{days} days',)
    )
    conn.commit()
    conn.close()
