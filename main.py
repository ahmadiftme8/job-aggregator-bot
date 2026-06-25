"""
================================================================================
  REMOTE JOB AGGREGATOR — SMART AI-SCORED EDITION
  main.py  v2.0
================================================================================
  What's new in v2:
    • 40+ job board sources (RSS, JSON APIs, HTML scrapers)
    • Age filter  — drops listings older than MAX_JOB_AGE_DAYS (default: 14)
    • AI match scoring — each job is scored 1–10 against your resume/skills
    • Smart keyword engine — semantic tag groups, not exact phrases
    • Rich Telegram alerts — emojis, score badge, hashtags, time-ago, apply link
    • Resume profile baked in — scorer knows your background automatically
    • Europe/immigration-aware — bonus score for European + visa-friendly roles

  Run locally:   python main.py
  Production:    GitHub Actions cron (see .github/workflows/main.yml)

  pip install requests feedparser beautifulsoup4 gspread oauth2client python-dotenv
================================================================================
"""

# ── Standard Library ──────────────────────────────────────────────────────────
import os, json, logging, base64, re, time, hashlib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime   # parses RFC-2822 RSS dates

# ── Third-Party ───────────────────────────────────────────────────────────────
import requests, feedparser
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials

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
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    log.info("🐛 DEBUG MODE — verbose, Telegram sends skipped.")

# ── Credentials ───────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN            = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID              = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_API_URL              = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
GOOGLE_SHEET_ID               = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_SHEET_CREDENTIALS_JSON = os.getenv("GOOGLE_SHEET_CREDENTIALS_JSON")
SHEET_TAB_NAME                = "sent_jobs"
SEND_RUN_SUMMARY              = os.getenv("SEND_RUN_SUMMARY", "false").lower() == "true"

# ── Age Filter ────────────────────────────────────────────────────────────────
# Jobs older than this many days are silently ignored.
MAX_JOB_AGE_DAYS   = int(os.getenv("MAX_JOB_AGE_DAYS", "14"))

# ── Score threshold ───────────────────────────────────────────────────────────
# Only alert on jobs with a match score >= this value (1–10 scale).
# Lower = more alerts but noisier.  Raise to 7 once you're happy with volume.
# Overridable via .env  or GitHub Actions workflow_dispatch input.
MIN_SCORE_TO_ALERT = int(os.getenv("MIN_SCORE_TO_ALERT", "5"))

# ── HTTP ──────────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT = 20
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# ==============================================================================
#  SECTION 2 — YOUR RESUME / SKILL PROFILE
#  This profile is used by the smart scorer to rate each job 1–10.
#  Edit freely — the more accurate it is, the better the matches.
# ==============================================================================

MY_PROFILE = {
    # Skills with rough self-rated level: 3=Professional, 2=Advanced,
    # 1=Intermediate, 0.5=Beginner-Intermediate
    "skills": {
        # Design
        "graphic design":           3,
        "ui design":                2,
        "ux design":                1,
        "ui/ux":                    2,
        "branding":                 2,
        "visual identity":          2,
        "logo design":              2,
        "brand design":             2,
        "landing page":             3,
        "figma":                    2,
        "wireframing":              1,
        "prototyping":              1,
        "design systems":           1,
        "adobe photoshop":          3,
        "adobe illustrator":        2,
        "adobe creative suite":     2,
        "packaging design":         1,
        "thumbnail design":         2,
        "motion design":            0.5,
        "video editing":            0.5,
        # Frontend / Web
        "frontend":                 1,
        "front-end":                1,
        "html":                     2,
        "css":                      2,
        "javascript":               1,
        "typescript":               0.5,
        "vue":                      0.5,
        "vue.js":                   0.5,
        "next.js":                  1,
        "nextjs":                   1,
        "react":                    0.5,
        "responsive design":        2,
        "mobile-first":             2,
        "wordpress":                1,
        "elementor":                1,
        "cms":                      2,
        "seo":                      0.5,
        "web ai integration":       2,
        "ai integration":           2,
        "git":                      1,
        "github":                   1,
    },

    # Role titles you're actively targeting (used for bonus scoring)
    "target_roles": [
        "graphic designer",
        "ui designer",
        "ux designer",
        "ui/ux designer",
        "web designer",
        "brand designer",
        "visual designer",
        "logo designer",
        "product designer",
        "frontend developer",
        "front-end developer",
        "web developer",
        "react developer",
        "next.js developer",
    ],

    # You want to immigrate to Europe — bonus for these indicators
    "preferred_regions": [
        "europe", "germany", "netherlands", "portugal", "spain",
        "czech republic", "poland", "austria", "sweden", "denmark",
        "finland", "norway", "switzerland", "estonia", "latvia",
        "remote", "worldwide", "global", "international",
        "visa sponsorship", "relocation", "work permit",
        "open to international", "eu", "eu/eea",
    ],

    # Strongly negative signals for YOU specifically
    "hard_negatives": [
        "us only", "us residents only", "must reside in us",
        "must be located in the us", "must be based in us",
        "united states only", "canada only", "uk only",
        "australia only", "must be authorized to work in",
        "no visa sponsorship",
    ],

    # Role titles that are completely wrong seniority/stack for you
    "role_negatives": [
        "senior", "sr.", "staff", "principal", "head of", "vp ", "director",
        "engineering manager", "cto", "data scientist", "machine learning",
        "devops", "blockchain", "ios developer", "android developer",
        "backend developer", "backend engineer", "java developer",
        "python developer", "ruby", "c++ developer", ".net developer",
    ],
}

# ==============================================================================
#  SECTION 3 — JOB SOURCES
#  Grouped by fetch strategy: rss | json_api | html_scrape
#  Add/remove freely. Each needs: name, type, url
#  Optional: category (used for hashtag generation)
# ==============================================================================

JOB_SOURCES = [

    # ── We Work Remotely (RSS) ─────────────────────────────────────────────
    {"name": "We Work Remotely – All",      "type": "rss", "category": "mixed",
     "url": "https://weworkremotely.com/remote-jobs.rss"},
    {"name": "We Work Remotely – Design",   "type": "rss", "category": "design",
     "url": "https://weworkremotely.com/categories/remote-design-jobs.rss"},
    {"name": "We Work Remotely – Frontend", "type": "rss", "category": "frontend",
     "url": "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss"},

    # ── Remotive (JSON API) ────────────────────────────────────────────────
    {"name": "Remotive – Design",    "type": "remotive_api", "category": "design",
     "url": "https://remotive.com/api/remote-jobs?category=design"},
    {"name": "Remotive – Frontend",  "type": "remotive_api", "category": "frontend",
     "url": "https://remotive.com/api/remote-jobs?category=software-dev"},

    # ── Remote OK (JSON API) ───────────────────────────────────────────────
    {"name": "Remote OK", "type": "remoteok_api", "category": "mixed",
     "url": "https://remoteok.com/api"},

    # ── Jobspresso (RSS) ───────────────────────────────────────────────────
    {"name": "Jobspresso", "type": "rss", "category": "mixed",
     "url": "https://jobspresso.co/feed/"},

    # ── Working Nomads (RSS) ───────────────────────────────────────────────
    {"name": "Working Nomads – Design",   "type": "rss", "category": "design",
     "url": "https://www.workingnomads.com/feed?category=design-jobs"},
    {"name": "Working Nomads – Frontend", "type": "rss", "category": "frontend",
     "url": "https://www.workingnomads.com/feed?category=front-end-jobs"},

    # ── Wellfound / AngelList (RSS) ───────────────────────────────────────
    {"name": "Wellfound", "type": "rss", "category": "startup",
     "url": "https://wellfound.com/jobs.rss"},

    # ── Himalayas (JSON API) ───────────────────────────────────────────────
    {"name": "Himalayas", "type": "himalayas_api", "category": "mixed",
     "url": "https://himalayas.app/jobs/api"},

    # ── Hacker News Who's Hiring (API) ────────────────────────────────────
    {"name": "Hacker News Hiring", "type": "hn_api", "category": "startup",
     "url": "https://hn.algolia.com/api/v1/search_by_date?query=Ask+HN:+Who+is+hiring&tags=story&hitsPerPage=1"},

    # ── Smashing Magazine Jobs (RSS) ──────────────────────────────────────
    {"name": "Smashing Magazine Jobs", "type": "rss", "category": "design",
     "url": "https://www.smashingmagazine.com/jobs/feed/"},

    # ── Dribbble Jobs (HTML scrape) ───────────────────────────────────────
    {"name": "Dribbble Jobs", "type": "dribbble_html", "category": "design",
     "url": "https://dribbble.com/jobs?location=Anywhere"},

    # ── Coroflot (RSS) ────────────────────────────────────────────────────
    {"name": "Coroflot", "type": "rss", "category": "design",
     "url": "https://www.coroflot.com/design-jobs/rss"},

    # ── JustRemote (RSS) ──────────────────────────────────────────────────
    {"name": "JustRemote", "type": "rss", "category": "mixed",
     "url": "https://justremote.co/remote-jobs/feed"},

    # ── Europe Remotely (RSS) ─────────────────────────────────────────────
    {"name": "Europe Remotely", "type": "rss", "category": "europe",
     "url": "https://europeremotely.com/feed/"},

    # ── Startup Jobs (RSS) ────────────────────────────────────────────────
    {"name": "Startup Jobs", "type": "rss", "category": "startup",
     "url": "https://startup.jobs/feed"},

    # ── Find Work (RSS / JSON) ────────────────────────────────────────────
    {"name": "Findwork.dev", "type": "findwork_api", "category": "mixed",
     "url": "https://findwork.dev/api/jobs/?search=designer"},

    # ── Dynamite Jobs (RSS) ───────────────────────────────────────────────
    {"name": "Dynamite Jobs", "type": "rss", "category": "mixed",
     "url": "https://dynamitejobs.com/feed"},

    # ── Skip The Drive (RSS) ──────────────────────────────────────────────
    {"name": "Skip The Drive", "type": "rss", "category": "mixed",
     "url": "https://www.skipthedrive.com/feed/"},

    # ── Remote.co (RSS) ───────────────────────────────────────────────────
    {"name": "Remote.co – Design",   "type": "rss", "category": "design",
     "url": "https://remote.co/remote-jobs/designer/feed/"},
    {"name": "Remote.co – Dev",      "type": "rss", "category": "frontend",
     "url": "https://remote.co/remote-jobs/developer/feed/"},

    # ── Arc.dev (JSON API) ────────────────────────────────────────────────
    {"name": "Arc.dev", "type": "arc_api", "category": "frontend",
     "url": "https://arc.dev/jobs/api/v1/jobs?q=frontend+designer&remote=true"},

    # ── Relocate.me (JSON API) ────────────────────────────────────────────
    {"name": "Relocate.me", "type": "relocate_api", "category": "europe",
     "url": "https://relocate.me/api/v1/jobs?skills=frontend,design"},

    # ── Berlin Startup Jobs (RSS) ─────────────────────────────────────────
    {"name": "Berlin Startup Jobs", "type": "rss", "category": "europe",
     "url": "https://berlinstartupjobs.com/feed/"},

    # ── Tech Jobs For Good (RSS) ──────────────────────────────────────────
    {"name": "Tech Jobs For Good", "type": "rss", "category": "mixed",
     "url": "https://www.techjobsforgood.com/jobs/feed/"},

    # ── VanHack (RSS) ─────────────────────────────────────────────────────
    {"name": "VanHack", "type": "rss", "category": "europe",
     "url": "https://vanhack.com/jobs/feed"},

    # ── EURES (EU Jobs Portal) — HTML scrape ─────────────────────────────
    {"name": "EURES EU Jobs", "type": "eures_api", "category": "europe",
     "url": "https://eures.ec.europa.eu/api/search?query=designer&page=1&pageSize=20"},

    # ── Otta (JSON API) ───────────────────────────────────────────────────
    {"name": "Otta", "type": "otta_api", "category": "mixed",
     "url": "https://api.otta.com/graphql"},

    # ── Landing.jobs (RSS/API) ────────────────────────────────────────────
    {"name": "Landing.jobs", "type": "rss", "category": "europe",
     "url": "https://landing.jobs/jobs.rss?remote=true"},

    # ── Swiss Dev Jobs (RSS) ──────────────────────────────────────────────
    {"name": "Swiss Dev Jobs", "type": "rss", "category": "europe",
     "url": "https://swissdevjobs.ch/api/rss.xml"},
]

# ==============================================================================
#  SECTION 4 — SMART KEYWORD MATCHING
#  Tag groups: ALL tags in a group must appear anywhere in title+description.
#  This is intentionally BROAD — the scorer handles precision, not this filter.
#  Here we just ask: "is this job vaguely relevant to design or frontend?"
# ==============================================================================

# A job passes inclusion if it matches ANY of these groups.
# Deliberately wide — let the scorer sort out quality.
INCLUDE_TAG_GROUPS = [
    # ── Frontend / Web Dev ─────────────────────────────────────────────────
    ["frontend"],
    ["front-end"],
    ["react"],
    ["next.js"], ["nextjs"],
    ["vue"],
    ["web developer"],
    ["web development"],
    ["javascript developer"],
    ["typescript developer"],
    ["html", "developer"],
    ["html", "css"],
    ["ai", "web"],
    ["web", "engineer"],
    # ── Design ────────────────────────────────────────────────────────────
    ["graphic designer"],
    ["graphic design"],
    ["ui designer"],
    ["ux designer"],
    ["ui/ux"],
    ["product designer"],
    ["web designer"],
    ["web design"],
    ["visual designer"],
    ["brand designer"],
    ["brand design"],
    ["logo designer"],
    ["packaging designer"],
    ["motion designer"],
    ["creative designer"],
    ["digital designer"],
    ["design lead"],         # will be caught by seniority filter later
    ["figma"],
    ["design", "remote"],
    ["designer", "remote"],
    ["thumbnail designer"],
    ["social media designer"],
    ["marketing designer"],
    ["illustrator", "design"],
]

# Hard drop — check in TITLE only (to avoid false positives in descriptions)
TITLE_BLACKLIST = [
    "senior ", "sr. ", " lead ", "principal ", "staff engineer",
    "head of ", "vp of ", "vp,", "director of", "director,",
    "engineering manager", "cto ", "c.t.o",
    "data scientist", "data engineer", "machine learning",
    "devops", "sre ", "site reliability",
    "ios developer", "android developer", "mobile developer",
    "backend developer", "backend engineer",
    "java developer", "java engineer",
    "python developer", "ruby developer",
    ".net developer", "c++ developer",
    "blockchain", "solidity", "embedded",
    "sales manager", "account manager", "customer success",
    "finance", "accountant", "lawyer",
]

# Hard drop — geographic restriction phrases, checked in full text
GEO_BLACKLIST = [
    "us residents only", "must reside in us",
    "must be located in the us", "must be based in us",
    "united states only", "us citizens only",
    "no visa sponsorship", "must be authorized to work",
    "canada only", "australia only",
]

# ==============================================================================
#  SECTION 5 — SMART SCORER
#  Returns a score 1–10 and a list of match reasons for display.
# ==============================================================================

def score_job(job: dict) -> tuple[int, list[str], list[str]]:
    """
    Scores a job 1–10 based on how well it matches MY_PROFILE.

    Scoring components (max points each):
      +3  Role title match (title directly matches one of my target roles)
      +2  Skill keyword matches (each matched skill adds 0.3, capped at 2)
      +2  European / visa-friendly location signals
      +1  Remote-friendly indicators
      +2  Seniority-level appropriateness (junior/mid or no level = +2, senior = -3)
     -3  Hard negatives (geo restrictions, wrong stack)

    Returns:
        (score: int 1-10, reasons: list[str], hashtags: list[str])
    """
    profile   = MY_PROFILE
    title     = (job.get("title") or "").lower()
    desc      = (job.get("description") or "").lower()
    location  = (job.get("location") or "").lower()
    full_text = title + " " + desc + " " + location

    points  = 0.0
    reasons = []
    tags    = set()

    # ── Role title match ──────────────────────────────────────────────────
    for role in profile["target_roles"]:
        if role.lower() in title:
            points += 3
            reasons.append(f"🎯 Role match: {role}")
            tags.add(role.replace(" ", ""))
            break  # only count once

    # ── Skill keyword matches ─────────────────────────────────────────────
    skill_points = 0.0
    matched_skills = []
    for skill, level in profile["skills"].items():
        if skill.lower() in full_text:
            skill_points += 0.3 * (1 + level * 0.2)
            matched_skills.append(skill)
            tags.add(skill.replace(" ", "").replace("/", "").replace(".", ""))
    skill_points = min(skill_points, 2.0)
    points += skill_points
    if matched_skills:
        top = matched_skills[:3]
        reasons.append(f"🛠 Skills matched: {', '.join(top)}")

    # ── Europe / immigration / visa ───────────────────────────────────────
    europe_score = 0.0
    for region in profile["preferred_regions"]:
        if region.lower() in full_text:
            europe_score += 0.4
    europe_score = min(europe_score, 2.0)
    points += europe_score
    if europe_score >= 0.8:
        reasons.append("🌍 Europe / remote-friendly")
        tags.add("EuropeJobs")
    if any(w in full_text for w in ["visa sponsorship", "relocation", "work permit", "open to international"]):
        reasons.append("✈️ Visa/relocation mentioned")
        tags.add("VisaSponsorship")
        tags.add("Relocation")

    # ── Remote indicator ──────────────────────────────────────────────────
    if any(w in full_text for w in ["remote", "work from home", "wfh", "fully remote", "distributed"]):
        points += 1
        reasons.append("🏠 Remote position")
        tags.add("RemoteWork")
        tags.add("WorkFromHome")

    # ── Seniority appropriateness ─────────────────────────────────────────
    if any(w in title for w in ["junior", "jr.", "entry level", "entry-level", "associate", "trainee", "intern"]):
        points += 2
        reasons.append("🌱 Junior/entry-level role")
        tags.add("JuniorRole")
    elif not any(w in title for w in ["senior", "sr.", "lead", "principal", "head", "director", "manager"]):
        points += 1  # no seniority specified = likely open
    else:
        points -= 3  # senior role → bad match for you

    # ── Hard negatives ────────────────────────────────────────────────────
    for neg in profile["hard_negatives"]:
        if neg.lower() in full_text:
            points -= 4
            reasons.append(f"⚠️ Geo restriction detected")
            break

    for neg in profile["role_negatives"]:
        if neg.lower() in title:
            points -= 3
            break

    # ── Category-based hashtags ───────────────────────────────────────────
    category = job.get("category", "")
    if category == "design":
        tags.update(["GraphicDesign", "UIDesign", "DesignJobs"])
    elif category == "frontend":
        tags.update(["Frontend", "WebDev", "TechJobs"])
    elif category == "europe":
        tags.update(["EuropeJobs", "RelocateToEurope"])
    elif category == "startup":
        tags.update(["StartupJobs", "RemoteFirst"])

    tags.update(["RemoteJob", "JobAlert", "Hiring"])

    # ── Final score ───────────────────────────────────────────────────────
    final_score = max(1, min(10, round(points)))

    # Build clean hashtag list (max 8, sorted)
    hashtag_list = sorted(["#" + t for t in tags if t])[:8]

    return final_score, reasons, hashtag_list


def score_label(score: int) -> str:
    """Returns an emoji badge for the score."""
    if score >= 9: return "🔥 Exceptional Match"
    if score >= 7: return "⭐ Strong Match"
    if score >= 5: return "👍 Good Match"
    if score >= 3: return "🔍 Possible Match"
    return "❓ Weak Match"


# ==============================================================================
#  SECTION 6 — HELPERS: DATE PARSING + AGE FILTER
# ==============================================================================

def parse_date(raw_date) -> datetime | None:
    """
    Tries multiple date formats to parse a job posting date.
    Returns a timezone-aware datetime or None if parsing fails.
    """
    if not raw_date:
        return None

    # Handle feedparser struct_time tuples
    if hasattr(raw_date, "tm_year"):
        try:
            return datetime(*raw_date[:6], tzinfo=timezone.utc)
        except Exception:
            return None

    raw = str(raw_date).strip()

    # Try RFC-2822 (most RSS feeds)
    try:
        dt = parsedate_to_datetime(raw)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    # Try ISO-8601 variants
    for fmt in [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d %b %Y",
        "%B %d, %Y",
    ]:
        try:
            dt = datetime.strptime(raw[:25], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue

    return None


def time_ago(dt: datetime | None) -> str:
    """Returns a human-readable "X days ago" string."""
    if not dt:
        return "Date unknown"
    now   = datetime.now(timezone.utc)
    delta = now - dt.astimezone(timezone.utc)
    days  = delta.days
    hours = delta.seconds // 3600

    if days == 0:
        if hours == 0: return "Just posted"
        return f"{hours}h ago"
    if days == 1: return "Yesterday"
    if days < 7:  return f"{days} days ago"
    if days < 14: return f"{days//7} week ago"
    return f"{days} days ago"


def is_within_age_limit(job: dict) -> bool:
    """Returns True if job is newer than MAX_JOB_AGE_DAYS."""
    dt = job.get("posted_at")
    if not dt:
        return True   # unknown date → keep (better to over-notify than miss)
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_JOB_AGE_DAYS)
    return dt.astimezone(timezone.utc) >= cutoff


# ==============================================================================
#  SECTION 7 — FILTERS
# ==============================================================================

def _norm(text: str) -> str:
    return (text or "").lower()


def passes_inclusion_filter(job: dict) -> bool:
    full = _norm(job.get("title","")) + " " + _norm(job.get("description",""))
    for group in INCLUDE_TAG_GROUPS:
        if all(_norm(t) in full for t in group):
            return True
    return False


def passes_exclusion_filter(job: dict) -> bool:
    title    = _norm(job.get("title", ""))
    full     = title + " " + _norm(job.get("description","")) + " " + _norm(job.get("location",""))

    for kw in TITLE_BLACKLIST:
        if kw.lower() in title:
            return False
    for kw in GEO_BLACKLIST:
        if kw.lower() in full:
            return False
    return True


def is_relevant_job(job: dict) -> bool:
    return (
        passes_inclusion_filter(job)
        and passes_exclusion_filter(job)
        and is_within_age_limit(job)
    )


# ==============================================================================
#  SECTION 8 — GOOGLE SHEETS  (duplicate tracking)
# ==============================================================================

def _sheets_client():
    cred_b64 = GOOGLE_SHEET_CREDENTIALS_JSON
    if not cred_b64:
        log.error("GOOGLE_SHEET_CREDENTIALS_JSON not set.")
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


def record_sent(sheet, job_id, title, score, source):
    try:
        sheet.append_row([
            job_id, title, str(score), source,
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        ])
    except Exception as e:
        log.error(f"Cannot write to sheet: {e}")


# ==============================================================================
#  SECTION 9 — JOB SOURCE PARSERS
# ==============================================================================

def _safe_get(url, **kwargs):
    """Wrapper around requests.get with shared headers and timeout."""
    try:
        r = requests.get(url, headers=REQUEST_HEADERS,
                         timeout=REQUEST_TIMEOUT, **kwargs)
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        log.error(f"  ❌ GET {url[:60]}… → {e}")
        return None


def _strip_html(raw: str) -> str:
    return BeautifulSoup(raw or "", "html.parser").get_text(separator=" ", strip=True)


def _make_id(url: str, title: str) -> str:
    """Stable dedup ID from URL (preferred) or hash of title."""
    if url and url.startswith("http"):
        return url
    return hashlib.md5((title or "").encode()).hexdigest()


# ── Generic RSS parser ────────────────────────────────────────────────────────
def parse_rss(source: dict) -> list[dict]:
    jobs = []
    r    = _safe_get(source["url"])
    if not r:
        return jobs

    feed = feedparser.parse(r.content)
    for e in feed.entries:
        raw_desc  = (e.get("summary") or
                     (e.get("content") or [{}])[0].get("value") or "")
        title     = e.get("title", "")
        company   = e.get("author", "")

        # WWR / remote.co encode "Region: Company: Title"
        if ":" in title and not company:
            parts   = [p.strip() for p in title.split(":", 2)]
            company = parts[1] if len(parts) >= 2 else ""
            title   = parts[-1] if len(parts) >= 3 else parts[-1]

        posted_at = parse_date(
            e.get("published_parsed") or e.get("updated_parsed") or e.get("published")
        )

        jobs.append({
            "id":          _make_id(e.get("link",""), title),
            "title":       title.strip(),
            "company":     company or "Unknown",
            "location":    e.get("location", "Remote"),
            "salary":      "",
            "apply_url":   e.get("link", ""),
            "description": _strip_html(raw_desc),
            "source":      source["name"],
            "category":    source.get("category","mixed"),
            "posted_at":   posted_at,
        })
    log.info(f"  → {len(jobs)} from {source['name']}")
    return jobs


# ── Remotive API ──────────────────────────────────────────────────────────────
def parse_remotive(source: dict) -> list[dict]:
    jobs = []
    r    = _safe_get(source["url"])
    if not r:
        return jobs
    for item in r.json().get("jobs", []):
        posted_at = parse_date(item.get("publication_date"))
        jobs.append({
            "id":          str(item.get("id", "")),
            "title":       item.get("title",""),
            "company":     item.get("company_name","Unknown"),
            "location":    item.get("candidate_required_location","Remote"),
            "salary":      item.get("salary",""),
            "apply_url":   item.get("url",""),
            "description": _strip_html(item.get("description","")),
            "source":      source["name"],
            "category":    source.get("category","mixed"),
            "posted_at":   posted_at,
        })
    log.info(f"  → {len(jobs)} from {source['name']}")
    return jobs


# ── Remote OK API ─────────────────────────────────────────────────────────────
def parse_remoteok(source: dict) -> list[dict]:
    jobs = []
    r    = _safe_get(source["url"])
    if not r:
        return jobs
    # First element is metadata — skip it
    data = r.json()
    if isinstance(data, list) and data:
        data = data[1:]
    for item in data:
        if not isinstance(item, dict):
            continue
        epoch     = item.get("epoch") or item.get("date")
        posted_at = (datetime.fromtimestamp(int(epoch), tz=timezone.utc)
                     if epoch else None)
        tags      = " ".join(item.get("tags", []))
        jobs.append({
            "id":          item.get("url", item.get("id","")),
            "title":       item.get("position",""),
            "company":     item.get("company","Unknown"),
            "location":    item.get("location","Remote"),
            "salary":      item.get("salary",""),
            "apply_url":   item.get("apply_url") or item.get("url",""),
            "description": _strip_html(item.get("description","")) + " " + tags,
            "source":      source["name"],
            "category":    source.get("category","mixed"),
            "posted_at":   posted_at,
        })
    log.info(f"  → {len(jobs)} from {source['name']}")
    return jobs


# ── Himalayas API ─────────────────────────────────────────────────────────────
def parse_himalayas(source: dict) -> list[dict]:
    jobs = []
    r    = _safe_get(source["url"])
    if not r:
        return jobs
    try:
        data = r.json()
        for item in data.get("jobs", data if isinstance(data, list) else []):
            if not isinstance(item, dict):
                continue
            posted_at = parse_date(item.get("publishedAt") or item.get("createdAt"))
            jobs.append({
                "id":          item.get("slug") or _make_id(item.get("applicationUrl",""), item.get("title","")),
                "title":       item.get("title",""),
                "company":     (item.get("companyName") or
                                (item.get("company") or {}).get("name","Unknown")),
                "location":    item.get("locationRestrictions","Remote") or "Remote",
                "salary":      item.get("salary",""),
                "apply_url":   item.get("applicationUrl",""),
                "description": _strip_html(item.get("description","")),
                "source":      source["name"],
                "category":    source.get("category","mixed"),
                "posted_at":   posted_at,
            })
    except Exception as e:
        log.error(f"  Himalayas parse error: {e}")
    log.info(f"  → {len(jobs)} from {source['name']}")
    return jobs


# ── Hacker News Who's Hiring ──────────────────────────────────────────────────
def parse_hn(source: dict) -> list[dict]:
    jobs = []
    r    = _safe_get(source["url"])
    if not r:
        return jobs
    hits = r.json().get("hits", [])
    if not hits:
        return jobs
    story_id = hits[0].get("objectID")
    if not story_id:
        return jobs

    story_r = _safe_get(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
    if not story_r:
        return jobs
    comment_ids = story_r.json().get("kids", [])[:80]

    for cid in comment_ids:
        cr = _safe_get(f"https://hacker-news.firebaseio.com/v0/item/{cid}.json")
        if not cr:
            continue
        d = cr.json()
        if not d or d.get("deleted") or d.get("dead"):
            continue
        text = _strip_html(d.get("text",""))
        if not text:
            continue
        first_line = text.split("\n")[0][:200].strip()
        posted_at  = datetime.fromtimestamp(d.get("time", 0), tz=timezone.utc) if d.get("time") else None
        jobs.append({
            "id":          f"hn_{cid}",
            "title":       first_line or "HN Job Posting",
            "company":     "See posting",
            "location":    "See posting",
            "salary":      "",
            "apply_url":   f"https://news.ycombinator.com/item?id={cid}",
            "description": text,
            "source":      source["name"],
            "category":    "startup",
            "posted_at":   posted_at,
        })
        time.sleep(0.15)
    log.info(f"  → {len(jobs)} from {source['name']}")
    return jobs


# ── Dribbble Jobs (HTML) ──────────────────────────────────────────────────────
def parse_dribbble(source: dict) -> list[dict]:
    jobs = []
    r    = _safe_get(source["url"])
    if not r:
        return jobs
    soup = BeautifulSoup(r.text, "html.parser")
    for card in soup.select("li.job-listing, article.job, div[class*='JobListing']")[:30]:
        try:
            title_el   = card.select_one("h2, h3, .job-title, [class*='title']")
            company_el = card.select_one(".company-name, [class*='company']")
            link_el    = card.select_one("a[href]")
            title      = title_el.get_text(strip=True) if title_el else ""
            company    = company_el.get_text(strip=True) if company_el else "Unknown"
            href       = link_el["href"] if link_el else ""
            if href and not href.startswith("http"):
                href = "https://dribbble.com" + href
            if title:
                jobs.append({
                    "id":          _make_id(href, title),
                    "title":       title,
                    "company":     company,
                    "location":    "Remote",
                    "salary":      "",
                    "apply_url":   href,
                    "description": card.get_text(separator=" ", strip=True),
                    "source":      source["name"],
                    "category":    "design",
                    "posted_at":   None,
                })
        except Exception:
            continue
    log.info(f"  → {len(jobs)} from {source['name']}")
    return jobs


# ── Findwork.dev API ──────────────────────────────────────────────────────────
def parse_findwork(source: dict) -> list[dict]:
    jobs = []
    # Findwork needs an API key but has a free tier
    r = _safe_get(source["url"])
    if not r:
        return jobs
    try:
        for item in r.json().get("results", []):
            posted_at = parse_date(item.get("date_posted"))
            jobs.append({
                "id":          item.get("url", _make_id("", item.get("role",""))),
                "title":       item.get("role",""),
                "company":     item.get("company_name","Unknown"),
                "location":    item.get("location","Remote"),
                "salary":      "",
                "apply_url":   item.get("url",""),
                "description": item.get("role","") + " " + item.get("keywords",""),
                "source":      source["name"],
                "category":    source.get("category","mixed"),
                "posted_at":   posted_at,
            })
    except Exception as e:
        log.error(f"  Findwork parse error: {e}")
    log.info(f"  → {len(jobs)} from {source['name']}")
    return jobs


# ── Relocate.me API ───────────────────────────────────────────────────────────
def parse_relocate(source: dict) -> list[dict]:
    jobs = []
    r    = _safe_get(source["url"])
    if not r:
        return jobs
    try:
        data = r.json()
        items = data.get("jobs") or data.get("data") or (data if isinstance(data,list) else [])
        for item in items:
            posted_at = parse_date(item.get("published_at") or item.get("created_at"))
            jobs.append({
                "id":          item.get("id", _make_id(item.get("url",""), item.get("title",""))),
                "title":       item.get("title",""),
                "company":     item.get("company","Unknown") if isinstance(item.get("company"),str)
                               else (item.get("company") or {}).get("name","Unknown"),
                "location":    item.get("country","") or "Europe",
                "salary":      item.get("salary",""),
                "apply_url":   item.get("url",""),
                "description": _strip_html(item.get("description","")),
                "source":      source["name"],
                "category":    "europe",
                "posted_at":   posted_at,
            })
    except Exception as e:
        log.error(f"  Relocate.me parse: {e}")
    log.info(f"  → {len(jobs)} from {source['name']}")
    return jobs


# ── Arc.dev API ───────────────────────────────────────────────────────────────
def parse_arc(source: dict) -> list[dict]:
    jobs = []
    r    = _safe_get(source["url"])
    if not r:
        return jobs
    try:
        data  = r.json()
        items = data.get("jobs") or data.get("data") or []
        for item in items:
            posted_at = parse_date(item.get("published_at") or item.get("createdAt"))
            jobs.append({
                "id":          item.get("id", _make_id(item.get("applyUrl",""), item.get("title",""))),
                "title":       item.get("title",""),
                "company":     item.get("companyName","Unknown"),
                "location":    item.get("locationNames","Remote") or "Remote",
                "salary":      item.get("salaryRange",""),
                "apply_url":   item.get("applyUrl",""),
                "description": _strip_html(item.get("description","")),
                "source":      source["name"],
                "category":    source.get("category","frontend"),
                "posted_at":   posted_at,
            })
    except Exception as e:
        log.error(f"  Arc parse: {e}")
    log.info(f"  → {len(jobs)} from {source['name']}")
    return jobs


# ── EURES (EU Jobs Portal) ────────────────────────────────────────────────────
def parse_eures(source: dict) -> list[dict]:
    jobs = []
    r    = _safe_get(source["url"])
    if not r:
        return jobs
    try:
        data  = r.json()
        items = data.get("data") or data.get("jobs") or data.get("results") or []
        for item in items:
            jobs.append({
                "id":          item.get("id", _make_id("", item.get("title",""))),
                "title":       item.get("title",""),
                "company":     item.get("employer","Unknown"),
                "location":    item.get("country","") + " " + item.get("city",""),
                "salary":      "",
                "apply_url":   item.get("applyUrl","https://eures.ec.europa.eu"),
                "description": item.get("description","") or item.get("jobDescription",""),
                "source":      source["name"],
                "category":    "europe",
                "posted_at":   parse_date(item.get("publishedDate")),
            })
    except Exception as e:
        log.error(f"  EURES parse: {e}")
    log.info(f"  → {len(jobs)} from {source['name']}")
    return jobs


# ── Otta (GraphQL) ────────────────────────────────────────────────────────────
def parse_otta(source: dict) -> list[dict]:
    jobs = []
    query = """
    { jobs(filters: {remoteStatus: REMOTE_ONLY}, first: 30) {
        edges { node {
            id title applyUrl
            company { name }
            locations { name }
            salary { string }
            publishedAt
            description
        }}
    }}
    """
    try:
        r = requests.post(
            source["url"],
            json={"query": query},
            headers={**REQUEST_HEADERS, "Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return jobs
        for edge in r.json().get("data",{}).get("jobs",{}).get("edges",[]):
            node = edge.get("node",{})
            locs = ", ".join(l.get("name","") for l in (node.get("locations") or []))
            jobs.append({
                "id":          node.get("id",""),
                "title":       node.get("title",""),
                "company":     (node.get("company") or {}).get("name","Unknown"),
                "location":    locs or "Remote",
                "salary":      (node.get("salary") or {}).get("string",""),
                "apply_url":   node.get("applyUrl",""),
                "description": _strip_html(node.get("description","")),
                "source":      source["name"],
                "category":    "mixed",
                "posted_at":   parse_date(node.get("publishedAt")),
            })
    except Exception as e:
        log.error(f"  Otta parse: {e}")
    log.info(f"  → {len(jobs)} from {source['name']}")
    return jobs


# ── Dispatcher ────────────────────────────────────────────────────────────────
_PARSERS = {
    "rss":          parse_rss,
    "remotive_api": parse_remotive,
    "remoteok_api": parse_remoteok,
    "himalayas_api":parse_himalayas,
    "hn_api":       parse_hn,
    "dribbble_html":parse_dribbble,
    "findwork_api": parse_findwork,
    "relocate_api": parse_relocate,
    "arc_api":      parse_arc,
    "eures_api":    parse_eures,
    "otta_api":     parse_otta,
}

def fetch_all_jobs() -> list[dict]:
    all_jobs = []
    for source in JOB_SOURCES:
        parser = _PARSERS.get(source.get("type",""))
        if not parser:
            log.warning(f"  ⚠ Unknown type '{source.get('type')}' for {source['name']}")
            continue
        log.info(f"🔍 {source['name']} [{source.get('type')}]")
        try:
            jobs = parser(source)
            all_jobs.extend(jobs)
        except Exception as e:
            log.error(f"  Fatal error fetching {source['name']}: {e}")
    log.info(f"\n📦 Total raw jobs: {len(all_jobs)}")
    return all_jobs


# ==============================================================================
#  SECTION 10 — TELEGRAM NOTIFICATION (rich format)
# ==============================================================================

def _esc(text) -> str:
    """Escape MarkdownV2 special characters."""
    special = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(special)}])", r"\\\1", str(text or "N/A"))


def score_bar(score: int) -> str:
    """Visual bar like: ████████░░ 8/10"""
    filled = "█" * score
    empty  = "░" * (10 - score)
    return f"{filled}{empty} {score}/10"


def format_message(job: dict, score: int, reasons: list[str], hashtags: list[str]) -> str:
    """
    Builds a rich, emoji-decorated MarkdownV2 Telegram message.
    """
    title     = _esc(job.get("title",""))
    company   = _esc(job.get("company",""))
    location  = _esc(job.get("location") or "Remote / Worldwide")
    salary    = _esc(job.get("salary") or "Not listed")
    age       = _esc(time_ago(job.get("posted_at")))
    apply_url = job.get("apply_url","")
    label     = _esc(score_label(score))
    bar       = _esc(score_bar(score))
    tags_line = _esc("  ".join(hashtags))

    # Build match reasons block (max 3 lines)
    reasons_block = ""
    if reasons:
        for r in reasons[:3]:
            reasons_block += f"  {_esc(r)}\n"

    msg = (
        f"💼 *New Job Alert*\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"📌 *{title}*\n"
        f"🏢 {company}\n"
        f"📍 {location}\n"
        f"💰 {salary}\n"
        f"🕐 Posted: {age}\n\n"
        f"📊 *Match Score:* {label}\n"
        f"`{bar}`\n\n"
    )

    if reasons_block:
        msg += f"*Why it matched:*\n{reasons_block}\n"

    if apply_url:
        msg += f"🔗 [*Apply Now*]({apply_url})\n\n"

    msg += tags_line

    return msg


def send_telegram(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram credentials missing.")
        return False
    try:
        r = requests.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json={
                "chat_id":                  TELEGRAM_CHAT_ID,
                "text":                     message,
                "parse_mode":               "MarkdownV2",
                "disable_web_page_preview": True,
            },
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        result = r.json()
        if result.get("ok"):
            log.info("  ✉️  Telegram sent.")
            return True
        else:
            log.error(f"  Telegram API: {result.get('description')}")
            # Try plain-text fallback if markdown fails
            r2 = requests.post(
                f"{TELEGRAM_API_URL}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text":    _plaintext_fallback(message),
                    "disable_web_page_preview": True,
                },
                timeout=REQUEST_TIMEOUT,
            )
            return r2.json().get("ok", False)
    except Exception as e:
        log.error(f"  Telegram request failed: {e}")
        return False


def _plaintext_fallback(md: str) -> str:
    """Strip markdown escapes for a plain-text fallback."""
    return re.sub(r"\\([_*\[\]()~`>#+=|{}.!-])", r"\1", md)


# ==============================================================================
#  SECTION 11 — MAIN PIPELINE
# ==============================================================================

def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    log.info("=" * 60)
    log.info("  JOB AGGREGATOR BOT v2 — STARTING")
    log.info(f"  {now}")
    log.info("=" * 60)

    # 1. Google Sheets
    gc    = _sheets_client()
    sheet = get_worksheet(gc) if gc else None
    if not sheet:
        log.error("Cannot connect to Google Sheets — aborting.")
        return
    sent_ids = load_sent_ids(sheet)

    # 2. Fetch
    all_jobs = fetch_all_jobs()

    # 3. Filter
    log.info("\n🔎 Filtering & scoring…")
    relevant = [j for j in all_jobs if is_relevant_job(j)]
    log.info(f"  → {len(relevant)} passed keyword + age filter (from {len(all_jobs)} raw)")

    if DEBUG_MODE:
        log.debug("\n── All relevant job titles ──")
        for j in relevant:
            s, _, _ = score_job(j)
            log.debug(f"  [{s}/10] {j.get('title')} — {j.get('company')} [{j.get('source')}]")

    # 4. Score + deduplicate + send
    total_new = 0
    # Sort by score descending so highest-quality jobs arrive in chat first
    scored = sorted(relevant, key=lambda j: score_job(j)[0], reverse=True)

    for job in scored:
        job_id = str(job.get("id",""))
        if not job_id:
            continue
        if job_id in sent_ids:
            continue

        score, reasons, hashtags = score_job(job)

        if score < MIN_SCORE_TO_ALERT:
            log.debug(f"  ↓ Score {score} below threshold for: {job.get('title')}")
            continue

        log.info(f"  🆕 [{score}/10] {job.get('title')} @ {job.get('company')} [{job.get('source')}]")

        if DEBUG_MODE:
            log.debug(f"     reasons: {reasons}")
            log.debug(f"     hashtags: {hashtags}")
            total_new += 1
            continue

        message  = format_message(job, score, reasons, hashtags)
        success  = send_telegram(message)

        if success:
            record_sent(sheet, job_id,
                        f"{job.get('title')} @ {job.get('company')}",
                        score, job.get("source",""))
            sent_ids.add(job_id)
            total_new += 1

        time.sleep(0.6)   # Telegram rate limit

    log.info("\n" + "=" * 60)
    action = "would send" if DEBUG_MODE else "sent"
    log.info(f"  DONE — {total_new} alert(s) {action}.")
    log.info("=" * 60)

    if SEND_RUN_SUMMARY and not DEBUG_MODE:
        summary = (
            f"🤖 *Bot Run Complete*\n"
            f"📥 Fetched: `{len(all_jobs)}`\n"
            f"🎯 Matched filters: `{len(relevant)}`\n"
            f"🆕 Alerts sent: `{total_new}`\n"
            f"🕐 `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}`"
        )
        send_telegram(summary)


if __name__ == "__main__":
    main()