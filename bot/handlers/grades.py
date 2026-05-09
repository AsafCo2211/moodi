"""
הנדלר לציונים — בחירת קורס והצגת ציונים.
מכיל את כל הלוגיקה הקשורה לתצוגת ציונים ב-WhatsApp.
"""

import re

from database import get_connection
from bot.sender import send_text, send_buttons, send_list
from utils.course_namer import get_short_name
from utils.logger import get_logger

logger = get_logger(__name__)

RLM = "‏"


def parse_max_grade(grade_range: str):
    """
    מחלץ את הציון המקסימלי ממחרוזת טווח ציון.

    Args:
        grade_range: מחרוזת כמו '0–100' או '0-10'.

    Returns:
        הציון המקסימלי כ-float, או None אם לא ניתן לחלץ.
    """
    if not grade_range:
        return None
    parts = re.split(r'[–\-]', grade_range)
    if len(parts) >= 2:
        try:
            return float(parts[-1].strip())
        except ValueError:
            pass
    return None


async def show_grades(to: str, user_id: int):
    """
    שולח למשתמש תפריט בחירת קורס לצפייה בציונים.

    Args:
        to: מספר הטלפון של המשתמש.
        user_id: מזהה המשתמש ב-DB.
    """
    from bot.menu import send_main_menu

    conn = get_connection()
    courses = conn.execute("""
        SELECT DISTINCT uc.course_id, uc.course_name
        FROM user_courses uc
        LEFT JOIN user_course_settings ucs
          ON uc.user_id = ucs.user_id AND uc.course_id = ucs.course_id
        WHERE uc.user_id = ? AND COALESCE(ucs.is_active, 1) = 1
        AND EXISTS (
            SELECT 1 FROM grades g
            WHERE g.user_id = uc.user_id AND g.course_name = uc.course_name
        )
        ORDER BY uc.added_at DESC
    """, (user_id,)).fetchall()
    conn.close()

    if not courses:
        send_text(to, f"{RLM}אין ציונים עדיין 📊")
        send_main_menu(to, "")
        return

    rows = []
    for c in courses[:9]:
        short = get_short_name(c["course_id"], c["course_name"].strip())
        rows.append({"id": f"grades_course_{c['course_id']}", "title": short})

    send_list(
        to=to,
        message=f"{RLM}באיזה קורס תרצה לראות ציונים?",
        button_text="בחר קורס",
        sections=[{"title": "הקורסים שלך", "rows": rows}]
    )


async def show_grades_for_course(to: str, user_id: int, course_id: int):
    """
    מציג את כל הציונים של המשתמש בקורס ספציפי.

    Args:
        to: מספר הטלפון של המשתמש.
        user_id: מזהה המשתמש ב-DB.
        course_id: מזהה הקורס ב-Moodle.
    """
    conn = get_connection()
    course_row = conn.execute(
        "SELECT course_name FROM user_courses WHERE course_id = ? AND user_id = ?",
        (course_id, user_id)
    ).fetchone()
    course_name = course_row["course_name"] if course_row else ""
    grades = conn.execute("""
        SELECT item_name, grade, grade_range
        FROM grades
        WHERE user_id = ? AND course_name = ?
        ORDER BY detected_at DESC
    """, (user_id, course_name)).fetchall()
    conn.close()

    if not grades:
        send_text(to, f"{RLM}אין ציונים לקורס זה עדיין 📊")
        await show_grades(to, user_id)
        return

    message = f"{RLM}🎓 *ציונים — {course_name.strip()}*\n\n"
    for g in grades:
        max_g = parse_max_grade(g["grade_range"])
        grade_display = f"{g['grade']:.0f} / {max_g:.0f}" if max_g else f"{g['grade']:.0f}"
        message += (
            f"{RLM}• 📝 *{g['item_name']}*\n"
            f"{RLM}         📊 *ציון:* *{grade_display}*\n\n"
        )

    send_text(to, message)
    send_buttons(to, f"{RLM}מה תרצה לעשות?", [
        {"id": "back_grades", "title": "⬅️ חזור לקורסים"},
        {"id": "back_main",   "title": "🏠 תפריט ראשי"},
    ])
