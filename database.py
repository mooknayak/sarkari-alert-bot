# database.py
# Yahan hum track karte hain ki kaun sa post pehle bhej chuke hain (duplicate rokne ke liye),
# kaun sa department pehli baar check ho raha hai (purani jankari na bheje isliye),
# aur ab yeh bhi ki round-robin mein ABHI KAUN SA group ki baari hai.

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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seeded_sources (
            department TEXT PRIMARY KEY,
            seeded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Yeh table sirf 1 row rakhta hai - round-robin mein abhi kaunse
    # group ki baari hai, uska index yaad rakhta hai
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_state (
            key TEXT PRIMARY KEY,
            value TEXT
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


def make_title_hash(title):
    return hashlib.md5(normalize_title(title).encode()).hexdigest()


def is_new_post(link, title):
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
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.execute(
        "SELECT 1 FROM seeded_sources WHERE department = ?", (department,)
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None


def mark_source_seeded(department):
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute(
        "INSERT OR IGNORE INTO seeded_sources (department) VALUES (?)", (department,)
    )
    conn.commit()
    conn.close()


def cleanup_old_posts(days=60):
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute(
        "DELETE FROM posts WHERE sent_at < datetime('now', ?)",
        (f'-{days} days',)
    )
    conn.commit()
    conn.close()


def get_current_group_index():
    """Round-robin mein abhi kaunse group ki baari hai, wo number laata hai (0 se shuru)"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.execute("SELECT value FROM bot_state WHERE key = 'group_index'")
    result = cursor.fetchone()
    conn.close()
    return int(result[0]) if result else 0


def set_current_group_index(index):
    """Agli baari ke liye group index save karta hai"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute(
        "INSERT INTO bot_state (key, value) VALUES ('group_index', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(index),)
    )
    conn.commit()
    conn.close()
