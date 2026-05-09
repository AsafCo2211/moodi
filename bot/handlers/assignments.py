"""
הנדלר למטלות — בחירת קורס והצגת מטלות פתוחות.
מכיל את כל הלוגיקה הקשורה לתצוגת מטלות ב-WhatsApp.
"""

from datetime import datetime

from database import get_connection
from bot.sender import send_text, send_buttons, send_list
from utils.course_namer import get_short_name
from utils.logger import get_logger

logger = get_logger(__name__)

RLM = "‏"


def assignment_emoji(due_date_str: str) -> str:
    """
    מחזיר אמוג'י צבעוני לפי קרבת תאריך ההגשה.

    Args:
        due_date_str: תאריך ההגשה כמחרוזת '%Y-%m-%d %H:%M:%S', או None.

    Returns:
        אמוג'י: ⚪ (ללא תאריך), ⚫ (עבר), 🔴 (היום), 🟡 (3 ימים), 🟢 (אחר).
    """
    if not due_date_str:
        return "⚪"
    due = datetime.strptime(due_date_str, '%Y-%m-%d %H:%M:%S')
    now = datetime.now()
    diff = due - now
    if diff.total_seconds() < 0:
        return "⚫"
    elif diff.days < 1:
        return "🔴"
    elif diff.days < 3:
        return "🟡"
    else:
        return "🟢"


def format_due_date(due_date_str: str) -> str:
    """
    מעצב תאריך הגשה לתצוגה ידידותית.

    Args:
        due_date_str: תאריך ההגשה כמחרוזת '%Y-%m-%d %H:%M:%S', או None.

    Returns:
        מחרוזת כמו 'היום | 14:00', 'מחר | 09:00', '15/05/25 | 12:00', או 'ללא תאריך'.
    """
    if not due_date_str:
        return "ללא תאריך"
    due = datetime.strptime(due_date_str, '%Y-%m-%d %H:%M:%S')
    now = datetime.now()
    diff = due - now
    if diff.days == 0:
        return f"היום | {due.strftime('%H:%M')}"
    elif diff.days == 1:
        return f"מחר | {due.strftime('%H:%M')}"
    else:
        return f"{due.strftime('%d/%m/%y')} | {due.strftime('%H:%M')}"


async def show_course_selection(to: str, user_id: int):
    """
    שולח למשתמש תפריט בחירת קורס עם מטלות פתוחות.

    Args:
        to: מספר הטלפון של המשתמש.
        user_id: מזהה המשתמש ב-DB.
    """
    from bot.menu import send_main_menu, get_first_name

    conn = get_connection()
    courses = conn.execute("""
    SELECT DISTINCT uc.course_id, uc.course_name
    FROM user_courses uc
    LEFT JOIN user_course_settings ucs
      ON uc.user_id = ucs.user_id AND uc.course_id = ucs.course_id
    WHERE uc.user_id = ? AND COALESCE(ucs.is_active, 1) = 1
    AND EXISTS (
        SELECT 1 FROM assignments a
        WHERE a.user_id = uc.user_id
        AND a.course_name = uc.course_name
        AND a.is_submitted = 0
    )
    ORDER BY uc.added_at DESC
""", (user_id,)).fetchall()
    name_row = conn.execute("SELECT first_name FROM users WHERE id = ?", (user_id,)).fetchone()
    name = get_first_name(name_row) if name_row else ""
    conn.close()

    if not courses:
        send_text(to, f"{RLM}🎉 אין לך מטלות פתוחות כרגע!")
        send_main_menu(to, name)
        return

    rows = []
    for c in courses[:9]:
        short = get_short_name(c["course_id"], c["course_name"].strip())
        rows.append({
            "id": f"course_{c['course_id']}",
            "title": short
        })
    rows.append({"id": "course_all", "title": "📋 כל הקורסים"})

    send_list(
        to=to,
        message=f"{RLM}באיזה קורס תרצה לראות מטלות?",
        button_text="בחר קורס",
        sections=[{"title": "הקורסים שלך", "rows": rows}]
    )


async def show_assignments(to: str, user_id: int, course_id, user=None, full_view: bool = False):
    """
    מציג רשימת מטלות פתוחות — לקורס ספציפי או לכל הקורסים.

    Args:
        to: מספר הטלפון של המשתמש.
        user_id: מזהה המשתמש ב-DB.
        course_id: מזהה קורס ספציפי, או None להצגת כל הקורסים.
        user: שורת המשתמש מה-DB (לשם תצוגה).
        full_view: אם True, מציג את כל המטלות ולא רק 3 ראשונות.
    """
    from bot.menu import send_main_menu, get_first_name

    name = get_first_name(user) if user else ""
    conn = get_connection()

    if course_id is None:
        rows = conn.execute("""
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
            ORDER BY
                CASE WHEN a.due_date IS NULL THEN 1 ELSE 0 END ASC,
                a.due_date ASC
        """, (user_id,)).fetchall()
        course_header = None
    else:
        course_name_row = conn.execute(
            "SELECT course_name FROM user_courses WHERE course_id = ? AND user_id = ?",
            (course_id, user_id)
        ).fetchone()
        course_header = course_name_row["course_name"]
        rows = conn.execute("""
            SELECT a.course_name, a.assignment_name, a.due_date
            FROM assignments a
            LEFT JOIN user_courses uc
              ON a.user_id = uc.user_id AND a.course_name = uc.course_name
            LEFT JOIN user_course_settings ucs
              ON uc.user_id = ucs.user_id AND uc.course_id = ucs.course_id
            LEFT JOIN user_assignment_settings uas
              ON a.user_id = uas.user_id AND a.moodle_assign_id = uas.moodle_assign_id
            WHERE a.user_id = ?
              AND a.course_name = ?
              AND a.is_submitted = 0
              AND COALESCE(ucs.is_active, 1) = 1
              AND COALESCE(uas.status, 'open') = 'open'
            ORDER BY
                CASE WHEN a.due_date IS NULL THEN 1 ELSE 0 END ASC,
                a.due_date ASC
        """, (user_id, course_header)).fetchall()
    conn.close()

    today = datetime.now().date()
    red, yellow, green, white, overdue = [], [], [], [], []
    for a in rows:
        if not a["due_date"]:
            white.append(a)
            continue
        due_date_obj = datetime.strptime(a["due_date"], '%Y-%m-%d %H:%M:%S').date()
        if due_date_obj < today:
            overdue.append(a)
        elif due_date_obj == today:
            red.append(a)
        elif (due_date_obj - today).days <= 3:
            yellow.append(a)
        else:
            green.append(a)

    open_items = (
        [(a, "🔴") for a in red] +
        [(a, "🟡") for a in yellow] +
        [(a, "🟢") for a in green] +
        [(a, "⚪") for a in white]
    )
    overdue_items = [(a, "❗️") for a in overdue]

    if not open_items and not overdue_items:
        send_text(to, f"{RLM}{name}, סיימת הכל! 🎉 אין מטלות פתוחות כרגע.")
        send_main_menu(to, name)
        return

    include_course = course_id is None

    def fmt_date(due_str):
        due = datetime.strptime(due_str, '%Y-%m-%d %H:%M:%S')
        diff_days = (due.date() - datetime.now().date()).days
        if diff_days == 0:
            return f"היום | {due.strftime('%H:%M')}"
        elif diff_days == 1:
            return f"מחר | {due.strftime('%H:%M')}"
        else:
            return f"{due.strftime('%d/%m/%y')} | {due.strftime('%H:%M')}"

    def fmt_block(a, emoji):
        date_part = fmt_date(a["due_date"]) if a["due_date"] else "ללא תאריך"
        SEP = f"{RLM}• - - - - - - - - - - - - - - - - - - - - •\n"
        if include_course:
            return (
                SEP +
                f"{RLM}📖 *{a['course_name'].strip()}*\n\n"
                f"{RLM}📋 *מטלה*: {a['assignment_name'].strip()}\n\n"
                f"{RLM}{emoji} *מועד הגשה*: {date_part}\n"
            )
        else:
            return (
                SEP +
                f"{RLM}📋 *מטלה*: {a['assignment_name'].strip()}\n\n"
                f"{RLM}{emoji} *מועד הגשה*: {date_part}\n"
            )

    message = f"{RLM}📋 *המטלות הפתוחות שלך:*\n"
    if course_header:
        message += f"{RLM}📖 *{course_header.strip()}*\n"
    message += "\n"

    if full_view:
        for a, emoji in open_items:
            message += fmt_block(a, emoji)
        message += f"{RLM}• - - - - - - - - - - - - - - - - - - - - •\n"
    else:
        top3 = open_items[:3]
        rest = open_items[3:]

        for a, emoji in top3:
            message += fmt_block(a, emoji)
        message += f"{RLM}• - - - - - - - - - - - - - - - - - - - - •\n"

        if rest:
            rest_counts = {"🔴": 0, "🟡": 0, "🟢": 0, "⚪": 0}
            for _, emoji in rest:
                rest_counts[emoji] += 1
            message += "\n"
            for emoji in ("🔴", "🟡", "🟢", "⚪"):
                if rest_counts[emoji]:
                    message += f"{RLM}{emoji} {rest_counts[emoji]} מטלות נוספות\n"
            message += "\n"

        if overdue_items:
            message += f"\n{RLM}⚠️ *פספסת להגיש* ⚠️\n"
            for a, emoji in overdue_items:
                message += fmt_block(a, emoji)
            message += f"{RLM}• - - - - - - - - - - - - - - - - - - - - •\n"

    send_text(to, message)

    if full_view or len(open_items) <= 3:
        send_buttons(to, f"{RLM}מה תרצה לעשות?", [
            {"id": "back_main", "title": "⬅️ תפריט ראשי"},
        ])
    else:
        course_key = str(course_id) if course_id is not None else "all"
        send_buttons(to, f"{RLM}מה תרצה לעשות?", [
            {"id": f"show_all_{course_key}", "title": "📋 הצג את כל המטלות"},
            {"id": "back_main",              "title": "⬅️ תפריט ראשי"},
        ])
