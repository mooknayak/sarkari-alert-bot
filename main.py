# main.py
# Yeh poore tool ka "dil" hai - isi file ko Railway per chalaya jaayega
#
# SURAKSHA: Har ek source (website) apne alag try/except ke andar chalta
# hai. Agar kisi ek website mein KOI BHI dikkat aaye (site down ho,
# format badal gaya ho, ya koi aur anjaan error), to sirf USI ek
# website ka check chhoot jaayega - baaki saari websites aur poora
# bot bilkul normal chalte rahenge. Kabhi bhi poora bot band nahi hoga.

import time
import traceback
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
from scraper import fetch_new_posts, detect_category, extract_vacancy, find_apply_link
from telegram_bot import send_alert


def process_source(source):
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
                continue

            if category not in ALLOWED_CATEGORIES:
                print(f"     [SKIPPED - not relevant] {post['title']} ({category})")
                continue

            apply_link = find_apply_link(post["link"])

            send_alert(
                department=post["department"],
                title=post["title"],
                category=category,
                vacancy=vacancy,
                link=post["link"],
                source_site=source["url"],
                apply_link=apply_link,
            )
            print(f"     [NEW ALERT] {post['title']} ({category})"
                  f" - Apply link {'mila' if apply_link else 'nahi mila, notice link diya'}")

    if first_time:
        mark_source_seeded(department)
        print(f"     [SEEDED] {department} - {len(posts)} purani entries yaad rakh li gayin, alert nahi bheja")


def check_next_group():
    index = get_current_group_index()
    group_name = GROUP_NAMES[index % len(GROUP_NAMES)]
    sources = SOURCE_GROUPS[group_name]

    print(f"\n[{time.strftime('%d-%m-%Y %H:%M:%S')}] Group check ho raha hai: {group_name} "
          f"({len(sources)} sources)")

    for source in sources:
        # SURAKSHA: har website apne alag try/except mein - ek toote to
        # baaki sab (aur poora bot) chalta rahega
        try:
            print(f"  -> {source['department']} check ho raha hai...")
            process_source(source)
        except Exception as e:
            print(f"  [SKIP - GALTI AAYI] {source['department']} mein dikkat aayi, "
                  f"isse chhod kar aage badh rahe hain: {e}")
            traceback.print_exc()
            continue

    # Yeh 2 kaam bhi apne alag try/except mein - inmein dikkat aaye
    # to bhi agli baari ka check rukna nahi chahiye
    try:
        set_current_group_index(index + 1)
    except Exception as e:
        print(f"  [ERROR] Group index save karne mein dikkat: {e}")

    try:
        if index % len(GROUP_NAMES) == 0:
            cleanup_old_posts(days=CLEANUP_AFTER_DAYS)
    except Exception as e:
        print(f"  [ERROR] Purani entries saaf karne mein dikkat: {e}")

    print(f"Group '{group_name}' ka check poora hua.\n")


if __name__ == "__main__":
    init_db()
    print("Sarkari Alert Bot shuru ho gaya hai...")
    print(f"Total {len(GROUP_NAMES)} groups hain, har {CHECK_INTERVAL_MINUTES} minute mein 1 group check hoga.")

    check_next_group()

    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_next_group)

    while True:
        # SURAKSHA: sabse bahar bhi ek suraksha-jaal - agar kabhi kisi
        # anjaan wajah se schedule chalane mein hi dikkat aa jaaye, to
        # bhi poora bot band nahi hoga, sirf error print karke chalta rahega
        try:
            schedule.run_pending()
        except Exception as e:
            print(f"[ERROR] Kuch anjaan dikkat aayi, lekin bot chalta rahega: {e}")
            traceback.print_exc()
        time.sleep(30)
