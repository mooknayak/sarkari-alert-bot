# main.py
# Poore tool ka "dil" - isi file ko Railway per chalaya jaayega
#
# NAYA DESIGN: Ab groups ko baari-baari (round-robin) check karne ki
# jagah, SABHI 136 sources ko ek saath (parallel) check karte hain -
# bas ek waqt mein zyada se zyada MAX_CONCURRENT_SOURCES (config.py
# mein set) hi ek saath chalte hain, taaki server par zyada load na pade.
#
# Isse poora rotation (jo pehle 1.5+ ghante leta tha) ab sirf kuch
# minute mein poora ho jaata hai - kyunki ab bot ek website ke jawab
# ka intezaar karte hue "khaali" nahi baithta, us waqt mein doosri
# websites se bhi baat kar raha hota hai.
#
# 🆕 NAYA (Sanity Auto-Publish): Ab har naye, relevant post ke liye
# Telegram alert ke saath-saath (agar config.py mein AUTO_PUBLISH_TO_SANITY
# "true" hai) bot khud jaakar notice ka poora page padhta hai, AI se
# professional post likhwaata hai, aur use Sanity mein ek DRAFT ke roop
# mein save kar deta hai - aap sirf Studio mein jaakar Publish dabayenge.

import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import schedule

from config import (
    SOURCE_GROUPS, ALLOWED_CATEGORIES,
    CHECK_INTERVAL_MINUTES, CLEANUP_AFTER_DAYS, MAX_CONCURRENT_SOURCES,
    AUTO_PUBLISH_TO_SANITY,
)
from database import (
    init_db, is_new_post, save_post,
    is_source_seeded, mark_source_seeded, cleanup_old_posts,
    record_source_failure, record_source_success, is_source_in_cooldown,
)
from scraper import (
    fetch_new_posts, detect_category, extract_vacancy,
    find_apply_link, resolve_official_site, fetch_full_details,
)
from telegram_bot import send_alert

# 🆕 Sanity publishing sirf tabhi import hoga jab feature ON ho - isse agar
# koi Sanity/Gemini env variable missing bhi ho, to bot bina us feature ke
# (sirf Telegram alerts ke saath) bina crash hue chalta rahega.
if AUTO_PUBLISH_TO_SANITY:
    from sanity_publisher import publish_scraped_post

# Sabhi groups ke sources ko ek hi lambi list mein jod dete hain -
# ab "group" sirf naam/organisation ke liye hai, checking sabki
# ek saath hoti hai
ALL_SOURCES = []
for _group_name, _sources in SOURCE_GROUPS.items():
    ALL_SOURCES.extend(_sources)


def try_publish_to_sanity(post, apply_link):
    """🆕 Naye post ko Sanity mein DRAFT banaata hai. Yeh function jaan-bujh
    kar apna alag try/except rakhta hai - agar AI ya Sanity mein kuch bhi
    gadbad ho, to sirf yeh ek step fail hoga, Telegram alert (jo already
    bhej diya gaya) aur baaki poora bot bilkul theek chalta rahega."""
    try:
        full_text = fetch_full_details(post["link"])
        raw_for_ai = (
            f"Title: {post['title']}\n"
            f"Department: {post['department']}\n"
            f"Notice Link: {post['link']}\n"
            f"Apply Link: {apply_link or 'N/A'}\n\n"
            f"Page Content:\n{full_text}"
        )
        result = publish_scraped_post(raw_for_ai, post["link"])
        print(f"    [SANITY DRAFT BANA] {result['title']} -> Studio mein review karke Publish karein")
    except Exception as e:
        print(f"    [SANITY ERROR] '{post['title']}' ke liye draft nahi ban paaya: {e}")


def process_source(source):
    """Ek website ko check karta hai. Yeh function alag-alag threads
    (ek saath, parallel) mein chalta hai - isliye ismein koi shared
    cheez bina lock ke nahi likhi jaati (database/telegram apna khud
    ka lock sambhalte hain)."""
    department = source["department"]

    if is_source_in_cooldown(department):
        return f"[COOLDOWN] {department} - abhi ke liye chhoda gaya"

    try:
        posts = fetch_new_posts(source)
        record_source_success(department)
    except Exception as e:
        record_source_failure(department)
        return f"[FAIL] {department}: {e}"

    first_time = not is_source_seeded(department)
    new_alert_count = 0

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
                continue

            apply_link = find_apply_link(post["link"])
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
            new_alert_count += 1

            # 🆕 Telegram alert ke turant baad, agar feature ON hai to
            # Sanity draft bhi bana dete hain - isi post ke liye
            if AUTO_PUBLISH_TO_SANITY:
                try_publish_to_sanity(post, apply_link)

    if first_time:
        mark_source_seeded(department)
        return f"[SEEDED] {department} - {len(posts)} purani entries yaad rakhi gayin"

    if new_alert_count:
        return f"[OK] {department} - {new_alert_count} naya alert bheja"

    return f"[OK] {department} - kuch naya nahi mila"


def check_all_sources():
    """Sabhi sources ko ek saath (parallel, max MAX_CONCURRENT_SOURCES
    ek waqt mein) check karta hai."""
    start_time = time.time()
    print(f"\n[{time.strftime('%d-%m-%Y %H:%M:%S')}] Poora check shuru - "
          f"{len(ALL_SOURCES)} sources, {MAX_CONCURRENT_SOURCES} ek saath")

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_SOURCES) as executor:
        futures = {executor.submit(process_source, source): source for source in ALL_SOURCES}

        for future in as_completed(futures):
            source = futures[future]
            try:
                result = future.result()
                print(f"  {result}")
            except Exception as e:
                # Suraksha: kisi ek source mein anjaan error aaye to bhi
                # baaki sab chalte rahenge
                print(f"  [SKIP - GALTI AAYI] {source['department']}: {e}")

    try:
        cleanup_old_posts(days=CLEANUP_AFTER_DAYS)
    except Exception as e:
        print(f"  [ERROR] Purani entries saaf karne mein dikkat: {e}")

    elapsed = time.time() - start_time
    print(f"\nPoora check khatam - {elapsed:.0f} second mein {len(ALL_SOURCES)} sources ho gaye.\n")


if __name__ == "__main__":
    init_db()
    print("Sarkari Alert Bot shuru ho gaya hai...")
    print(f"Total {len(ALL_SOURCES)} sources hain, har {CHECK_INTERVAL_MINUTES} minute mein "
          f"SABHI ek saath (max {MAX_CONCURRENT_SOURCES} parallel) check honge.")
    print(f"Sanity Auto-Publish: {'ON ✅' if AUTO_PUBLISH_TO_SANITY else 'OFF (sirf Telegram alerts jayenge)'}")

    check_all_sources()

    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_all_sources)

    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            print(f"[ERROR] Kuch anjaan dikkat aayi, lekin bot chalta rahega: {e}")
            traceback.print_exc()
        time.sleep(30)
