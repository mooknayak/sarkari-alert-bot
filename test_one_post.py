# test_one_post.py
#
# 🔁 STHAYI (PERMANENT) FEATURE - sirf testing ke liye nahi!
#
# Yeh file kisi bhi platform (Sarkari Result, FreeJobAlert, koi bhi
# sarkari website, kahin se bhi) ke KISI EK notice/post ka poora URL
# lekar, usse poore pipeline (page padhna -> AI se apne shabdon mein
# maulik/unique Hindi post likhwana -> Sanity mein DRAFT banana) se
# guzar deti hai - bilkul waisa hi jaisa roz-marra wala automatic bot
# (main.py/run_once.py) karta hai.
#
# ISTEMAL KAB KAB KAR SAKTE HAIN:
#   1) Testing ke liye - confirm karne ke liye ki system sahi kaam kar
#      raha hai.
#   2) HAMESHA KE LIYE - jab bhi koi khaas post turant apni website par
#      chahiye ho (chahe woh kisi bhi platform/website se mile), bas
#      uska link yahan de dein - AI turant apna, maulik (kabhi copy-paste
#      nahi) version likh kar draft bana dega, aap Studio mein review
#      karke Publish kar denge.
#
# Database ke "kya yeh pehle se dekha hua hai?" wale filter ko yeh
# jaan-bujh kar BYPASS karti hai - isliye chahe woh post purani ho ya
# kisi bhi source se ho, hamesha kaam karegi.

import sys
from scraper import fetch_full_details
from sanity_publisher import publish_scraped_post

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ Galti: notice ka poora URL dena zaroori hai")
        sys.exit(1)

    url = sys.argv[1]
    print(f"🔎 Shuru: {url}")

    full_text = fetch_full_details(url)
    if not full_text:
        print("⚠️  Chetavani: page se text theek se nahi mila, phir bhi try kar rahe hain...")
    else:
        print(f"✅ Page se {len(full_text)} characters text mila")

    raw_for_ai = f"Notice Link: {url}\n\nPage Content:\n{full_text}"

    print("🤖 AI se apna maulik, professional post likhwa rahe hain...")
    result = publish_scraped_post(raw_for_ai, url)

    print(f"🎉 SAFAL! Draft ban gaya:")
    print(f"   Title: {result['title']}")
    print(f"   Slug: {result['slug']}")
    print(f"   Ab Sanity Studio (aapki-site.com/studio) mein jaakar 'All Job Posts' mein dekhein")
