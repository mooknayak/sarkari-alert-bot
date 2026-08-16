# config.py
# Yahan aap jitni bhi websites track karna chahte hain, unki list daalte jaayein
# type: "rss" ya "scrape"
# scrape wali sites ke liye selector aage scraper.py mein set karna hoga

SOURCES = [
    {
        "department": "SSC",
        "type": "scrape",
        "url": "https://ssc.nic.in/",
        "selector": "a.whats-new-link",   # Note: yeh sirf example selector hai,
                                            # asli site dekh kar sahi selector daalna hoga
    },
    {
        "department": "UPSC",
        "type": "scrape",
        "url": "https://upsc.gov.in/whats-new",
        "selector": "a.views-field-title",  # example selector - verify from real site
    },
    # Yahan aage UP, Bihar, MP, Rajasthan aur baaki central sites jodte jaayein:
    # {
    #     "department": "UPPSC",
    #     "type": "scrape",
    #     "url": "https://uppsc.up.nic.in/",
    #     "selector": "...",
    # },
]

# Telegram Bot settings (BotFather se milega)
TELEGRAM_BOT_TOKEN = "8823551734:AAGzPF5zRZZGBhwEPokVszW11kEkFe1J0fc"
TELEGRAM_CHAT_ID = "6158953448"

# Kitni der mein dobara check kare (minutes mein)
CHECK_INTERVAL_MINUTES = 30

# Database file ka naam
DATABASE_FILE = "posts.db"
