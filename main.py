# main.py
# Yeh poore tool ka "dil" hai - isi file ko Railway per chalaya jaayega

import time
import schedule

from config import SOURCES, CHECK_INTERVAL_MINUTES
from database import init_db, is_new_post, save_post
from scraper import fetch_new_posts, detect_category, extract_vacancy
from telegram_bot import send_alert


def check_all_sources():
    """Sabhi sources ko ek-ek karke check karta hai aur naye post mile to alert bhejta hai"""
    print(f"\n[{time.strftime('%d-%m-%Y %H:%M:%S')}] Check shuru ho raha hai...")

    for source in SOURCES:
        print(f"  -> {source['department']} check ho raha hai...")
        posts = fetch_new_posts(source)

        for post in posts:
            if is_new_post(post["link"]):
                category = detect_category(post["title"])
                vacancy = extract_vacancy(post["title"])

                # Database mein save karo taaki dobara na bheje
                save_post(
                    department=post["department"],
                    title=post["title"],
                    link=post["link"],
                    category=category,
                    vacancy=vacancy,
                )

                # Telegram par alert bhejo
                send_alert(
                    department=post["department"],
                    title=post["title"],
                    category=category,
                    vacancy=vacancy,
                    link=post["link"],
                )
                print(f"     [NEW] {post['title']}")

    print("Check poora hua.\n")


if __name__ == "__main__":
    init_db()
    print("Sarkari Alert Bot shuru ho gaya hai...")

    # Shuru mein ek baar turant check kar lo
    check_all_sources()

    # Fir har CHECK_INTERVAL_MINUTES mein dobara check karta rahe
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_all_sources)

    while True:
        schedule.run_pending()
        time.sleep(30)
