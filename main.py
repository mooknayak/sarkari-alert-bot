# main.py
# Poore tool ka "dil" - isi file ko Railway per chalaya jaayega
#
# NAYA: Agar koi source (jaise SSC/UPSC) baar-baar (5 baar) lagataar
# fail ho, to use 6 ghante ke liye "cooldown" mein daal dete hain -
# taaki har cycle mein waqt barbaad na ho aisi site try karne mein jo
# waise bhi block hai. Har alert mein ab asli vibhag ki official
# website dikhti hai, chaahe post kisi aggregator se mila ho.

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
    record_source_failure, record_source_success, is_source_in_cooldown,
)
from scraper import (
    fetch_new_posts, detect_category, extract_vacancy,
    find_apply_link, resolve_official_site,
)
from telegram_bot import send_alert


def process_source(source):
    department = source["department"]

    if is_source_in_cooldown(department):
        print(f"  [COOLDOWN] {department} baar-baar fail ho raha tha, "
              f"kuch ghanton ke liye chhod rahe hain waqt bachaane ke liye")
        return

    try:
        posts = fetch_new_posts(source)
        record_source_success(department)
    except Exception as e:
        record_source_failure(department)
        raise

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
            # Asli vibhag ki official website dhoondo (aggregator ki nahi)
            official_site = resolve_official_site(post["title"], source["url"])

            send_alert(
                department=post["department"],
                title=post["title"],
                category=category,
                vacancy=vacancy,
                link=post["link"],
                source_site=official_site,
                apply_link=apply_link,
            )
            print(f"     [NEW ALERT] {post['title']} ({category})"
                  f" - Apply link {'mila' if apply_link else 'nahi mila'}")

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
            continue

    print(f"Group '{group_name}' ka check poora hua.")


def check_next_groups():
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
        if (index // GROUPS_PER_CYCLE) % max(1, total_groups // GROUPS_PER_CYCLE) == 0:
            cleanup_old_posts(days=CLEANUP_AFTER_DAYS)
    except Exception as e:
        print(f"  [ERROR] Purani entries saaf karne mein dikkat: {e}")

    print(f"\nIs cycle mein {GROUPS_PER_CYCLE} groups check ho gaye.\n")


if __name__ == "__main__":
    init_db()
    print("Sarkari Alert Bot shuru ho gaya hai...")
    print(f"Total {len(GROUP_NAMES)} groups hain, har {CHECK_INTERVAL_MINUTES} minute mein "
          f"{GROUPS_PER_CYCLE} groups check honge.")

    check_next_groups()

    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_next_groups)

    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            print(f"[ERROR] Kuch anjaan dikkat aayi, lekin bot chalta rahega: {e}")
            traceback.print_exc()
        time.sleep(30)
