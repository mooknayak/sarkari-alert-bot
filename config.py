# config.py
# Yahan aap jitni bhi websites track karna chahte hain, unki list daalte jaayein
#
# Har entry mein bas 3 cheezein chahiye:
#   "department" -> naam jo Telegram message mein dikhega
#   "type"       -> "scrape" (generic - zyaadatar sabhi sarkari sites ke liye)
#                    ya "rss" (agar us site ki RSS feed ho)
#   "url"        -> us website ka homepage/notice-page (scrape) ya RSS link (rss)
#
# Naya source jodna ho to bas neeche ek naya block copy-paste karke
# department naam aur url badal dein - selector dhundne ki zaroorat NAHI hai.

SOURCES = [
    # =========== BHAROSEMAND AGGREGATOR - RSS (asli, verified feeds) ===========
    {"department": "Amar Ujala - Jobs", "type": "rss", "url": "https://results.amarujala.com/rss/jobs.xml"},
    {"department": "Amar Ujala - Admit Card", "type": "rss", "url": "https://results.amarujala.com/rss/admit-card.xml"},
    {"department": "Amar Ujala - Result", "type": "rss", "url": "https://results.amarujala.com/rss/results-alert.xml"},
    {"department": "Amar Ujala - Exam Alert", "type": "rss", "url": "https://results.amarujala.com/rss/exam-alerts.xml"},
    {"department": "Amar Ujala - Answer Key", "type": "rss", "url": "https://results.amarujala.com/rss/answer-keys.xml"},
    {"department": "Amar Ujala - Application Form", "type": "rss", "url": "https://results.amarujala.com/rss/application-forms.xml"},

    # =========== MASHHUR PRIVATE AGGREGATOR SITES - scrape (inki RSS nahi hai) ===========
    {"department": "Sarkari Result", "type": "scrape", "url": "https://www.sarkariresult.com/"},
    {"department": "Free Job Alert", "type": "scrape", "url": "https://www.freejobalert.com/"},

    # ---------------- KENDRA SARKAR (Central Government) - scrape ----------------
    {"department": "SSC", "type": "scrape", "url": "https://ssc.gov.in/"},
    {"department": "UPSC", "type": "scrape", "url": "https://upsc.gov.in/"},
    {"department": "IBPS (Banking)", "type": "scrape", "url": "https://www.ibps.in/"},

    # ---------------- UTTAR PRADESH - scrape ----------------
    {"department": "UPPSC", "type": "scrape", "url": "https://uppsc.up.nic.in/"},
    {"department": "UPSSSC", "type": "scrape", "url": "https://upsssc.gov.in/"},
    {"department": "UP Police (UPPRPB)", "type": "scrape", "url": "https://uppbpb.gov.in/"},

    # ---------------- BIHAR - scrape ----------------
    {"department": "BPSC", "type": "scrape", "url": "https://bpsc.bihar.gov.in/"},
    {"department": "Bihar Police (CSBC)", "type": "scrape", "url": "https://csbc.bihar.gov.in/"},

    # ---------------- MADHYA PRADESH - scrape ----------------
    {"department": "MPPSC", "type": "scrape", "url": "https://mppsc.mp.gov.in/"},
    {"department": "MP ESB (Vyapam)", "type": "scrape", "url": "https://esb.mp.gov.in/"},

    # ---------------- RAJASTHAN - scrape ----------------
    {"department": "RPSC", "type": "scrape", "url": "https://rpsc.rajasthan.gov.in/"},
    {"department": "RSMSSB", "type": "scrape", "url": "https://rsmssb.rajasthan.gov.in/"},
    {"department": "Rajasthan Police", "type": "scrape", "url": "https://police.rajasthan.gov.in/"},

    # ---------------- Yahan aage aur sites jodte jaayein ----------------
    # RSS wali site ke liye:
    # {"department": "NAAM", "type": "rss", "url": "https://asli-site-ki-rss-feed.xml"},
    # Scrape wali site ke liye (selector ki zaroorat nahi):
    # {"department": "NAAM", "type": "scrape", "url": "https://asli-site-ka-url.gov.in/"},
]

# Telegram Bot settings (BotFather se mila hua asli token/ID yahan bhara hua hai)
TELEGRAM_BOT_TOKEN = "8823551734:AAGzPF5zRZZGBhwEPokVszW11kEkFe1J0fc"
TELEGRAM_CHAT_ID = "6158953448"

# Kitni der mein dobara check kare (minutes mein)
CHECK_INTERVAL_MINUTES = 30

# Database file ka naam
DATABASE_FILE = "posts.db"
