# Moodi 🎓

A production WhatsApp bot for Ben-Gurion University students that connects to Moodle via Web Services API — delivering assignment deadlines, grade notifications, and an interactive web dashboard, all through WhatsApp.

**Live at:** [moodi.aitoolhub.blog](https://moodi.aitoolhub.blog)

---

## Features

- **Assignment tracking** — fetches open assignments per course, sorted by urgency (today / 3 days / this week / overdue)
- **Grade notifications** — instant push notification when a new grade is detected, including grade range
- **Proactive alerts** — morning summary at 10:00, evening reminder at 20:00 for unsubmitted assignments
- **Recordings** — scrapes BGU's video system via autologin session management; supports watched/unwatched tracking and personal notes
- **Personal tasks** — natural Hebrew input ("תזכיר לי על X מחר בשעה 9") parsed by Gemini NLP, with reminder scheduling
- **Web dashboard** — full-featured dashboard with calendar view, assignment management, course toggles, and recordings tab
- **Voice messages** — audio transcription via Gemini API for hands-free task creation

---

## Architecture

```
FastAPI (Uvicorn)
├── bot/           — WhatsApp webhook, message routing, interactive menus
├── moodle/        — Moodle Web Services client, parser, assignment/grade poller
├── notifications/ — APScheduler (polling every 5 min, morning/evening jobs)
├── auth/          — BGU login flow, Fernet-encrypted token storage, dashboard sessions
├── utils/         — Gemini AI assistant, course name shortener, task manager
└── templates/     — Login page + full dashboard (vanilla JS, no framework)
```

**Stack:** Python 3.14, FastAPI, SQLite, APScheduler, Meta WhatsApp Cloud API v25.0, Google Gemini API, Fernet encryption

**Infrastructure:** Oracle Cloud VPS, Cloudflare Tunnel, systemd services (24/7 uptime)

---

## Database Schema

| Table | Purpose |
|---|---|
| `users` | Phone, Moodle user ID, encrypted wstoken + privatetoken |
| `assignments` | Per-user assignments with notification flags |
| `grades` | Per-user grades with grade_range and notification state |
| `user_courses` | User ↔ course mapping |
| `personal_tasks` | User-defined tasks with due dates |
| `task_reminders` | Scheduled reminders per task |
| `recordings` | Cached video metadata per course |
| `dashboard_sessions` | Time-limited dashboard access codes |

---

## Key Technical Decisions

- **Grades via `gradereport_user_get_grades_table`** — the only Moodle API that returns `grade_range`
- **Recordings via HTML scraping** — BGU's video system has no public WS API; uses `tool_mobile_get_autologin_key` to obtain a MoodleSession cookie
- **RTL rendering** — every WhatsApp message line prefixed with `\u200f` (RLM) to force correct Hebrew display
- **User-Agent spoofing** — BGU blocks non-mobile user agents; requests identify as MoodleMobile 5.1.1

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your tokens
python database.py     # initialize schema
uvicorn main:app --reload
```

**Required environment variables:** see `.env.example`

---

## Tests

```bash
pytest tests/
```

Covers notification engine (morning summary, evening reminder, due date change detection) with in-memory SQLite and mocked external calls.

---

## Status

Active development. Core features production-ready and running 24/7.  
See [STATUS.md](STATUS.md) for detailed feature status and roadmap.