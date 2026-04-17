from bot.sender import send_main_menu, send_text
from database import get_connection
from datetime import datetime


async def handle_message(from_number: str, msg_type: str, content: str):
    """
    הלוגיקה המרכזית של הבוט.
    מקבל הודעה ומחליט מה לענות.
    """
    conn = get_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE phone_number = ?", (from_number,)
    ).fetchone()
    conn.close()

    # משתמש לא רשום
    if not user:
        send_text(from_number, "היי! 👋 אני מודי, העוזר האישי שלך למודל.\nכדי להתחיל שלח לי את קוד ההרשמה שקיבלת.")
        return

    # תפריט ראשי — כל הודעת טקסט שאין לה תואם
    if msg_type == "text":
        send_main_menu(from_number, user["phone_number"])
        return

    # טיפול בכפתורים
    if msg_type == "button":

        if content == "menu_assignments":
            await show_assignments(from_number, user["id"])

        elif content == "menu_grades":
            await show_grades(from_number, user["id"])

        elif content == "menu_today":
            await show_today(from_number, user["id"])


async def show_assignments(to: str, user_id: int):
    """מציג מטלות פתוחות ממוינות לפי תאריך"""
    conn = get_connection()
    assignments = conn.execute("""
        SELECT course_name, assignment_name, due_date
        FROM assignments
        WHERE user_id = ?
        AND (due_date IS NULL OR due_date > ?)
        ORDER BY due_date ASC
        LIMIT 10
    """, (user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))).fetchall()
    conn.close()

    if not assignments:
        send_text(to, "🎉 אין לך מטלות פתוחות כרגע!")
        return

    message = "📋 *המטלות הפתוחות שלך:*\n\n"
    for a in assignments:
        due = datetime.strptime(a["due_date"], '%Y-%m-%d %H:%M:%S') if a["due_date"] else None
        due_str = due.strftime('%d/%m/%y %H:%M') if due else "ללא תאריך"
        message += f"📝 *{a['assignment_name']}*\n"
        message += f"   {a['course_name']}\n"
        message += f"   ⏰ {due_str}\n\n"

    send_text(to, message)


async def show_grades(to: str, user_id: int):
    """מציג ציונים אחרונים"""
    conn = get_connection()
    grades = conn.execute("""
        SELECT course_name, item_name, grade
        FROM grades
        WHERE user_id = ?
        ORDER BY detected_at DESC
        LIMIT 10
    """, (user_id,)).fetchall()
    conn.close()

    if not grades:
        send_text(to, "אין ציונים עדיין.")
        return

    message = "🎓 *הציונים האחרונים שלך:*\n\n"
    for g in grades:
        message += f"📊 *{g['item_name']}*\n"
        message += f"   {g['course_name']}\n"
        message += f"   ציון: {g['grade']}\n\n"

    send_text(to, message)


async def show_today(to: str, user_id: int):
    """מציג מטלות להגשה היום"""
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_connection()
    assignments = conn.execute("""
        SELECT course_name, assignment_name, due_date
        FROM assignments
        WHERE user_id = ?
        AND due_date LIKE ?
        AND is_submitted = 0
    """, (user_id, f"{today}%")).fetchall()
    conn.close()

    if not assignments:
        send_text(to, "✅ אין לך מטלות להגשה היום. תהנה!")
        return

    message = "📅 *מטלות להגשה היום:*\n\n"
    for a in assignments:
        due = datetime.strptime(a["due_date"], '%Y-%m-%d %H:%M:%S')
        message += f"📝 *{a['assignment_name']}*\n"
        message += f"   {a['course_name']}\n"
        message += f"   ⏰ עד {due.strftime('%H:%M')}\n\n"

    send_text(to, message)