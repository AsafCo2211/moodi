from apscheduler.schedulers.background import BackgroundScheduler
from moodle.poller import poll_all_users
from notifications.engine import send_morning_summary, send_evening_reminder, reset_daily_flags
from config import POLLING_ENABLED
from utils.logger import get_logger
from datetime import datetime

logger = get_logger(__name__)
scheduler = BackgroundScheduler()


def send_task_reminder(reminder_id: int, user_id: int, phone_number: str, title: str):
    from bot.sender import send_text, send_buttons
    from utils.task_manager import mark_reminder_sent
    RLM = "‏"
    try:
        send_text(phone_number, f"{RLM}⏰ תזכורת: {title}")
        send_buttons(phone_number, f"{RLM}מה תרצה לעשות?", [
            {"id": "back_main", "title": "⬅️ תפריט ראשי"}
        ])
        mark_reminder_sent(reminder_id)
        logger.info(f"Sent reminder {reminder_id} to {phone_number}")
    except Exception as e:
        logger.error(f"Failed to send reminder {reminder_id}: {e}")


def schedule_reminder(task_id: int, user_id: int, phone_number: str, title: str, remind_at: str):
    from database import get_connection
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM task_reminders WHERE task_id=? AND remind_at=? AND sent=0",
        (task_id, remind_at)
    ).fetchone()
    conn.close()
    if not row:
        logger.warning(f"No reminder found for task {task_id} at {remind_at}")
        return
    reminder_id = row["id"]
    try:
        run_date = datetime.fromisoformat(remind_at)
        scheduler.add_job(
            send_task_reminder,
            trigger='date',
            run_date=run_date,
            args=[reminder_id, user_id, phone_number, title],
            id=f"reminder_{reminder_id}",
            replace_existing=True
        )
        logger.info(f"Scheduled reminder {reminder_id} for task {task_id} at {remind_at}")
    except Exception as e:
        logger.error(f"Failed to schedule reminder {reminder_id}: {e}")


def load_task_reminders():
    from utils.task_manager import load_pending_reminders
    reminders = load_pending_reminders()
    for r in reminders:
        try:
            scheduler.add_job(
                send_task_reminder,
                trigger='date',
                run_date=datetime.fromisoformat(r['remind_at']),
                args=[r['id'], r['user_id'], r['phone_number'], r['title']],
                id=f"reminder_{r['id']}",
                replace_existing=True
            )
        except Exception as e:
            logger.warning(f"Failed to schedule reminder {r['id']}: {e}")
    if reminders:
        logger.info(f"Loaded {len(reminders)} pending task reminders")


def start_scheduler():
    if not POLLING_ENABLED:
        logger.info("Polling disabled — scheduler not started")
        return

    scheduler.add_job(poll_all_users, "cron", hour="7-23", minute="*/5")
    scheduler.add_job(send_morning_summary, "cron", hour=10, minute=00)
    scheduler.add_job(send_evening_reminder, "cron", hour=20, minute=0)
    scheduler.add_job(reset_daily_flags, "cron", hour=1, minute=0)

    scheduler.start()
    load_task_reminders()
    logger.info("Scheduler started — polling every 5 min, morning at 10:00, evening at 20:00, reset at 01:00")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
