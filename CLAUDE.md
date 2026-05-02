# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Moodi

WhatsApp bot for BGU students that connects to Moodle (BGU's LMS). Users receive a WhatsApp-based interactive menu to view their assignments, grades, and today's deadlines. The bot polls Moodle periodically and sends push notifications for new grades and upcoming deadlines.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database schema
python database.py

# Run the server (development)
uvicorn main:app --reload

# Run the server (production)
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Production Deployment

Server: Oracle Cloud VPS — ubuntu@130.61.50.239
SSH: ssh -i ~/Documents/Projects/ai-content-factory/ssh-key-202*-20.key ubuntu@130.61.50.239

To deploy updates:
1. git push origin main  (from local Mac)
2. SSH into server
3. cd ~/moodi && git fetch && git diff HEAD origin/main  (review changes)
4. git pull && sudo systemctl restart moodi

Services:
- moodi.service — uvicorn FastAPI app on port 8000
- cloudflared.service — Cloudflare Tunnel → https://moodi.aitoolhub.blog

Server-only files (not in git):
- /home/ubuntu/moodi/.env
- /etc/cloudflared/config.yml
- /etc/systemd/system/moodi.service
- /etc/systemd/system/cloudflared.service

View logs: sudo journalctl -u moodi -f

## Required Environment Variables

Create a `.env` file with:
- `WHATSAPP_TOKEN` — Meta Graph API bearer token
- `WHATSAPP_PHONE_ID` — WhatsApp Business phone number ID
- `WHATSAPP_VERIFY_TOKEN` — Webhook verification token (set in Meta dashboard)
- `ENCRYPTION_KEY` — Fernet key for encrypting stored tokens
- `GEMINI_API_KEY` — Google Gemini API key (used for course name shortening)
- `DATABASE_URL` — SQLite path, defaults to `moodi.db`
- `MOODLE_BASE_URL` — defaults to `https://moodle.bgu.ac.il/moodle`
- `POLLING_ENABLED` — set to `false` in dev, `true` in production

## Architecture

```
main.py                  FastAPI app entry point; mounts webhook router
config.py                All env vars loaded via dotenv
database.py              SQLite schema init + get_connection()

bot/
  webhook.py             Meta webhook endpoint (GET verify + POST receive)
  menu.py                Message routing logic and WhatsApp response builders
  sender.py              Low-level WhatsApp API calls (send_text, send_buttons, send_list)

moodle/
  client.py              Moodle Web Services API calls (call_moodle wrapper)
  parser.py              Parses raw Moodle API responses into clean dicts
  poller.py              poll_all_users() — fetches assignments/grades for all active users

notifications/
  engine.py              Notification dispatch: new assignments, new grades, morning summary, evening reminder, daily flag reset
  scheduler.py           APScheduler — polls 07:00-23:59 every 5 min, morning summary at 10:00, evening reminder at 20:00, flag reset at 01:00

auth/
  webview.py             Registration endpoint: GET /login serves HTML page, POST /auth/login authenticates against BGU token.php, returns 6-digit one-time code
  token_store.py         (stub) Encrypted wstoken storage

utils/
  course_namer.py        Shortens long course names via Gemini, caches results in courses_cache table
```

## Key Data Flow

1. **Incoming message**: Meta → `POST /webhook` → `bot/webhook.py` → `bot/menu.py:handle_message()`
2. **Menu interaction**: `handle_message` dispatches on `msg_type` + `content` ID (e.g. `"menu_assignments"`, `"course_42"`)
3. **Moodle polling**: `moodle/poller.py:poll_all_users()` → `moodle/client.py` → `moodle/parser.py` → SQLite
4. **Grades fetch**: always via `get_grades_table` (HTML table parser) — only API that returns `grade_range`
5. **Course name display**: `utils/course_namer.py:get_short_name()` checks `courses_cache` table first, then calls Gemini

## Database Schema

- `users` — phone number, Moodle user ID, wstoken, first_name, token_expires_at, is_active
- `assignments` — per-user assignments with flags: `notified_new`, `notified_today`, `notified_evening`, `is_submitted`
- `grades` — per-user grades with `grade`, `grade_range`, `notified`, `detected_at`
- `user_courses` — maps users to their enrolled Moodle courses
- `courses_cache` — caches Gemini-shortened course names by `moodle_course_id`
- `pending_registrations` — temporary registration codes with wstoken, 10-minute expiry

## WhatsApp API Constraints

- `send_buttons`: max 3 buttons
- `send_list`: max 10 rows total across all sections; row `title` max 24 chars
- All Hebrew text uses RLM (`\u200f`) prefix to force RTL rendering
- The bot uses Meta Graph API v25.0
