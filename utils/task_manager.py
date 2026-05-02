from database import get_connection
from utils.logger import get_logger
from datetime import datetime

logger = get_logger(__name__)


def create_task(user_id: int, title: str, due_datetime, reminder_times: list) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO personal_tasks (user_id, title, due_datetime) VALUES (?, ?, ?)",
        (user_id, title, due_datetime)
    )
    task_id = cursor.lastrowid
    for remind_at in reminder_times:
        cursor.execute(
            "INSERT INTO task_reminders (task_id, user_id, remind_at) VALUES (?, ?, ?)",
            (task_id, user_id, remind_at)
        )
    conn.commit()
    conn.close()
    logger.info(f"Created task {task_id} for user {user_id}: '{title}' with {len(reminder_times)} reminders")
    return task_id


def delete_task_by_reference(user_id: int, reference: str) -> bool:
    if not reference:
        return False
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM personal_tasks WHERE user_id=? AND title LIKE ? AND status='open'",
        (user_id, f"%{reference}%")
    ).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute(
        "UPDATE personal_tasks SET status='deleted' WHERE id=?",
        (row["id"],)
    )
    conn.commit()
    conn.close()
    return True


def update_task_datetime(user_id: int, reference: str, new_datetime: str) -> bool:
    if not reference:
        return False
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM personal_tasks WHERE user_id=? AND title LIKE ? AND status='open'",
        (user_id, f"%{reference}%")
    ).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute(
        "UPDATE personal_tasks SET due_datetime=? WHERE id=?",
        (new_datetime, row["id"])
    )
    conn.commit()
    conn.close()
    return True


def get_upcoming_tasks(user_id: int, days: int = 7) -> list:
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT id, title, due_datetime, status, created_at
        FROM personal_tasks
        WHERE user_id=? AND status='open'
          AND (due_datetime IS NULL OR due_datetime >= datetime('now'))
          AND (due_datetime IS NULL OR due_datetime <= datetime('now', '+{days} days'))
        ORDER BY
            CASE WHEN due_datetime IS NULL THEN 1 ELSE 0 END ASC,
            due_datetime ASC
    """, (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_task_by_id(task_id: int, user_id: int, title: str = None, due_datetime: str = None) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM personal_tasks WHERE id=? AND user_id=? AND status='open'",
        (task_id, user_id)
    ).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute(
        "UPDATE personal_tasks SET title=COALESCE(?,title), due_datetime=COALESCE(?,due_datetime) WHERE id=? AND user_id=?",
        (title, due_datetime, task_id, user_id)
    )
    conn.commit()
    conn.close()
    return True


def delete_task_by_id(task_id: int, user_id: int) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM personal_tasks WHERE id=? AND user_id=? AND status='open'",
        (task_id, user_id)
    ).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute(
        "UPDATE personal_tasks SET status='deleted' WHERE id=? AND user_id=?",
        (task_id, user_id)
    )
    conn.commit()
    conn.close()
    return True


def add_reminders_to_task(task_id: int, user_id: int, reminder_times: list) -> bool:
    conn = get_connection()
    try:
        task = conn.execute(
            "SELECT id FROM personal_tasks WHERE id=? AND user_id=? AND status='open'",
            (task_id, user_id)
        ).fetchone()
        if not task:
            return False
        for remind_at in reminder_times:
            conn.execute(
                "INSERT INTO task_reminders (task_id, user_id, remind_at) VALUES (?, ?, ?)",
                (task_id, user_id, remind_at)
            )
        conn.commit()
        logger.info(f"Added {len(reminder_times)} reminders to task {task_id}")
        return True
    except Exception as e:
        logger.error(f"add_reminders_to_task failed: {e}")
        return False
    finally:
        conn.close()


def load_pending_reminders() -> list:
    conn = get_connection()
    rows = conn.execute("""
        SELECT tr.id, tr.user_id, tr.remind_at, pt.title, u.phone_number
        FROM task_reminders tr
        JOIN personal_tasks pt ON tr.task_id = pt.id
        JOIN users u ON tr.user_id = u.id
        WHERE tr.sent = 0
          AND tr.remind_at > datetime('now')
          AND pt.status = 'open'
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_reminder_sent(reminder_id: int):
    conn = get_connection()
    conn.execute("UPDATE task_reminders SET sent=1 WHERE id=?", (reminder_id,))
    conn.commit()
    conn.close()
