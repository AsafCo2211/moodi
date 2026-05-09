"""
הנדלר להגשות קרובות — תפריט בחירת טווח זמן והצגת מטלות לפי טווח.
"""

from datetime import datetime, timedelta

from database import get_connection
from bot.sender import send_text, send_buttons, send_list
from utils.logger import get_logger

logger = get_logger(__name__)

RLM = "‏"


async def show_upcoming_menu(to: str, user_id: int):
    """
    שולח תפריט בחירת טווח זמן להגשות קרובות.

    Args:
        to: מספר הטלפון של המשתמש.
        user_id: מזהה המשתמש ב-DB (לא בשימוש ישיר, נשמר לעקביות חתימה).
    """
    send_list(
        to=to,
        message=f"{RLM}בחר טווח זמן:",
        button_text="בחר",
        sections=[{"title": "הגשות קרובות", "rows": [
            {"id": "upcoming_today", "title": "📅 היום"},
            {"id": "upcoming_3days", "title": "📅 3 ימים הקרובים"},
            {"id": "upcoming_week",  "title": "📅 השבוע הקרוב"},
        ]}]
    )


async def show_upcoming(to: str, user_id: int, days: int):
    """
    מציג מטלות להגשה בטווח הזמן המבוקש, מקובצות לפי קורס.

    Args:
        to: מספר הטלפון של המשתמש.
        user_id: מזהה המשתמש ב-DB.
        days: מספר הימים קדימה (0=היום, 3=שלושה ימים, 7=שבוע).
    """
    period = {0: "היום", 3: "3 הימים הקרובים", 7: "השבוע הקרוב"}[days]
    today = datetime.now().strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')

    conn = get_connection()
    assignments = conn.execute("""
        SELECT a.course_name, a.assignment_name, a.due_date
        FROM assignments a
        LEFT JOIN user_courses uc
          ON a.user_id = uc.user_id AND a.course_name = uc.course_name
        LEFT JOIN user_course_settings ucs
          ON uc.user_id = ucs.user_id AND uc.course_id = ucs.course_id
        LEFT JOIN user_assignment_settings uas
          ON a.user_id = uas.user_id AND a.moodle_assign_id = uas.moodle_assign_id
        WHERE a.user_id = ?
          AND a.is_submitted = 0
          AND COALESCE(ucs.is_active, 1) = 1
          AND COALESCE(uas.status, 'open') = 'open'
          AND a.due_date >= ? AND a.due_date <= ?
        ORDER BY a.due_date ASC
    """, (user_id, f"{today} 00:00:00", f"{end_date} 23:59:59")).fetchall()
    conn.close()

    if not assignments:
        send_text(to, f"{RLM}✅ אין הגשות ל{period}!")
        send_buttons(to, f"{RLM}מה תרצה לעשות?", [
            {"id": "back_main", "title": "⬅️ תפריט ראשי"},
        ])
        return

    groups: dict = {}
    for a in assignments:
        groups.setdefault(a["course_name"], []).append(a)

    message = f"{RLM}📅 *הגשות קרובות — {period}:*\n\n"
    for course_name, items in groups.items():
        message += f"{RLM}📖 *{course_name.strip()}*\n"
        for a in items:
            if a["due_date"]:
                due = datetime.strptime(a["due_date"], '%Y-%m-%d %H:%M:%S')
                due_str = due.strftime('%d/%m %H:%M')
            else:
                due_str = "ללא תאריך"
            message += f"{RLM}▫️ *{a['assignment_name'].strip()}*\n"
            message += f"{RLM}    ⏳ ```{due_str}```\n\n"
        message += "\n"

    send_text(to, message)
    send_buttons(to, f"{RLM}מה תרצה לעשות?", [
        {"id": "back_main", "title": "⬅️ תפריט ראשי"},
    ])
