# database.py
# Yahan hum track karte hain ki kaun sa post pehle bhej chuke hain (duplicate rokne ke liye)

import sqlite3
import hashlib
from config import DATABASE_FILE


def init_db():
    """Database aur table banata hai (agar pehle se nahi hai)"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            department TEXT,
            title TEXT,
            link TEXT,
            category TEXT,
            vacancy TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def make_post_id(link):
    """Har link ka ek unique ID banata hai, taaki duplicate pehchana ja sake"""
    return hashlib.md5(link.encode()).hexdigest()


def is_new_post(link):
    """Check karta hai ki yeh post pehle bhej chuke hain ya nahi"""
    post_id = make_post_id(link)
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.execute("SELECT 1 FROM posts WHERE id = ?", (post_id,))
    result = cursor.fetchone()
    conn.close()
    return result is None


def save_post(department, title, link, category, vacancy):
    """Naya post database mein save karta hai, taaki dobara na bheje"""
    post_id = make_post_id(link)
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute("""
        INSERT OR IGNORE INTO posts (id, department, title, link, category, vacancy)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (post_id, department, title, link, category, vacancy))
    conn.commit()
    conn.close()
