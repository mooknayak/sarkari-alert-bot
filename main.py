# main.py
# Yeh poore tool ka "dil" hai - isi file ko Railway per chalaya jaayega
#
# SURAKSHA: Har ek source (website) apne alag try/except ke andar chalta
# hai. Agar kisi ek website mein KOI BHI dikkat aaye, sirf USI ek
# website ka check chhoot jaayega - baaki saari websites aur poora
# bot bilkul normal chalte rahenge.
#
# TEZI: Pehle har cycle mein sirf 1 group check hota tha (poora
# rotation ~4.5 ghante mein hota tha). Ab GROUPS_PER_CYCLE (config.py
# mein set) jitne groups EK HI CYCLE mein check ho jaate hain - isse
# poora rotation bahut jaldi (~1 ghanta) poora ho jaata hai, bina
# kisi extra server/platform ke.

import time
import traceback
import schedule

from config import (
    SOURCE_GROUPS, GROUP_NAMES, ALLOWED_CATEGORIES,
    CHECK_INTERVAL_MINUTES, CLEANUP_AFTER_DAYS, GROUPS_PER_CYCLE,
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


def check_one_group(group_name):
    sources = SOURCE_GROUPS[group_name]
    print(f"\n[{time.strftime('%d-%m-%Y %H:%M:%S')}] Group check ho raha hai: {group_name} "
          f"({len(sources)} sources)")

    for source in sources:
        try:
            print(f"  -> {source['department']} check ho raha hai...")
            process_source(source)
        except Exception as e:
            print(f"  [SKIP - GALTI AAYI] {source['department']} mein dikkat aayi, "
                  f"isse chhod kar aage badh rahe hain: {e}")
            traceback.print_exc()
            continue

    print(f"Group '{group_name}' ka check poora hua.")


def check_next_groups():
    """
    Ek cycle mein GROUPS_PER_CYCLE jitne groups check karta hai (round-robin),
    taaki poora 18-group rotation bahut jaldi poora ho jaaye.
    """
    total_groups = len(GROUP_NAMES)
    index = get_current_group_index()

    for i in range(GROUPS_PER_CYCLE):
        current_index = (index + i) % total_groups
        group_name = GROUP_NAMES[current_index]
        check_one_group(group_name)

    try:
        set_current_group_index(index + GROUPS_PER_CYCLE)
    except Exception as e:
        print(f"  [ERROR] Group index save karne mein dikkat: {e}")

    try:
        # Har poore rotation ke baad ek baar purani entries saaf karo
        if (index // GROUPS_PER_CYCLE) % max(1, total_groups // GROUPS_PER_CYCLE) == 0:
            cleanup_old_posts(days=CLEANUP_AFTER_DAYS)
    except Exception as e:
        print(f"  [ERROR] Purani entries saaf karne mein dikkat: {e}")

    print(f"\nIs cycle mein {GROUPS_PER_CYCLE} groups check ho gaye.\n")


if __name__ == "__main__":
    init_db()
    print("Sarkari Alert Bot shuru ho gaya hai...")
    print(f"Total {len(GROUP_NAMES)} groups hain, har {CHECK_INTERVAL_MINUTES} minute mein "
          f"{GROUPS_PER_CYCLE} groups check honge - poora rotation lagbhag "
          f"{(len(GROUP_NAMES) / GROUPS_PER_CYCLE) * CHECK_INTERVAL_MINUTES:.0f} minute mein poora hoga.")

    check_next_groups()

    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_next_groups)

    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            print(f"[ERROR] Kuch anjaan dikkat aayi, lekin bot chalta rahega: {e}")
            traceback.print_exc()
        time.sleep(30)
