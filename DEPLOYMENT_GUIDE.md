# 🤖 Remote Job Aggregator Bot — Complete Deployment Guide

> **Who this guide is for:** Complete beginners to Python, Telegram bots, Google APIs, and GitHub Actions. Every single step is documented with no assumed knowledge.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Prerequisites — What You Need Before Starting](#2-prerequisites)
3. [Step 1: Set Up Your Telegram Bot](#3-step-1-set-up-your-telegram-bot)
4. [Step 2: Set Up Google Sheets as Your Database](#4-step-2-set-up-google-sheets)
5. [Step 3: Prepare Your GitHub Repository](#5-step-3-prepare-your-github-repository)
6. [Step 4: Add Secrets to GitHub](#6-step-4-add-secrets-to-github)
7. [Step 5: Test the Bot Locally (Optional but Recommended)](#7-step-5-test-locally)
8. [Step 6: Deploy and Verify on GitHub Actions](#8-step-6-deploy-and-verify)
9. [Customisation Guide](#9-customisation-guide)
10. [Troubleshooting Common Errors](#10-troubleshooting)

---

## 1. Project Overview

This bot automatically:
1. Runs every 6 hours via GitHub Actions (free, no server needed)
2. Fetches job listings from 5+ remote job boards
3. Filters them using your include/exclude keyword rules
4. Checks a Google Sheet to avoid sending duplicate alerts
5. Sends formatted notifications to your Telegram chat

**Files in this project:**

| File | Purpose |
|------|---------|
| `main.py` | The entire bot logic |
| `requirements.txt` | Python package list |
| `.env.example` | Template for your secret keys |
| `.github/workflows/main.yml` | GitHub Actions automation config |
| `.gitignore` | Prevents secrets from being committed |

---

## 2. Prerequisites

You need the following accounts (all free):

- [ ] **GitHub account** — [github.com](https://github.com)
- [ ] **Telegram account** — [telegram.org](https://telegram.org) (mobile app)
- [ ] **Google account** — [google.com](https://google.com)
- [ ] **Python 3.10+ installed locally** (for local testing only)

To check if Python is installed, open your terminal and type:
```bash
python --version
# or
python3 --version
```
If you see `Python 3.10.x` or higher, you're good. Otherwise download it from [python.org](https://python.org).

---

## 3. Step 1: Set Up Your Telegram Bot

This step creates a bot identity that can send messages to your Telegram chat.

### 3.1 Create Your Bot with BotFather

1. Open Telegram on your phone or desktop
2. Search for **`@BotFather`** (it has a blue checkmark — it's the official bot)
3. Start the conversation by clicking **START** or sending `/start`
4. Send the command: `/newbot`
5. BotFather will ask: *"Alright, a new bot. How are we going to call it?"*
   - Type a display name, e.g.: `My Job Alerts Bot`
6. BotFather will ask: *"Good. Now let's choose a username for your bot."*
   - Type a unique username ending in `bot`, e.g.: `myjobsalerts_bot`
   - If the name is taken, try variations until one is accepted
7. BotFather will reply with a message containing:
   ```
   Done! Congratulations on your new bot. You will find it at t.me/myjobsalerts_bot.
   
   Use this token to access the HTTP API:
   1234567890:ABCDefGhijKLMnopQrsTUVwxyz
   ```
8. **Copy and save this token** — this is your `TELEGRAM_BOT_TOKEN`

> ⚠️ **Security warning:** Never share your bot token publicly. Anyone with this token can control your bot.

### 3.2 Get Your Personal Telegram Chat ID

Your bot needs to know *where* to send messages. The simplest setup sends messages directly to your personal Telegram account.

**Method: Use @userinfobot**

1. In Telegram, search for **`@userinfobot`**
2. Send it `/start`
3. It will reply with your information including: `Id: 123456789`
4. **Copy this number** — this is your `TELEGRAM_CHAT_ID`

### 3.3 Start a Conversation with Your Bot

> **Critical:** Telegram bots cannot message you first. You must initiate contact.

1. Search for your bot by its username (e.g., `@myjobsalerts_bot`)
2. Click **START**
3. Your bot can now message you ✅

### 3.4 Quick Verification Test

Paste this URL into your browser (replace with your real values):

```
https://api.telegram.org/bot<YOUR_BOT_TOKEN>/sendMessage?chat_id=<YOUR_CHAT_ID>&text=Hello!+Bot+is+working!
```

If you receive a "Hello! Bot is working!" message in Telegram, everything is set up correctly. 🎉

---

## 4. Step 2: Set Up Google Sheets

Google Sheets acts as the bot's memory — it stores job IDs to prevent duplicate alerts.

### 4.1 Create the Google Sheet

1. Go to [sheets.google.com](https://sheets.google.com)
2. Click **+ Blank** to create a new spreadsheet
3. Name it something like `Job Bot Database`
4. Look at the URL in your browser:
   ```
   https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit
   ```
5. The long string between `/d/` and `/edit` is your **`GOOGLE_SHEET_ID`**
   - Example: `1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms`
6. **Copy and save this ID**

> ✅ You don't need to add any headers or data — the bot creates the worksheet automatically.

### 4.2 Create a Google Cloud Project

Google requires a "project" container to issue API credentials.

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Sign in with your Google account
3. At the top, click the project dropdown (it might say "Select a project")
4. Click **New Project**
5. Name it: `job-bot-project` (or anything you like)
6. Click **Create**
7. Wait a moment, then make sure your new project is selected in the dropdown

### 4.3 Enable the Required APIs

1. In the left sidebar, click **APIs & Services → Library**
2. Search for **"Google Sheets API"**
3. Click on it, then click **Enable**
4. Go back to the library (click ← or go to APIs & Services → Library again)
5. Search for **"Google Drive API"**
6. Click on it, then click **Enable**

### 4.4 Create a Service Account

A service account is like a "robot Google account" that your bot will use to access the sheet.

1. Go to **APIs & Services → Credentials**
2. Click **+ CREATE CREDENTIALS** → **Service account**
3. Fill in the form:
   - **Service account name:** `job-bot-service-account`
   - **Service account ID:** auto-fills, leave it
   - **Description:** "Service account for Job Aggregator Bot"
4. Click **CREATE AND CONTINUE**
5. On "Grant this service account access" — you can skip this, just click **CONTINUE**
6. On "Grant users access" — skip this too, click **DONE**

### 4.5 Download the Service Account Key (credentials.json)

1. On the Credentials page, you'll see your new service account listed
2. Click on the service account email to open it
3. Click the **KEYS** tab
4. Click **ADD KEY → Create new key**
5. Select **JSON** format
6. Click **CREATE**
7. A file called something like `job-bot-project-xxxx.json` will download automatically
8. **Rename this file to `credentials.json`** and keep it somewhere safe

> ⚠️ **This file contains your private key. Never commit it to Git or share it.**

### 4.6 Share Your Google Sheet with the Service Account

The service account needs permission to write to your sheet.

1. Open your `credentials.json` file with any text editor
2. Find the line with `"client_email"` — copy the email address (looks like: `job-bot-service-account@job-bot-project-12345.iam.gserviceaccount.com`)
3. Go to your Google Sheet
4. Click **Share** (top right)
5. Paste the service account email into the "Add people" field
6. Set the permission to **Editor**
7. **Uncheck "Notify people"** (the service account has no inbox)
8. Click **Share**

### 4.7 Encode Your Credentials as Base64

GitHub Secrets can only store text strings, not files. We encode the JSON key as Base64 text.

**On macOS or Linux:**
```bash
base64 -i credentials.json | tr -d '\n'
```

**On Windows (PowerShell):**
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("credentials.json")) | Set-Clipboard
```

**Copy the entire output** — it's a very long single line of letters and numbers. This is your `GOOGLE_SHEET_CREDENTIALS_JSON` value.

---

## 5. Step 3: Prepare Your GitHub Repository

### 5.1 Create a New Repository

1. Go to [github.com](https://github.com) and sign in
2. Click the **+** icon → **New repository**
3. Name it: `job-aggregator-bot`
4. Set visibility to **Private** (keeps your secrets configuration private)
5. Leave all other options unchecked (no README, no .gitignore)
6. Click **Create repository**

### 5.2 Upload the Project Files

**Option A: Using the GitHub web interface (easiest)**

1. On your new empty repository page, click **uploading an existing file**
2. Drag and drop all project files:
   - `main.py`
   - `requirements.txt`
   - `.env.example`
   - `.gitignore`
3. For the workflow file, you need to create the folder structure:
   - After uploading the above files, click **Add file → Create new file**
   - In the filename field, type: `.github/workflows/main.yml`
   - GitHub will auto-create the nested folders
   - Paste the contents of `main.yml` into the editor
4. Click **Commit changes**

**Option B: Using Git command line**

```bash
# Navigate to the project folder
cd path/to/job-aggregator-bot

# Initialise git and push to GitHub
git init
git add .
git commit -m "Initial commit: Job Aggregator Bot"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/job-aggregator-bot.git
git push -u origin main
```

> ⚠️ **Critical check:** Make sure the `.env` file (with real credentials) is NOT committed. Only `.env.example` should be in the repository.

---

## 6. Step 4: Add Secrets to GitHub

GitHub Secrets store your credentials securely — they're injected as environment variables when the workflow runs, and never shown in logs.

### 6.1 Navigate to Secrets Settings

1. Go to your repository on GitHub
2. Click the **Settings** tab (top navigation bar)
3. In the left sidebar, click **Secrets and variables → Actions**
4. Click the **Secrets** tab (it may already be selected)

### 6.2 Add Each Secret

Click **New repository secret** for each of the following:

---

**Secret 1: `TELEGRAM_BOT_TOKEN`**
- Name: `TELEGRAM_BOT_TOKEN`
- Secret: Your bot token from BotFather (e.g., `1234567890:ABCDefGhijKLMnopQrsTUVwxyz`)
- Click **Add secret**

---

**Secret 2: `TELEGRAM_CHAT_ID`**
- Name: `TELEGRAM_CHAT_ID`
- Secret: Your Telegram User ID from @userinfobot (e.g., `987654321`)
- Click **Add secret**

---

**Secret 3: `GOOGLE_SHEET_CREDENTIALS_JSON`**
- Name: `GOOGLE_SHEET_CREDENTIALS_JSON`
- Secret: The entire Base64-encoded string from Step 4.7 (the very long string)
- Click **Add secret**

---

**Secret 4: `GOOGLE_SHEET_ID`**
- Name: `GOOGLE_SHEET_ID`
- Secret: Your Google Sheet ID (e.g., `1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms`)
- Click **Add secret**

---

After adding all four secrets, your Secrets page should list:
- ✅ TELEGRAM_BOT_TOKEN
- ✅ TELEGRAM_CHAT_ID
- ✅ GOOGLE_SHEET_CREDENTIALS_JSON
- ✅ GOOGLE_SHEET_ID

---

## 7. Step 5: Test the Bot Locally (Optional but Recommended)

Testing locally first saves you from mysterious failures in GitHub Actions.

### 7.1 Set Up a Virtual Environment

```bash
# Create a virtual environment
python -m venv venv

# Activate it
# macOS/Linux:
source venv/bin/activate
# Windows:
venv\Scripts\activate
```

### 7.2 Install Dependencies

```bash
pip install -r requirements.txt
```

### 7.3 Create Your Local .env File

```bash
# Copy the template
cp .env.example .env
```

Open `.env` in a text editor and fill in your real values:
```env
TELEGRAM_BOT_TOKEN="1234567890:ABCDefGhijKLMnopQrsTUVwxyz"
TELEGRAM_CHAT_ID="987654321"
GOOGLE_SHEET_CREDENTIALS_JSON="eyJ0eXBlIjoic2VydmljZV9hY2NvdW50..."
GOOGLE_SHEET_ID="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"
SEND_RUN_SUMMARY="true"
```

### 7.4 Run the Bot

```bash
python main.py
```

**Expected output:**
```
2025-01-15 10:30:00 [INFO] ============================================================
2025-01-15 10:30:00 [INFO]   JOB AGGREGATOR BOT — STARTING RUN
2025-01-15 10:30:01 [INFO] ✅ Google Sheets authenticated successfully.
2025-01-15 10:30:01 [INFO] 📋 Loaded 0 sent job IDs from Google Sheets.
2025-01-15 10:30:02 [INFO] 🔍 Fetching RSS: We Work Remotely (https://...)
2025-01-15 10:30:03 [INFO]    → Found 50 listings from We Work Remotely
...
2025-01-15 10:30:15 [INFO] 📦 Total raw jobs fetched: 287
2025-01-15 10:30:15 [INFO] 🔎 Applying keyword filters...
2025-01-15 10:30:15 [INFO]    → 5 jobs passed keyword filters.
2025-01-15 10:30:16 [INFO]    🆕 New job: Junior Frontend Developer @ TechCorp [We Work Remotely]
2025-01-15 10:30:16 [INFO]    ✉️  Telegram message sent successfully.
```

Check your Telegram — you should receive job alert messages! 🎉

---

## 8. Step 6: Deploy and Verify on GitHub Actions

### 8.1 Trigger Your First Manual Run

1. Go to your GitHub repository
2. Click the **Actions** tab
3. In the left sidebar, click **🤖 Job Aggregator Bot**
4. Click **Run workflow** → **Run workflow** (green button)
5. Wait about 60–90 seconds

### 8.2 Check the Run Logs

1. Click on the running workflow (yellow spinning circle)
2. Click on the **Fetch, Filter & Alert** job
3. Expand each step to see the logs
4. Look for the final summary showing how many jobs were found and sent

### 8.3 Verify the Schedule

The workflow is configured to run every 6 hours automatically. You can confirm this:

1. Go to **Actions** → **🤖 Job Aggregator Bot**
2. You should see runs appearing on the schedule (00:00, 06:00, 12:00, 18:00 UTC)

> 💡 **Note:** GitHub may delay scheduled workflows by up to 15-30 minutes during high-traffic periods. This is normal.

### 8.4 Check Your Google Sheet

After the bot runs, open your Google Sheet. You should see a tab called `sent_jobs` with columns:
- `job_id` — the unique identifier
- `job_title` — human-readable title
- `sent_at` — ISO timestamp

This confirms the deduplication system is working.

---

## 9. Customisation Guide

### Changing the Run Schedule

Edit `.github/workflows/main.yml`:

```yaml
schedule:
  # Every 3 hours:
  - cron: "0 */3 * * *"
  
  # Twice a day at 8 AM and 8 PM UTC:
  - cron: "0 8,20 * * *"
  
  # Once a day at 9 AM UTC (good starting point):
  - cron: "0 9 * * *"
```

Use [crontab.guru](https://crontab.guru) to build and test cron expressions visually.

### Adding New Keywords

In `main.py`, find the `INCLUDE_KEYWORDS` list and add your terms:

```python
INCLUDE_KEYWORDS = [
    # ...existing keywords...
    "motion designer",          # ← Add new ones here
    "social media designer",
    "vue js developer remote",
]
```

### Adding New Job Sources

Add a new entry to the `JOB_SOURCES` list:

```python
JOB_SOURCES = [
    # ...existing sources...
    {
        "name": "Jobspresso",
        "type": "rss",
        "url": "https://jobspresso.co/feed/",
    },
]
```

Common RSS feed URLs for remote jobs:
- **Jobspresso:** `https://jobspresso.co/feed/`
- **Flexjobs (free listings):** `https://www.flexjobs.com/jobs/rss`
- **Working Nomads:** `https://www.workingnomads.com/feed`
- **Remote OK (API):** `https://remoteok.com/api`

### Receiving Alerts in a Telegram Channel

To send to a Telegram channel instead of your personal chat:

1. Create a Telegram channel
2. Add your bot as an **Administrator** of the channel
3. Get the channel ID:
   - Forward a message from the channel to `@userinfobot`
   - It will show the channel ID (starts with `-100`)
4. Set `TELEGRAM_CHAT_ID` to the channel ID (e.g., `-1001234567890`)

---

## 10. Troubleshooting

### ❌ "GOOGLE_SHEET_CREDENTIALS_JSON is not set"

**Cause:** The environment variable isn't loaded.

**Fix:**
- Local: Make sure your `.env` file exists and has the correct value
- GitHub Actions: Verify the secret name is exactly `GOOGLE_SHEET_CREDENTIALS_JSON` (case-sensitive)

---

### ❌ "Could not open Google Sheet" / "PERMISSION_DENIED"

**Cause:** The service account doesn't have access to the sheet.

**Fix:**
1. Open your `credentials.json` file
2. Copy the `client_email` value
3. Open your Google Sheet → Share → Add that email as **Editor**

---

### ❌ Telegram: "Unauthorized" (401 error)

**Cause:** The bot token is invalid or has been revoked.

**Fix:**
1. Message `@BotFather` on Telegram
2. Send `/mybots` and select your bot
3. Click **API Token** to see or regenerate the token
4. Update the `TELEGRAM_BOT_TOKEN` secret in GitHub

---

### ❌ Telegram: "Chat not found" (400 error)

**Cause:** The bot has never had a conversation with your Telegram account.

**Fix:**
1. Find your bot on Telegram and send it `/start`
2. Try running the bot again

---

### ❌ "No jobs found" (bot runs but sends nothing)

**Cause:** Either no jobs matched the keywords, or the sheet already contains all the job IDs.

**Debug steps:**
1. Run locally with `SEND_RUN_SUMMARY="true"` to see counts
2. Check the GitHub Actions logs for the line: `→ X jobs passed keyword filters`
3. If `X = 0`, your keywords may not be matching current listings — try broader terms
4. If `X > 0` but `0 new alerts sent`, the jobs are already in your sheet (working correctly!)

---

### ❌ GitHub Actions: Workflow doesn't appear in the Actions tab

**Cause:** The `main.yml` file may not be in the exact right location.

**Fix:** The file MUST be at this exact path in your repository:
```
.github/workflows/main.yml
```
Both `.github` and `workflows` are folders. Verify this in your repository file browser.

---

### ❌ Base64 encoding produces errors

**Fix — Easier alternative to Base64:**

If Base64 encoding is causing trouble, you can store the credentials differently.

1. Open `credentials.json` in a text editor
2. Copy the entire contents
3. Paste it directly as the `GOOGLE_SHEET_CREDENTIALS_JSON` secret value

Then modify `main.py`'s `get_google_sheet_client()` function — replace the decode lines:

```python
# Replace this:
credentials_json_str = base64.b64decode(credentials_b64).decode("utf-8")
credentials_dict = json.loads(credentials_json_str)

# With this (direct JSON):
credentials_dict = json.loads(credentials_b64)
```

---

## Appendix: Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│              GitHub Actions (every 6h)              │
│                                                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐  │
│  │  WWR RSS │    │ Remotive │    │  HackerNews  │  │
│  │  Feed    │    │   API    │    │  Hiring      │  │
│  └────┬─────┘    └────┬─────┘    └──────┬───────┘  │
│       └───────────────┴──────────────────┘          │
│                       │                             │
│              ┌─────────▼──────────┐                 │
│              │   Keyword Filter   │                 │
│              │  (include/exclude) │                 │
│              └─────────┬──────────┘                 │
│                        │                            │
│              ┌─────────▼──────────┐                 │
│              │  Duplicate Check   │◄──Google Sheets │
│              │  (Google Sheets)   │──►(write IDs)   │
│              └─────────┬──────────┘                 │
│                        │                            │
│              ┌─────────▼──────────┐                 │
│              │  Telegram Alert    │──► Your Chat    │
│              └────────────────────┘                 │
└─────────────────────────────────────────────────────┘
```

---

*Built with Python 3.11 · Hosted on GitHub Actions · Database: Google Sheets · Notifications: Telegram*
