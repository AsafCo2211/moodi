from apscheduler.schedulers.background import BackgroundScheduler
from moodle.poller import poll_all_users
from notifications.engine import send_morning_summary, send_evening_reminder, reset_daily_flags
from config import POLLING_ENABLED

scheduler = BackgroundScheduler()


def start_scheduler():
    if not POLLING_ENABLED:
        print("Polling disabled — scheduler not started")
        return

    scheduler.add_job(poll_all_users, "interval", minutes=5)
    scheduler.add_job(send_morning_summary, "cron", hour=10, minute=00)
    scheduler.add_job(send_evening_reminder, "cron", hour=20, minute=0)
    scheduler.add_job(reset_daily_flags, "cron", hour=1, minute=0)

    scheduler.start()
    print("Scheduler started — polling every 5 min, morning at 10:00, evening at 20:00, reset at 01:00")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
