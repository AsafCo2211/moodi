"""
הנדלר לדאשבורד ודוח מצב — יצירת קישור דאשבורד וייצור דוח שבועי.
"""

import random

from database import get_connection
from bot.sender import send_text, send_buttons
from utils.task_manager import get_upcoming_tasks
from utils.ai_assistant import generate_status_report
from utils.logger import get_logger

logger = get_logger(__name__)

RLM = "‏"


async def send_dashboard_link(phone_number: str, user_id: int):
    """
    יוצר session חדש לדאשבורד ושולח למשתמש קישור כניסה תקף ל-10 דקות.

    Args:
        phone_number: מספר הטלפון של המשתמש.
        user_id: מזהה המשתמש ב-DB (לא בשימוש ישיר, נשמר לעקביות חתימה).
    """
    code = str(random.randint(100000, 999999))
    conn = get_connection()
    conn.execute(
        "INSERT INTO dashboard_sessions (phone_number, code, expires_at) "
        "VALUES (?, ?, datetime('now', '+10 minutes'))",
        (phone_number, code),
    )
    conn.commit()
    conn.close()
    send_text(
        phone_number,
        f"{RLM}הדאשבורד שלך מוכן! 🖥️\n"
        f"{RLM}לחץ על הקישור כדי להיכנס:\n"
        f"{RLM}https://moodi.aitoolhub.blog/dashboard?phone={phone_number}&code={code}\n\n"
        f"{RLM}⏱️ הקישור תקף ל-10 דקות בלבד.",
    )


async def send_status_report(phone_number: str, user_id: int):
    """
    מייצר דוח מצב שבועי על מטלות ומשימות אישיות ושולח אותו למשתמש.

    Args:
        phone_number: מספר הטלפון של המשתמש.
        user_id: מזהה המשתמש ב-DB.
    """
    conn = get_connection()
    assignments = conn.execute("""
        SELECT a.assignment_name, a.course_name, a.due_date
        FROM assignments a
        LEFT JOIN user_assignment_settings uas
            ON a.user_id = uas.user_id AND a.moodle_assign_id = uas.moodle_assign_id
        LEFT JOIN user_courses uc ON a.user_id = uc.user_id AND a.course_name = uc.course_name
        LEFT JOIN user_course_settings ucs ON uc.user_id = ucs.user_id AND uc.course_id = ucs.course_id
        WHERE a.user_id = ?
          AND a.is_submitted = 0
          AND COALESCE(uas.status, 'open') = 'open'
          AND COALESCE(ucs.is_active, 1) = 1
          AND a.due_date >= datetime('now')
          AND a.due_date <= datetime('now', '+7 days')
        ORDER BY a.due_date ASC
    """, (user_id,)).fetchall()
    first_name_row = conn.execute(
        "SELECT first_name FROM users WHERE id=?", (user_id,)
    ).fetchone()
    first_name = (first_name_row["first_name"] or "") if first_name_row else ""
    conn.close()

    personal_tasks = get_upcoming_tasks(user_id, days=7)

    report = generate_status_report(
        first_name=first_name,
        assignments=[dict(a) for a in assignments],
        personal_tasks=personal_tasks,
    )
    send_text(phone_number, report)
    send_buttons(phone_number, f"{RLM}מה תרצה לעשות?", [
        {"id": "back_main", "title": "⬅️ תפריט ראשי"}
    ])
