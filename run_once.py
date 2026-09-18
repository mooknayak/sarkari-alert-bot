# run_once.py
# 🆕 NAYI FILE
#
# Yeh file GitHub Actions ke liye banayi gayi hai. main.py (jo hamesha
# chalta rehta hai, apne andar hi 20-minute wala scheduler leke) ke
# bajaye, yeh sirf EK BAAR poora check chalakar exit ho jaati hai -
# kyunki GitHub Actions khud hi isko har 20 minute mein naye sirre se
# chalata hai (.github/workflows/check-sources.yml mein cron se).
#
# Isse database.py, scraper.py, telegram_bot.py, sanity_publisher.py -
# in sabmein KOI badlaav nahi karna pada, sirf yeh chhoti nayi file
# unhe "ek baar chalao" tareeke se istemal karti hai.

from database import init_db
from main import check_all_sources

if __name__ == "__main__":
    init_db()
    check_all_sources()
