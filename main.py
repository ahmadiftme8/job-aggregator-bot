"""
================================================================================
  REMOTE JOB AGGREGATOR — SMART AI-SCORED EDITION
  main.py  v3.5 (Groq / Llama 4 Scout Extraction Edition)
================================================================================
"""

# ── Standard Library ──────────────────────────────────────────────────────────
import os, json, logging, base64, re, time, hashlib
from datetime import datetime, timezone, timedelta

# ── Third-Party ───────────────────────────────────────────────────────────────
import requests, feedparser
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from groq import Groq

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ==============================================================================
#  SECTION 1 — CONFIGURATION
# ==============================================================================

DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

# ── Credentials ───────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN            = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID              = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_API_URL              = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
GOOGLE_SHEET_ID               = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_SHEET_CREDENTIALS_JSON = os.getenv("GOOGLE_SHEET_CREDENTIALS_JSON")
SHEET_TAB_NAME                = "sent_jobs"

MAX_JOB_AGE_DAYS   = int(os.getenv("MAX_JOB_AGE_DAYS", "14"))
MIN_SCORE_TO_ALERT = int(os.getenv("MIN_SCORE_TO_ALERT", "6")) 

REQUEST_TIMEOUT = 20
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
}

# ==============================================================================
#  SECTION 2 — YOUR RESUME / SKILL PROFILE (Fed to the AI)
# ==============================================================================

MY_PROFILE = {
    "skills": [
        "React", "Next.js", "Tailwind CSS", "TypeScript", "AI Integration", "Web Development",
        "Graphic Design", "Branding", "Visual Identity", "Photoshop", "Illustrator"
    ],
    "target_roles": [
        "Frontend Developer", "Web Developer", "React Developer",
        "Graphic Designer", "Visual Designer", "Brand Designer"
    ],
    "goals": "Junior or Mid-level seeking remote gigs, contract work, or companies offering visa sponsorship/relocation to Europe. Strong at using AI for coding and building websites.",
    "hard_negatives": [
        "US residents only", "Must reside in US", "No visa sponsorship", "Senior Backend", "Data Scientist", "Pure UX Research"
    ]
}

# ==============================================================================
#  SECTION 3 — JOB SOURCES
# ==============================================================================

JOB_SOURCES = [
    {"name": "We Work Remotely – All", "type": "rss", "category": "mixed", "url": "https://weworkremotely.com/remote-jobs.rss"},
    {"name": "Remotive – Design", "type": "remotive_api", "category": "design", "url": "https://remotive.com/api/remote-jobs?category=design"},
    {"name": "Remote OK", "type": "remoteok_api", "category": "mixed", "url": "https://remoteok.com/api"},
    {"name": "Telegram - Webinar Farsi", "type": "telegram_html", "category": "mixed", "url": "https://t.me/s/webinar_farsi"},
    {"name": "Telegram - Jaabz", "type": "telegram_html", "category": "mixed", "url": "https://t.me/s/jaabz_com"},
    {"name": "Telegram - Jobs Finding", "type": "telegram_html", "category": "mixed", "url": "https://t.me/s/jobs_finding"},
    {"name": "Telegram - Get Job Offer", "type": "telegram_html", "category": "mixed", "url": "https://t.me/s/get_joboffer"},
    {"name": "Telegram - Relocats", "type": "telegram_html", "category": "europe", "url": "https://t.me/s/Relocats"},
    {"name": "Telegram - Remote Jobs", "type": "telegram_html", "category": "mixed", "url": "https://t.me/s/remotejobss"},
    {"name": "Telegram - Startup Finland", "type": "telegram_html", "category": "europe", "url": "https://t.me/s/StartupJobsInFinland"},
    {"name": "Telegram - RelocateMe", "type": "telegram_html", "category": "europe", "url": "https://t.me/s/relocateme"},
]

# ==============================================================================
#  SECTION 4 — SMART KEYWORD GATEKEEPER
# ==============================================================================

INCLUDE_TAG_GROUPS = [
    ["frontend"], ["react"], ["next.js"], ["vue"], ["web developer"],
    ["graphic design"], ["ui designer"], ["ux designer"], ["ui/ux"], ["product designer"],
    ["brand design"], ["figma"], ["designer", "remote"]
]

TITLE_BLACKLIST = ["head of ", "vp of ", "director of", "cto ", "data scientist", "machine learning", "backend", "java developer", "python developer"]
GEO_BLACKLIST   = ["us residents only", "must reside in us", "united states only", "no visa sponsorship"]

def _norm(val) -> str:
    if val is None: return ""
    if isinstance(val, list): return " ".join(str(v) for v in val).lower()
    return str(val).lower()

def is_relevant_job(job: dict) -> bool:
    title = _norm(job.get("title", ""))
    full  = title + " " + _norm(job.get("description","")) + " " + _norm(job.get("location",""))

    if any(kw.lower() in title for kw in TITLE_BLACKLIST): return False
    if any(kw.lower() in full for kw in GEO_BLACKLIST): return False

    passed_inclusion = False
    for group in INCLUDE_TAG_GROUPS:
        if all(_norm(t) in full for t in group):
            passed_inclusion = True
            break
            
    if not passed_inclusion: return False

    dt = job.get("posted_at")
    if dt:
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_JOB_AGE_DAYS)
        if dt.astimezone(timezone.utc) < cutoff: return False

    return True

# ==============================================================================
#  SECTION 5 — SMART SCORER (Powered by Groq)
# ==============================================================================

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)
else:
    log.warning("⚠ No GROQ_API_KEY found. AI scoring will be disabled.")
    groq_client = None

def ai_score_job(job: dict) -> tuple[int, list[str], str, list[str], dict]:
    if not groq_client:
        return 1, ["AI scoring disabled"], "No API Key", [], {"title": job.get("title"), "company": "Unknown", "location": "Remote", "visa": False, "salary": "Not listed"}

    title = job.get("title", "Unknown Role")
    desc = job.get("description", "")[:3000]

    prompt = f"""
    You are a ruthless, expert technical recruiter matching an unedited job post payload to a target candidate.
    
    CANDIDATE PROFILE:
    Target Roles: {', '.join(MY_PROFILE['target_roles'])}
    Core Skills: {', '.join(MY_PROFILE['skills'])}
    Career Goals: {MY_PROFILE['goals']}
    Absolute Dealbreakers: {', '.join(MY_PROFILE['hard_negatives'])}
    
    [HARD CONSTRAINTS & SCORING RUBRIC]
    1. Score 1-3: Requires wrong tech stack (Java, Android, Backend), requires Senior/Lead experience, or explicitly restricts to USA residents.
    2. Score 4-5: Partial match, but missing primary frontend/design text alignment or contains geographic eligibility hurdles.
    3. Score 6-10: Solid alignment with frontend/design tools, junior/mid-level, and offers verifiable international eligibility.
    4. EXTRACT clean metadata. If the payload title is an emoji like '📌' or says 'Hello everyone', dive into the text description to parse the actual job role, target employer name, and structural metadata details.
    5. The candidate is an Iranian national. Rate USA-restricted jobs as 1 unless explicitly stating international applicants are fine.
    
    JOB POSTING TO EVALUATE:
    Scraped Title: {title}
    Description/Text: {desc}
    
    Analyze the job data context against the candidate parameters.
    Return a JSON object with EXACTLY this structure:
    {{
        "extracted_title": "The true, normalized professional job title clean of emojis or channel codes",
        "extracted_company": "The company name (or 'Confidential' if unlisted)",
        "extracted_location": "Determined location window or 'Remote'",
        "extracted_salary": "Salary text parsed if available, otherwise 'Not listed'",
        "offers_visa_or_relocation": true or false,
        "score": (integer 1-10 based strictly on target rubric),
        "reasons": [(list of 2-3 short, punchy reasons prefixed without bullet shapes)],
        "verdict": "A clear, detailed 2-3 sentence analysis covering timezone compatibility, alignment with Next.js/React framework goals, or mobile-stack variations.",
        "hashtags": [(list of 3-5 relevant functional keywords without symbols)]
    }}
    """
    
    try:
        completion = groq_client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1, 
            max_completion_tokens=600
        )
        
        result = json.loads(completion.choices[0].message.content)
        
        score = int(result.get("score", 1))
        reasons = result.get("reasons", ["Analysis compiled."])
        verdict = result.get("verdict", "No additional context supplied.")
        hashtags = ["#" + tag.replace(" ", "") for tag in result.get("hashtags", ["JobAlert"])]
        
        clean_meta = {
            "title": result.get("extracted_title", title),
            "company": result.get("extracted_company", "Unknown"),
            "location": result.get("extracted_location", "Remote"),
            "salary": result.get("extracted_salary", "Not listed"),
            "visa": bool(result.get("offers_visa_or_relocation", False))
        }
        
        time.sleep(2.5) 
        return score, reasons, verdict, hashtags, clean_meta

    except Exception as e:
        log.error(f"  AI Scoring failed for {title}: {e}")
        time.sleep(3)
        fallback_meta = {"title": title, "company": "Unknown", "location": "Remote", "salary": "Not listed", "visa": False}
        return 1, ["AI processing failed."], "Error processing structural payload.", [], fallback_meta

# ==============================================================================
#  SECTION 6 — PARSERS
# ==============================================================================

def _safe_get(url, **kwargs):
    try:
        r = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT, **kwargs)
        r.raise_for_status()
        return r
    except requests.RequestException:
        return None

def _strip_html(raw: str) -> str:
    return BeautifulSoup(raw or "", "html.parser").get_text(separator=" ", strip=True)

def _make_id(url: str, title: str) -> str:
    if url and url.startswith("http"): return url
    return hashlib.md5((title or "").encode()).hexdigest()

def parse_rss(source: dict) -> list[dict]:
    jobs = []
    r = _safe_get(source["url"])
    if not r: return jobs
    feed = feedparser.parse(r.content)
    for e in feed.entries:
        try:
            jobs.append({
                "id": _make_id(e.get("link",""), e.get("title", "")),
                "title": e.get("title", "").strip(),
                "company": e.get("author", "Unknown"),
                "location": e.get("location", "Remote"),
                "apply_url": e.get("link", ""),
                "description": _strip_html((e.get("summary") or "")),
                "source": source["name"],
                "posted_at": None,
            })
        except Exception: continue
    return jobs

def parse_telegram(source: dict) -> list[dict]:
    jobs = []
    r = _safe_get(source["url"])
    if not r: return jobs
    soup = BeautifulSoup(r.text, "html.parser")
    
    for msg in soup.select(".tgme_widget_message"):
        try:
            text_el = msg.select_one(".tgme_widget_message_text")
            if not text_el: continue
            text = text_el.get_text(separator="\n", strip=True)
            
            date_el = msg.select_one(".tgme_widget_message_date")
            apply_url = date_el["href"] if date_el and date_el.has_attr("href") else source["url"]
            
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            title = lines[0][:80] if lines else "Telegram Job Post"
            
            jobs.append({
                "id": _make_id(apply_url, text),
                "title": title,
                "company": "See Telegram",
                "location": "See Telegram",
                "apply_url": apply_url,
                "description": text, 
                "source": source["name"],
                "posted_at": None,
            })
        except Exception: continue
    log.info(f"  → {len(jobs)} from {source['name']}")
    return jobs

_PARSERS = {
    "rss": parse_rss,
    "telegram_html": parse_telegram,
}

def fetch_all_jobs() -> list[dict]:
    all_jobs = []
    for source in JOB_SOURCES:
        parser = _PARSERS.get(source.get("type",""))
        if not parser: continue
        try:
            jobs = parser(source)
            all_jobs.extend(jobs)
        except Exception as e:
            log.error(f"Error fetching {source['name']}: {e}")
    return all_jobs

# ==============================================================================
#  SECTION 7 — TELEGRAM NOTIFICATION (With Inline Buttons!)
# ==============================================================================

def _esc(text) -> str:
    special = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(special)}])", r"\\\1", str(text or "N/A"))

def send_telegram(message: str, apply_url: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return False
    
    keyboard = []
    if apply_url and apply_url.startswith("http"):
        keyboard = [[
            {"text": "🚀 Apply Now", "url": apply_url},
            {"text": "👁 View Details", "url": apply_url}
        ]]
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
        "reply_markup": json.dumps({"inline_keyboard": keyboard}) if keyboard else None
    }
    
    try:
        r = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        return r.json().get("ok", False)
    except Exception: return False

def format_message(clean_meta: dict, score: int, reasons: list[str], verdict: str, hashtags: list[str]) -> str:
    visa_line = "✈️ *Visa sponsorship or relocation package*\n" if clean_meta.get("visa") else ""

    msg = (
        f"🔥 *HIGH MATCH JOB*\n"
        f"🎯 Match: *{score}/10*\n"
        f"💼 *{_esc(clean_meta.get('title'))}*\n"
        f"🏢 {_esc(clean_meta.get('company'))}\n"
        f"🌍 {_esc(clean_meta.get('location', 'Remote'))}\n"
        f"💰 {_esc(clean_meta.get('salary', 'Not listed'))}\n"
        f"{visa_line}\n"
        f"*Why it matches:*\n"
    )
    
    for r in reasons[:3]:
        msg += f"✏️ {_esc(r)}\n"
    
    msg += f"\n⚠️ *Check:* Timezone requirements\n\n"
    msg += f"🤖 *Verdict:*\n{_esc(verdict)}\n\n"
    msg += _esc("  ".join(hashtags))
    
    return msg

# ==============================================================================
#  SECTION 8 — GOOGLE SHEETS (Database)
# ==============================================================================

def _sheets_client():
    cred_b64 = GOOGLE_SHEET_CREDENTIALS_JSON
    if not cred_b64:
        log.warning("GOOGLE_SHEET_CREDENTIALS_JSON not set. Skipping Sheets backup.")
        return None
    try:
        cred_json = base64.b64decode(cred_b64).decode("utf-8")
        cred_dict = json.loads(cred_json)
        scopes    = ["https://spreadsheets.google.com/feeds",
                     "https://www.googleapis.com/auth/drive"]
        creds     = ServiceAccountCredentials.from_json_keyfile_dict(cred_dict, scopes)
        client    = gspread.authorize(creds)
        log.info("✅ Google Sheets authenticated.")
        return client
    except Exception as e:
        log.error(f"Sheets auth failed: {e}")
        return None

def get_worksheet(gc):
    try:
        ss = gc.open_by_key(GOOGLE_SHEET_ID)
        try:
            sheet = ss.worksheet(SHEET_TAB_NAME)
        except gspread.exceptions.WorksheetNotFound:
            sheet = ss.add_worksheet(title=SHEET_TAB_NAME, rows="2000", cols="5")
            sheet.append_row(["job_id", "job_title", "score", "source", "sent_at"])
        return sheet
    except Exception as e:
        log.error(f"Cannot open sheet: {e}")
        return None

def load_sent_ids(sheet) -> set:
    try:
        ids = sheet.col_values(1)
        log.info(f"📋 {len(ids)} previously-sent IDs loaded.")
        return set(ids)
    except Exception as e:
        log.error(f"Cannot read sheet: {e}")
        return set()

# ==============================================================================
#  SECTION 9 — MAIN PIPELINE
# ==============================================================================

def main():
    log.info("Starting AI-Powered Job Aggregator...")

    # 1. Google Sheets Setup
    gc = _sheets_client()
    sheet = get_worksheet(gc) if gc else None
    sent_ids = load_sent_ids(sheet) if sheet else set()

    # 2. Fetch raw jobs
    all_jobs = fetch_all_jobs()
    log.info(f"Fetched {len(all_jobs)} raw jobs.")

    # 3. Python Fast Filter
    relevant_jobs = [j for j in all_jobs if is_relevant_job(j)]
    log.info(f"Filtered down to {len(relevant_jobs)} jobs for AI analysis.")

    # 4. AI Scoring & Sending
    sent_count = 0
    for job in relevant_jobs:
        job_id = str(job.get("id", ""))
        if not job_id or job_id in sent_ids:
            continue

        score, reasons, verdict, hashtags, clean_meta = ai_score_job(job)

        if score >= MIN_SCORE_TO_ALERT:
            log.info(f"  🆕 [{score}/10] {clean_meta['title']}")
            message = format_message(clean_meta, score, reasons, verdict, hashtags)
            
            success = send_telegram(message, apply_url=job.get("apply_url", ""))

            # Save clean formatted elements to Google Sheets to keep database aligned
            if success and sheet:
                row_to_save = [
                    str(job_id),                                       
                    f"{clean_meta['title']} @ {clean_meta['company']}",      
                    str(score),                                        
                    str(job.get("source", "Unknown")),                 
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") 
                ]
                sheet.append_row(row_to_save)
                sent_ids.add(job_id)
            
            sent_count += 1

    log.info(f"Run complete. Sent {sent_count} alerts.")

if __name__ == "__main__":
    main()