# main.py
# Yeh poore tool ka "dil" hai - isi file ko Railway per chalaya jaayega

import time
import schedule

from config import SOURCES, CHECK_INTERVAL_MINUTES, CLEANUP_AFTER_DAYS
from database import (
    init_db, is_new_post, save_post,
    is_source_seeded, mark_source_seeded, cleanup_old_posts,
)
from scraper import fetch_new_posts, detect_category, extract_vacancy
from telegram_bot import send_alert


def process_source(source):
    """
    Ek source (department) ko check karta hai.

    Agar yeh department PEHLI BAAR check ho raha hai, to jitni bhi entries
    abhi mil rahi hain, unhe sirf database mein "yaad" rakh liya jaata hai -
    Telegram par alert NAHI bheja jaata (kyunki yeh sab purani/pehle-se-mojood
    jankari hai, nayi nahi). Agli baar se jo bhi SACH MEIN nayi entry aayegi,
    sirf usi ka alert aayega.
    """
    department = source["department"]
    posts = fetch_new_posts(source)

    first_time = not is_source_seeded(department)

    for post in posts:
        if is_new_post(post["link"], post["title"]):
            category = detect_category(post["title"])
            vacancy = extract_vacancy(post["title"])

            save_post(
                department=post["department"],
                title=post["title"],
                link=post["link"],
                category=category,
                vacancy=vacancy,
            )

            if first_time:
                # Pehli baar - sirf yaad rakho, alert mat bhejo
                continue

            send_alert(
                department=post["department"],
                title=post["title"],
                category=category,
                vacancy=vacancy,
                link=post["link"],
                source_site=source["url"],
            )
            print(f"     [NEW ALERT] {post['title']}")

    if first_time:
        mark_source_seeded(department)
        print(f"     [SEEDED] {department} - {len(posts)} purani entries yaad rakh li gayin, alert nahi bheja")


def check_all_sources():
    """Sabhi sources ko ek-ek karke check karta hai"""
    print(f"\n[{time.strftime('%d-%m-%Y %H:%M:%S')}] Check shuru ho raha hai...")

    for source in SOURCES:
        print(f"  -> {source['department']} check ho raha hai...")
        process_source(source)

    cleanup_old_posts(days=CLEANUP_AFTER_DAYS)
    print("Check poora hua.\n")


if __name__ == "__main__":
    init_db()
    print("Sarkari Alert Bot shuru ho gaya hai...")

    check_all_sources()

    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_all_sources)

    while True:
        schedule.run_pending()
        time.sleep(30)
