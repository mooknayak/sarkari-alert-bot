# config.py
#
# SURAKSHA: Telegram Token/Chat ID ab is file mein NAHI likhe - Railway ke
# "Variables" tab se (environment variable ke through) aate hain. Isse
# GitHub par code dekhne wale kisi ko bhi aapka asli token nahi dikhega.

import os

SOURCE_GROUPS = {

    "Bharosemand Aggregator": [
        {"department": "Amar Ujala - Jobs", "type": "rss", "url": "https://results.amarujala.com/rss/jobs.xml"},
        {"department": "Amar Ujala - Admit Card", "type": "rss", "url": "https://results.amarujala.com/rss/admit-card.xml"},
        {"department": "Amar Ujala - Result", "type": "rss", "url": "https://results.amarujala.com/rss/results-alert.xml"},
        {"department": "Amar Ujala - Exam Alert", "type": "rss", "url": "https://results.amarujala.com/rss/exam-alerts.xml"},
        {"department": "Amar Ujala - Answer Key", "type": "rss", "url": "https://results.amarujala.com/rss/answer-keys.xml"},
        {"department": "Amar Ujala - Application Form", "type": "rss", "url": "https://results.amarujala.com/rss/application-forms.xml"},
        {"department": "Sarkari Result", "type": "scrape", "url": "https://www.sarkariresult.com/"},
        {"department": "Free Job Alert", "type": "scrape", "url": "https://www.freejobalert.com/"},
    ],

    "Kendra Sarkar - Aayog aur Board": [
        {"department": "UPSC", "type": "scrape", "url": "https://www.upsc.gov.in"},
        {"department": "SSC", "type": "scrape", "url": "https://ssc.gov.in"},
        {"department": "RRB / RRC (Railway)", "type": "scrape", "url": "https://www.rrcb.gov.in"},
        {"department": "RRB Prayagraj (Railway)", "type": "scrape", "url": "https://rrbpryj.gov.in/"},
        {"department": "IBPS (Banking)", "type": "scrape", "url": "https://www.ibps.in"},
        {"department": "National Career Service", "type": "scrape", "url": "https://www.ncs.gov.in"},
        {"department": "Employment News", "type": "scrape", "url": "https://employmentnews.gov.in"},
    ],

    "Raksha Kshetra (Defence)": [
        {"department": "Indian Army", "type": "scrape", "url": "https://joinindianarmy.nic.in"},
        {"department": "Indian Navy", "type": "scrape", "url": "https://joinindiannavy.gov.in"},
        {"department": "Indian Air Force", "type": "scrape", "url": "https://careerairforce.gov.in"},
        {"department": "Indian Coast Guard", "type": "scrape", "url": "https://joinindiancoastguard.cdac.in"},
        {"department": "Border Roads Organisation (BRO)", "type": "scrape", "url": "https://bro.gov.in"},
    ],

    "Anusandhan Aur Vaigyanik Sansthan": [
        {"department": "DRDO", "type": "scrape", "url": "https://www.drdo.gov.in"},
        {"department": "ISRO", "type": "scrape", "url": "https://www.isro.gov.in"},
        {"department": "CSIR", "type": "scrape", "url": "https://www.csir.res.in"},
        {"department": "ICAR", "type": "scrape", "url": "https://icar.org.in"},
        {"department": "ICMR", "type": "scrape", "url": "https://www.icmr.gov.in"},
        {"department": "BARC", "type": "scrape", "url": "https://barc.gov.in"},
        {"department": "NPCIL", "type": "scrape", "url": "https://www.npcil.nic.in"},
        {"department": "KVS (Kendriya Vidyalaya)", "type": "scrape", "url": "https://kvsangathan.nic.in"},
        {"department": "NVS (Navodaya Vidyalaya)", "type": "scrape", "url": "https://navodaya.gov.in"},
        {"department": "AIIMS", "type": "scrape", "url": "https://www.aiims.edu"},
    ],

    "Kendriya Police Aur Mantralaya": [
        {"department": "Intelligence Bureau (Home Ministry)", "type": "scrape", "url": "https://www.mha.gov.in"},
        {"department": "CBI", "type": "scrape", "url": "https://cbi.gov.in"},
        {"department": "NIA", "type": "scrape", "url": "https://www.nia.gov.in"},
        {"department": "Postal Department (India Post)", "type": "scrape", "url": "https://www.indiapost.gov.in"},
        {"department": "EPFO", "type": "scrape", "url": "https://www.epfindia.gov.in"},
        {"department": "ESIC", "type": "scrape", "url": "https://www.esic.nic.in"},
        {"department": "FCI", "type": "scrape", "url": "https://fci.gov.in"},
        {"department": "FSSAI", "type": "scrape", "url": "https://www.fssai.gov.in"},
    ],

    "PSU (Maharatna/Navratna)": [
        {"department": "ONGC", "type": "scrape", "url": "https://www.ongcindia.com"},
        {"department": "NTPC", "type": "scrape", "url": "https://www.ntpc.co.in"},
        {"department": "IOCL", "type": "scrape", "url": "https://iocl.com"},
        {"department": "BHEL", "type": "scrape", "url": "https://www.bhel.com"},
        {"department": "GAIL", "type": "scrape", "url": "https://gailonline.com"},
        {"department": "CIL (Coal India)", "type": "scrape", "url": "https://www.coalindia.in"},
        {"department": "BPCL", "type": "scrape", "url": "https://www.bpcl.co.in"},
        {"department": "HPCL", "type": "scrape", "url": "https://www.hindustanpetroleum.com"},
        {"department": "NHPC", "type": "scrape", "url": "https://www.nhpcindia.com"},
        {"department": "BEL", "type": "scrape", "url": "https://www.bel-india.in"},
        {"department": "HAL", "type": "scrape", "url": "https://hal-india.co.in"},
        {"department": "BSNL", "type": "scrape", "url": "https://www.bsnl.co.in"},
    ],

    "Vittiya Sansthan Aur Bank (Central)": [
        {"department": "RBI", "type": "scrape", "url": "https://www.rbi.org.in"},
        {"department": "NABARD", "type": "scrape", "url": "https://www.nabard.org"},
        {"department": "SIDBI", "type": "scrape", "url": "https://www.sidbi.in"},
        {"department": "SEBI", "type": "scrape", "url": "https://www.sebi.gov.in"},
        {"department": "LIC", "type": "scrape", "url": "https://licindia.in"},
        {"department": "GIC Re", "type": "scrape", "url": "https://gicre.in"},
        {"department": "EXIM Bank", "type": "scrape", "url": "https://www.eximbankindia.in"},
        {"department": "NHB", "type": "scrape", "url": "https://www.nhb.org.in"},
        {"department": "SBI", "type": "scrape", "url": "https://sbi.co.in"},
        {"department": "PNB", "type": "scrape", "url": "https://www.pnbindia.in"},
        {"department": "Bank of Baroda", "type": "scrape", "url": "https://www.bankofbaroda.in"},
        {"department": "Canara Bank", "type": "scrape", "url": "https://canarabank.com"},
    ],

    "Public Sector Banks (Baaki)": [
        {"department": "Union Bank of India", "type": "scrape", "url": "https://www.unionbankofindia.co.in"},
        {"department": "Bank of India", "type": "scrape", "url": "https://www.bankofindia.co.in"},
        {"department": "Indian Bank", "type": "scrape", "url": "https://www.indianbank.in"},
        {"department": "Central Bank of India", "type": "scrape", "url": "https://www.centralbankofindia.co.in"},
        {"department": "Indian Overseas Bank", "type": "scrape", "url": "https://www.iob.in"},
        {"department": "UCO Bank", "type": "scrape", "url": "https://www.ucobank.com"},
        {"department": "Bank of Maharashtra", "type": "scrape", "url": "https://bankofmaharashtra.in"},
        {"department": "Punjab & Sind Bank", "type": "scrape", "url": "https://punjabandsindbank.co.in"},
    ],

    "Uttar Pradesh": [
        {"department": "UPPSC", "type": "scrape", "url": "https://uppsc.up.nic.in"},
        {"department": "UPSSSC", "type": "scrape", "url": "https://upsssc.gov.in"},
        {"department": "UP Police (UPPRPB)", "type": "scrape", "url": "https://uppbpb.gov.in"},
        {"department": "UP Police (uppolice.gov.in)", "type": "scrape", "url": "https://uppolice.gov.in"},
        {"department": "UPHESC (College Teachers)", "type": "scrape", "url": "https://uphesc.org"},
        {"department": "Allahabad High Court", "type": "scrape", "url": "https://www.allahabadhighcourt.in"},
        {"department": "UP Van Vibhag (Forest Dept)", "type": "scrape", "url": "http://upforest.gov.in"},
        {"department": "UP Basic Shiksha Board (UPEB)", "type": "scrape", "url": "http://basiceduboard.up.gov.in"},
        {"department": "UP Madhyamik Shiksha Parishad (UPMSP)", "type": "scrape", "url": "https://upmsp.edu.in"},
        {"department": "UPPCL (Power Corporation)", "type": "scrape", "url": "https://www.uppcl.org"},
        {"department": "BTEUP (Praavidhik Shiksha)", "type": "scrape", "url": "http://bteup.ac.in"},
        {"department": "Sewayojan UP (Rojgar Portal)", "type": "scrape", "url": "https://sewayojan.up.nic.in"},
        {"department": "UP Cooperative Service Board", "type": "scrape", "url": "https://upcssb.in"},
    ],

    "Bihar": [
        {"department": "BPSC", "type": "scrape", "url": "https://bpsc.bihar.gov.in"},
        {"department": "Bihar Police (CSBC)", "type": "scrape", "url": "https://csbc.bihar.gov.in"},
        {"department": "BSSC", "type": "scrape", "url": "https://bssc.bihar.gov.in"},
        {"department": "BPSSC", "type": "scrape", "url": "https://bpssc.bih.nic.in"},
        {"department": "BSEB (Bihar Board)", "type": "scrape", "url": "https://biharboardonline.bihar.gov.in"},
        {"department": "BCECEB", "type": "scrape", "url": "https://bceceboard.bihar.gov.in"},
        {"department": "BTSC (Technical Service)", "type": "scrape", "url": "https://btsc.bih.nic.in"},
        {"department": "Bihar Shiksha Vibhag", "type": "scrape", "url": "https://education.bihar.gov.in"},
        {"department": "BSUSC (University Service)", "type": "scrape", "url": "https://bsusc.bihar.gov.in"},
        {"department": "Bihar GAD", "type": "scrape", "url": "https://gad.bihar.gov.in"},
    ],

    "Madhya Pradesh": [
        {"department": "MPPSC", "type": "scrape", "url": "https://mppsc.mp.gov.in"},
        {"department": "MP ESB (Vyapam)", "type": "scrape", "url": "https://esb.mp.gov.in"},
        {"department": "MP Police", "type": "scrape", "url": "https://mppolice.gov.in"},
        {"department": "MPBSE (MP Board)", "type": "scrape", "url": "https://mpbse.nic.in"},
        {"department": "MP Higher Education", "type": "scrape", "url": "https://www.highereducation.mp.gov.in"},
        {"department": "MP Health Dept", "type": "scrape", "url": "https://health.mp.gov.in"},
        {"department": "MP Technical Education", "type": "scrape", "url": "https://dte.mponline.gov.in"},
        {"department": "MPPMCL (Power)", "type": "scrape", "url": "https://www.mppmcl.com"},
    ],

    "Rajasthan": [
        {"department": "RPSC", "type": "scrape", "url": "https://rpsc.rajasthan.gov.in"},
        {"department": "RSMSSB", "type": "scrape", "url": "https://rsmssb.rajasthan.gov.in"},
        {"department": "Rajasthan Police", "type": "scrape", "url": "https://police.rajasthan.gov.in"},
        {"department": "RBSE (Rajasthan Board)", "type": "scrape", "url": "https://rajeduboard.rajasthan.gov.in"},
        {"department": "RUHS (Health University)", "type": "scrape", "url": "https://ruhsraj.org"},
        {"department": "Rajasthan High Court", "type": "scrape", "url": "https://hcraj.nic.in"},
        {"department": "Rajasthan Health Dept", "type": "scrape", "url": "https://sihfwrajasthan.com"},
    ],

    "Delhi": [
        {"department": "Delhi Police", "type": "scrape", "url": "https://delhipolice.gov.in/recruitments"},
        {"department": "Delhi Sachivalay (DSSSB)", "type": "scrape", "url": "https://dsssb.delhi.gov.in/recruitment"},
        {"department": "Delhi Employment Dept", "type": "scrape", "url": "https://employment.delhi.gov.in"},
        {"department": "Directorate of Education Delhi", "type": "scrape", "url": "https://edudel.nic.in"},
    ],

    "Haryana": [
        {"department": "HPSC (Haryana PSC)", "type": "scrape", "url": "https://hpsc.gov.in"},
        {"department": "HSSC (Haryana SSC)", "type": "scrape", "url": "https://hssc.gov.in"},
        {"department": "BSEH (Haryana Board)", "type": "scrape", "url": "https://bseh.org.in"},
        {"department": "HKRN (Haryana Kaushal Rozgar)", "type": "scrape", "url": "https://hkrnl.hry.gov.in"},
        {"department": "Haryana Police", "type": "scrape", "url": "https://haryanapolice.gov.in"},
    ],

    "Jharkhand": [
        {"department": "JPSC", "type": "scrape", "url": "https://jpsc.gov.in"},
        {"department": "JSSC", "type": "scrape", "url": "https://jssc.nic.in"},
        {"department": "JAC (Jharkhand Board)", "type": "scrape", "url": "https://jac.jharkhand.gov.in"},
        {"department": "Jharkhand Police", "type": "scrape", "url": "https://jharkhandpolice.gov.in"},
    ],

    "Chhattisgarh": [
        {"department": "CGPSC", "type": "scrape", "url": "https://psc.cg.gov.in"},
        {"department": "CG Vyapam", "type": "scrape", "url": "https://vyapam.cgstate.gov.in"},
        {"department": "CGBSE (CG Board)", "type": "scrape", "url": "https://cgbse.nic.in"},
        {"department": "Chhattisgarh Police", "type": "scrape", "url": "https://cgpolice.gov.in"},
    ],

    "Uttarakhand": [
        {"department": "UKPSC", "type": "scrape", "url": "https://psc.uk.gov.in"},
        {"department": "UKSSSC", "type": "scrape", "url": "https://sssc.uk.gov.in"},
        {"department": "UBSE (Uttarakhand Board)", "type": "scrape", "url": "https://ubse.uk.gov.in"},
        {"department": "UBTER (Tech Education)", "type": "scrape", "url": "https://ubter.in"},
        {"department": "Uttarakhand Police", "type": "scrape", "url": "https://uttarakhandpolice.uk.gov.in"},
    ],

    "Himachal Pradesh": [
        {"department": "HPPSC", "type": "scrape", "url": "https://hppsc.hp.gov.in"},
        {"department": "HPSSSB", "type": "scrape", "url": "http://hpsssb.hp.gov.in"},
        {"department": "HPBOSE (HP Board)", "type": "scrape", "url": "https://hpbose.org"},
        {"department": "HPTU (Technical University)", "type": "scrape", "url": "https://himtu.ac.in"},
    ],
}

GROUP_NAMES = list(SOURCE_GROUPS.keys())

ALLOWED_CATEGORIES = ["Notification", "Admit Card", "Result", "Answer Key"]

# ============ SURAKSHIT TAREEKA: Token/ID ab yahan nahi likha ============
# Yeh Railway ke "Variables" tab se (environment variable se) aayega.
# GitHub par is file mein ab koi bhi asli token/ID nahi dikhega.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print("[CHETAVANI] TELEGRAM_BOT_TOKEN ya TELEGRAM_CHAT_ID nahi mila! "
          "Railway ke 'Variables' tab mein jaakar dono add karein.")

CHECK_INTERVAL_MINUTES = 15
CLEANUP_AFTER_DAYS = 90
DATABASE_FILE = "posts.db"
