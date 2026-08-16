# config.py
# Yahan aap jitni bhi websites track karna chahte hain, unki list daalte jaayein
#
# Har entry mein bas 3 cheezein chahiye:
#   "department" -> naam jo Telegram message mein dikhega
#   "type"       -> "scrape" (generic - zyaadatar sabhi sarkari sites ke liye)
#                    ya "rss" (agar us site ki RSS feed ho, bahut kam sites ki hoti hai)
#   "url"        -> us website ka homepage ya "What's New" / "Notice" wala page
#
# Naya source jodna ho to bas neeche ek naya block copy-paste karke
# department naam aur url badal dein - selector dhundne ki zaroorat NAHI hai.

SOURCES = [
    # ---------------- KENDRA SARKAR (Central Government) ----------------
    {"department": "SSC", "type": "scrape", "url": "https://ssc.gov.in/"},
    {"department": "UPSC", "type": "scrape", "url": "https://upsc.gov.in/"},
    {"department": "IBPS (Banking)", "type": "scrape", "url": "https://www.ibps.in/"},

    # ---------------- UTTAR PRADESH ----------------
    {"department": "UPPSC", "type": "scrape", "url": "https://uppsc.up.nic.in/"},
    {"department": "UPSSSC", "type": "scrape", "url": "https://upsssc.gov.in/"},
    {"department": "UP Police (UPPRPB)", "type": "scrape", "url": "https://uppbpb.gov.in/"},

    # ---------------- BIHAR ----------------
    {"department": "BPSC", "type": "scrape", "url": "https://bpsc.bihar.gov.in/"},
    {"department": "Bihar Police (CSBC)", "type": "scrape", "url": "https://csbc.bihar.gov.in/"},

    # ---------------- MADHYA PRADESH ----------------
    {"department": "MPPSC", "type": "scrape", "url": "https://mppsc.mp.gov.in/"},
    {"department": "MP ESB (Vyapam)", "type": "scrape", "url": "https://esb.mp.gov.in/"},

    # ---------------- RAJASTHAN ----------------
    {"department": "RPSC", "type": "scrape", "url": "https://rpsc.rajasthan.gov.in/"},
    {"department": "RSMSSB", "type": "scrape", "url": "https://rsmssb.rajasthan.gov.in/"},
    {"department": "Rajasthan Police", "type": "scrape", "url": "https://police.rajasthan.gov.in/"},

    # ---------------- Yahan aage aur sites jodte jaayein ----------------
    # Bas neeche jaisa ek line jodni hai - koi selector nahi chahiye:
    # {"department": "NAAM", "type": "scrape", "url": "https://asli-site-ka-url.gov.in/"},
]

# Telegram Bot settings (BotFather se milega)
TELEGRAM_BOT_TOKEN = "YAHAN_APNA_BOT_TOKEN_DAALEIN"
TELEGRAM_CHAT_ID = "YAHAN_APNA_CHAT_ID_DAALEIN"

# Kitni der mein dobara check kare (minutes mein)
CHECK_INTERVAL_MINUTES = 30

# Database file ka naam
DATABASE_FILE = "posts.db"
