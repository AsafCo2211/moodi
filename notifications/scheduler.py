from apscheduler.schedulers.background import BackgroundScheduler
from moodle.poller import poll_all_users
from config import POLLING_ENABLED

scheduler = BackgroundScheduler()


def start_scheduler():
    if not POLLING_ENABLED:
        print("Polling disabled — scheduler not started")
        return
    scheduler.add_job(poll_all_users, "interval", minutes=5)
    scheduler.start()
    print("Scheduler started — polling every 5 minutes")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
