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
    AUTO_PUBLISH_TO_SANITY, MAX_ALERTS_PER_SOURCE_PER_RUN, SEED_VERSION,
    HEALTH_REPORT_EVERY_HOURS,
)
from database import (
    init_db, is_new_post, save_post, delete_post,
    is_source_seeded, mark_source_seeded, cleanup_old_posts,
    record_source_failure, record_source_success, is_source_in_cooldown,
    get_state, set_state, reseed_if_version_changed,
)
from scraper import (
    fetch_new_posts, detect_category, extract_vacancy,
    resolve_official_site, fetch_full_details_with_pdf,
    download_and_extract_pdf_text, detect_status,
)
from official_links import find_official_links, is_official_url
from telegram_bot import send_alert, send_text
from portal_fetch import METHOD_USED

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

OPTIONAL_SOURCES = {s["department"] for s in ALL_SOURCES if s.get("optional")}


def try_publish_to_sanity(post, apply_link):
    """🆕 Naye post ko Sanity mein DRAFT banaata hai. Yeh function jaan-bujh
    kar apna alag try/except rakhta hai - agar AI ya Sanity mein kuch bhi
    gadbad ho, to sirf yeh ek step fail hoga, Telegram alert (jo already
    bhej diya gaya) aur baaki poora bot bilkul theek chalta rahega."""
    try:
        # 🆕 Ab sirf listing page nahi, official notification PDF bhi
        # padhi jaati hai - isse AI ko poori, asli detail milti hai
        if post["link"].lower().split("?")[0].endswith(".pdf"):
            full_text = download_and_extract_pdf_text(post["link"]) or ""
        else:
            full_text = fetch_full_details_with_pdf(post["link"])
        # 🆕 Status ka bharosemand andaza (keyword se) - AI ke guess par
        # akela nirbhar nahi rehte, isse "hamesha job hi ban jaata hai"
        # wali samasya khatam ho jaati hai
        status_hint = detect_status(post["title"])
        raw_for_ai = (
            f"Title: {post['title']}\n"
            f"Department: {post['department']}\n"
            f"Likely Status: {status_hint} (yeh keyword-match se pehchana gaya, isi ko istemal karo jab tak content mein saaf koi doosra status na dikhe)\n"
            f"Notice Link: {post['link']}\n"
            f"Apply Link: {apply_link or 'N/A'}\n\n"
            f"Page Content:\n{full_text}"
        )
        result = publish_scraped_post(raw_for_ai, post["link"], status_hint=status_hint)
        if result.get("duplicate"):
            print(f"    [SKIP - DUPLICATE] '{result['title']}' pehle se kisi doosre source se ban chuka hai")
        else:
            print(f"    [SANITY DRAFT BANA] {result['title']} -> Studio mein review karke Publish karein")
    except Exception as e:
        print(f"    [SANITY ERROR] '{post['title']}' ke liye draft nahi ban paaya: {e}")


# Category ke hisaab se Telegram mein kaunsa "mukhya link" dikhana hai
PRIMARY_BY_CATEGORY = {
    "Admit Card": ("🎫 Admit Card लिंक", "Download Admit Card"),
    "Result": ("📊 Result लिंक", "Check Result"),
    "Answer Key": ("🔑 Answer Key लिंक", "Check Result"),
}
DEFAULT_PRIMARY = ("📝 Apply Online", "Apply Online")


def _method_tag(department):
    method = METHOD_USED.get(department)
    return f" [{method}]" if method else ""


def process_source(source):
    """Ek website ko check karta hai. Yeh function alag-alag threads
    (ek saath, parallel) mein chalta hai.
    Return: (status, department, message) - status: ok / seeded / empty /
    fail / cooldown."""
    department = source["department"]

    if is_source_in_cooldown(department):
        return ("cooldown", department, f"[COOLDOWN] {department} - abhi ke liye chhoda gaya")

    try:
        posts = fetch_new_posts(source)
        record_source_success(department)
    except Exception as e:
        record_source_failure(department)
        return ("fail", department, f"[FAIL] {department}: {e}")

    # 🆕 Koi relevant link hi nahi mila - site khuli to, par kuch nikla nahi.
    # Ise "seed" nahi karte (warna baad mein sab purani posts ek saath 'nayi'
    # ban jaati) aur saaf dikhate hain ki yahan kuch gadbad hai.
    if not posts:
        return ("empty", department, f"[EMPTY] {department} - 0 relevant links mile (seed nahi kiya)")

    first_time = not is_source_seeded(department)
    new_alert_count = 0

    for post in posts:
        if not is_new_post(post["link"], post["title"]):
            continue

        category = detect_category(post["title"])
        # 🆕 Private portal ki har post kaam ki hoti hai - keyword na mile to bhi
        # "Notification" maano (pehle "General Update" ban kar chhoot jaati thi)
        if category == "General Update" and source.get("assume_relevant"):
            category = "Notification"
        vacancy = extract_vacancy(post["title"])

        # Pehli baar ya jo category allowed nahi: bas yaad rakho, alert nahi
        if first_time or category not in ALLOWED_CATEGORIES:
            save_post(department=post["department"], title=post["title"],
                      link=post["link"], category=category, vacancy=vacancy)
            continue

        # Ek baar mein bauchhar na ho - baaki agli baar (unhe save nahi karte)
        if new_alert_count >= MAX_ALERTS_PER_SOURCE_PER_RUN:
            break

        # Pehle "claim" kar lo (taaki doosre thread se wahi post dobara na
        # jaaye), bhejna fail ho to neeche wapas hata denge
        save_post(department=post["department"], title=post["title"],
                  link=post["link"], category=category, vacancy=vacancy)

        # 🆕 Post-page se AADHIKARIK links (gov/nic) nikalo
        try:
            info = find_official_links(post["link"])
        except Exception:
            info = {"by_type": {}}
        by_type = info.get("by_type", {})

        label, primary_type = PRIMARY_BY_CATEGORY.get(category, DEFAULT_PRIMARY)
        apply_link = (by_type.get(primary_type) or {}).get("url")
        notification_link = (by_type.get("Official Notification") or {}).get("url")
        # Agar post ka link khud aadhikarik hai (sarkari site se mila), to
        # wahi notification link bhi hai
        if not notification_link and is_official_url(post["link"]):
            notification_link = post["link"]
        official_site = (
            (by_type.get("Official Website") or {}).get("url")
            or resolve_official_site(post["title"], source["url"])
        )

        sent = send_alert(
            department=post["department"],
            title=post["title"],
            category=category,
            vacancy=vacancy,
            link=post["link"],
            source_site=official_site,
            apply_link=apply_link,
            notification_link=notification_link,
            primary_label=label,
        )
        if not sent:
            delete_post(post["link"])   # agli baar phir koshish hogi
            continue
        new_alert_count += 1

        if AUTO_PUBLISH_TO_SANITY:
            try_publish_to_sanity(post, apply_link)

    if first_time:
        mark_source_seeded(department)
        return ("seeded", department,
                f"[SEEDED] {department}{_method_tag(department)} - {len(posts)} purani entries yaad rakhi gayin")

    if new_alert_count:
        return ("ok", department, f"[OK] {department}{_method_tag(department)} - {new_alert_count} naya alert bheja")

    return ("ok", department, f"[OK] {department}{_method_tag(department)} - kuch naya nahi mila")


def _short_reason(msg):
    """Lambi error ko chhote Hindi karan mein badalta hai."""
    low = (msg or "").lower()
    if "403" in low or "forbidden" in low:
        return "403 रोक"
    if "429" in low:
        return "बहुत तेज़ (429)"
    if "timed out" in low or "timeout" in low:
        return "समय खत्म (IP रोक?)"
    if "connectionpool" in low or "connection reset" in low or "max retries" in low \
            or "connection aborted" in low or "connectionreset" in low or "connectionerror" in low:
        return "कनेक्शन नहीं बना (IP रोक?)"
    if "links hi nahi" in low or "javascript" in low:
        return "JS/सुरक्षा पेज"
    if "busy/blocked" in low:
        return "साइट busy/blocked"
    return msg.split(":", 1)[-1].strip()[:50]


def maybe_send_health_report(results):
    """Roz ek baar Telegram par bot ki sehat. Private portal ka vistaar se
    (kaun sa tareeka chala / kyun fail), sarkari (optional) sites ki sirf ginti."""
    try:
        last = get_state("last_health_report")
        if last and time.time() - float(last) < HEALTH_REPORT_EVERY_HOURS * 3600:
            return
        good = {"ok", "seeded"}
        main_res = [r for r in results if r[1] not in OPTIONAL_SOURCES]
        opt_res = [r for r in results if r[1] in OPTIONAL_SOURCES]

        lines = ["📊 Sarkari Alert Bot - रिपोर्ट", "", "🌐 प्राइवेट पोर्टल (मुख्य):"]
        for status, dept, msg in sorted(main_res, key=lambda r: r[1]):
            if status in good:
                method = METHOD_USED.get(dept)
                lines.append(f"✅ {dept}" + (f" — {method}" if method else ""))
            elif status == "empty":
                lines.append(f"⚪ {dept} — खाली (0 लिंक)")
            elif status == "cooldown":
                lines.append(f"⏳ {dept} — अभी छोड़ा गया")
            else:
                lines.append(f"❌ {dept} — {_short_reason(msg)}")

        if opt_res:
            ok_n = sum(1 for r in opt_res if r[0] in good)
            lines += ["", f"🏛 सरकारी विभाग (वैकल्पिक): {ok_n}/{len(opt_res)} चले"]
            bad = [r[1] for r in opt_res if r[0] not in good]
            if bad:
                lines.append("न चले: " + ", ".join(bad))
        if send_text("\n".join(lines)):
            set_state("last_health_report", time.time())
    except Exception as e:
        print(f"  [ERROR] Health report mein dikkat: {e}")


def check_all_sources():
    """Sabhi sources ko ek saath (parallel, max MAX_CONCURRENT_SOURCES
    ek waqt mein) check karta hai."""
    start_time = time.time()
    print(f"\n[{time.strftime('%d-%m-%Y %H:%M:%S')}] Poora check shuru - "
          f"{len(ALL_SOURCES)} sources, {MAX_CONCURRENT_SOURCES} ek saath")

    # 🆕 Naye niyam laagu hone par ek baar chup-chaap dobara "yaad" karna
    try:
        if reseed_if_version_changed(SEED_VERSION):
            print("  [RESEED] Naya update laagu hua - is baar sabhi sources ki maujooda "
                  "posts chup-chaap yaad ki jaayengi (alert nahi jayenge)")
            send_text("ℹ️ बोट अपडेट हुआ। इस बार सभी साइटों की मौजूदा पोस्टें चुपचाप "
                      "याद की जा रही हैं (अलर्ट नहीं आएंगे)। अगली बार से सिर्फ नई "
                      "पोस्टों के अलर्ट आएंगे।")
    except Exception as e:
        print(f"  [ERROR] Reseed mein dikkat: {e}")

    results = []
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_SOURCES) as executor:
        futures = {executor.submit(process_source, source): source for source in ALL_SOURCES}

        for future in as_completed(futures):
            source = futures[future]
            try:
                status, dept, message = future.result()
                results.append((status, dept, message))
                print(f"  {message}")
            except Exception as e:
                # Suraksha: kisi ek source mein anjaan error aaye to bhi
                # baaki sab chalte rahenge
                msg = f"[SKIP - GALTI AAYI] {source['department']}: {e}"
                results.append(("fail", source["department"], msg))
                print(f"  {msg}")

    try:
        cleanup_old_posts(days=CLEANUP_AFTER_DAYS)
    except Exception as e:
        print(f"  [ERROR] Purani entries saaf karne mein dikkat: {e}")

    maybe_send_health_report(results)

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
