# main.py
# Yeh poore tool ka "dil" hai - isi file ko Railway per chalaya jaayega
#
# NAYA TAREEKA: Har check-cycle mein SAARE 136 sources check nahi hote -
# sirf EK group (jaise "Uttar Pradesh" ya "Bihar") ki baari aati hai.
# Har baar agla group check hota hai, aur sab group ho jaane ke baad
# phir pehle se shuru ho jaata hai. Isse load hamesha kam rehta hai.
#
# FILTER: Sirf Notification, Admit Card, Result, Answer Key - inhi 4
# category ki jaankari Telegram par jaati hai. Baaki sab (jaise "Apply
# Online" links ya kisi aur tarah ki general jaankari) chhod di jaati hai.

import time
import schedule

from config import (
    SOURCE_GROUPS, GROUP_NAMES, ALLOWED_CATEGORIES,
    CHECK_INTERVAL_MINUTES, CLEANUP_AFTER_DAYS,
)
from database import (
    init_db, is_new_post, save_post,
    is_source_seeded, mark_source_seeded, cleanup_old_posts,
    get_current_group_index, set_current_group_index,
)
from scraper import fetch_new_posts, detect_category, extract_vacancy
from telegram_bot import send_alert


def process_source(source):
    """Ek source (department) ko check karta hai aur naye/kaam-ke posts ka alert bhejta hai"""
    department = source["department"]
    posts = fetch_new_posts(source)

    first_time = not is_source_seeded(department)

    for post in posts:
        if is_new_post(post["link"], post["title"]):
            category = detect_category(post["title"])
            vacancy = extract_vacancy(post["title"])

            # Database mein hamesha save karo (chahe alert bheje ya na bheje) -
            # taaki yeh dobara "naya" na dikhe aur baar-baar process na ho
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

            if category not in ALLOWED_CATEGORIES:
                # Sirf Notification/Admit Card/Result/Answer Key allowed hai -
                # baaki (jaise Apply Online, General Update) chhod do
                print(f"     [SKIPPED - not relevant] {post['title']} ({category})")
                continue

            send_alert(
                department=post["department"],
                title=post["title"],
                category=category,
                vacancy=vacancy,
                link=post["link"],
                source_site=source["url"],
            )
            print(f"     [NEW ALERT] {post['title']} ({category})")

    if first_time:
        mark_source_seeded(department)
        print(f"     [SEEDED] {department} - {len(posts)} purani entries yaad rakh li gayin, alert nahi bheja")


def check_next_group():
    """
    Round-robin ka dil - har baar sirf EK group check karta hai,
    fir agli baari ke liye index aage badha deta hai.
    """
    index = get_current_group_index()
    group_name = GROUP_NAMES[index % len(GROUP_NAMES)]
    sources = SOURCE_GROUPS[group_name]

    print(f"\n[{time.strftime('%d-%m-%Y %H:%M:%S')}] Group check ho raha hai: {group_name} "
          f"({len(sources)} sources)")

    for source in sources:
        print(f"  -> {source['department']} check ho raha hai...")
        process_source(source)

    # Agli baari ke liye agle group per index badha do
    set_current_group_index(index + 1)

    # Har kuch cycles ke baad purani entries saaf kar do
    if index % len(GROUP_NAMES) == 0:
        cleanup_old_posts(days=CLEANUP_AFTER_DAYS)

    print(f"Group '{group_name}' ka check poora hua.\n")


if __name__ == "__main__":
    init_db()
    print("Sarkari Alert Bot shuru ho gaya hai...")
    print(f"Total {len(GROUP_NAMES)} groups hain, har {CHECK_INTERVAL_MINUTES} minute mein 1 group check hoga.")

    check_next_group()

    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_next_group)

    while True:
        schedule.run_pending()
        time.sleep(30)
