"""
ניתוב הודעות WhatsApp — הלב של הבוט.
מקבל כל הודעה נכנסת ומפנה אותה להנדלר המתאים.
פונקציות עזר משותפות: get_user, get_first_name, send_main_menu.
"""

import threading
import re

from bot.sender import send_text, send_buttons, send_list
from database import get_connection
from moodle.poller import poll_user_on_demand
from utils.logger import get_logger
from bot.handlers.assignments import show_course_selection, show_assignments
from bot.handlers.grades import show_grades, show_grades_for_course
from bot.handlers.upcoming import show_upcoming_menu, show_upcoming
from bot.handlers.ai import handle_ai_request, handle_audio_message
from bot.handlers.dashboard import send_dashboard_link, send_status_report

logger = get_logger(__name__)

RLM = "‏"

GREETINGS = {
    "היי", "הי", "שלום", "הלו", "מה קורה", "מה נשמע",
    "בוקר טוב", "ערב טוב", "?", "מה", "ok", "אוקי", "היי מודי", "הי מודי", "שלום מודי", "הלו מודי",
    "מה קורה מודי", "מה נשמע מודי", "בוקר טוב מודי", "ערב טוב מודי", "מה שלומך", "מה שלומך?", "מה שלומך מודי", "מה שלומך מודי?", "הכל טוב", "הכל טוב?", "הכל טוב מודי", "הכל טוב מודי?"
}


def get_user(phone_number: str):
    """
    מחזיר את שורת המשתמש מה-DB לפי מספר טלפון.

    Args:
        phone_number: מספר הטלפון של המשתמש.

    Returns:
        שורת sqlite3.Row של המשתמש, או None אם לא נמצא.
    """
    conn = get_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE phone_number = ?", (phone_number,)
    ).fetchone()
    conn.close()
    return user


def get_first_name(user) -> str:
    """
    מחלץ את השם הפרטי מתוך שורת משתמש.

    Args:
        user: שורת sqlite3.Row של המשתמש, או None.

    Returns:
        השם הפרטי כמחרוזת, או מחרוזת ריקה אם לא קיים.
    """
    if user and user["first_name"]:
        return user["first_name"]
    return ""


def send_main_menu(to: str, name: str):
    """
    שולח את התפריט הראשי למשתמש.

    Args:
        to: מספר הטלפון של המשתמש.
        name: שם המשתמש לברכה.
    """
    send_list(
        to=to,
        message=f"{RLM}היי {name} 👋, במה אני יכול לעזור לך היום?",
        button_text="בחר אפשרות",
        sections=[{
            "title": "התפריט הראשי",
            "rows": [
                {"id": "menu_assignments", "title": "📋 המטלות שלי"},
                {"id": "menu_grades", "title": "🎓 ציונים בקורסים"},
                {"id": "menu_upcoming", "title": "📅 הגשות קרובות"},
                {"id": "menu_dashboard", "title": "🖥️ הדאשבורד שלי"},
                {"id": "menu_status", "title": "📊 דוח מצב"},
            ]
        }]
    )


async def handle_message(from_number: str, msg_type: str, content: str):
    """
    נקודת הכניסה המרכזית לכל הודעה נכנסת.
    מנתב לפי סוג ההודעה (טקסט, כפתור, רשימה, אודיו) ותוכנה.

    Args:
        from_number: מספר הטלפון של השולח.
        msg_type: סוג ההודעה — 'text', 'button', 'list', 'audio'.
        content: תוכן ההודעה (טקסט, מזהה כפתור/רשימה, או מזהה מדיה).
    """
    user = get_user(from_number)
    name = get_first_name(user) if user else ""

    if msg_type == "text":
        if re.match(r'^\d{6}$', content.strip()):
            conn = get_connection()
            row = conn.execute(
                "SELECT * FROM pending_registrations"
                " WHERE code = ? AND phone_number = ? AND expires_at > datetime('now')",
                (content.strip(), from_number),
            ).fetchone()
            conn.close()
            if not row:
                send_text(from_number, f"{RLM}❌ הקוד שגוי או פג תוקף. נסה להירשם מחדש.")
                return
            first_name = row["first_name"]
            conn = get_connection()
            conn.execute("""
                INSERT INTO users (phone_number, moodle_user_id, wstoken, first_name, private_token, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(phone_number) DO UPDATE SET
                    wstoken=excluded.wstoken,
                    moodle_user_id=excluded.moodle_user_id,
                    first_name=excluded.first_name,
                    private_token=excluded.private_token,
                    is_active=1
            """, (from_number, row["moodle_user_id"], row["wstoken"], first_name, row["private_token"]))
            conn.execute(
                "DELETE FROM pending_registrations WHERE code = ? AND phone_number = ?",
                (content.strip(), from_number),
            )
            conn.commit()
            user_row = conn.execute(
                "SELECT id FROM users WHERE phone_number = ?", (from_number,)
            ).fetchone()
            user_id = user_row["id"]
            conn.close()

            def _seed_and_welcome():
                poll_user_on_demand(user_id, skip_notifications=True)
                conn2 = get_connection()
                conn2.execute("UPDATE assignments SET notified_new=1, notified_due_changed=1 WHERE user_id=?", (user_id,))
                conn2.execute("UPDATE grades SET notified=1 WHERE user_id=?", (user_id,))
                conn2.commit()
                conn2.close()
                send_text(from_number, f"{RLM}✅ התחברת בהצלחה! היי {first_name} 👋")
                send_main_menu(from_number, first_name)

            threading.Thread(target=_seed_and_welcome, daemon=True).start()
            return

        if not user:
            send_text(from_number,
                f"{RLM}היי! 👋 אני מוודי, העוזר האישי שלך למודל.\n"
                f"{RLM}לחץ כאן כדי להתחיל:\n"
                f"{RLM}https://moodi.aitoolhub.blog/login?phone={from_number}"
            )
            return

        normalized = content.strip().lower()
        has_hebrew = bool(re.search(r'[֐-׿]', content))
        is_greeting = normalized in GREETINGS or len(content.split()) < 2
        if has_hebrew and not is_greeting:
            await handle_ai_request(from_number, content, user)
            return

        send_main_menu(from_number, name)
        return

    if not user:
        return

    if msg_type == "audio":
        await handle_audio_message(from_number, content, user)

    elif msg_type == "button":
        if content == "back_main":
            send_main_menu(from_number, name)
        elif content == "menu_other":
            send_text(from_number, f"{RLM}במה אוכל לעזור? 😊\n{RLM}כתוב לי חופשי או שלח הודעה קולית 🎤")
        elif content == "menu_status":
            await send_status_report(from_number, user["id"])
        elif content == "back_grades":
            await show_grades(from_number, user["id"])
        elif content.startswith("show_all_"):
            key = content.replace("show_all_", "")
            cid = None if key == "all" else int(key)
            await show_assignments(from_number, user["id"], cid, user=user, full_view=True)

    elif msg_type == "list":
        if content == "menu_assignments":
            await show_course_selection(from_number, user["id"])
        elif content == "menu_grades":
            await show_grades(from_number, user["id"])
        elif content == "menu_upcoming":
            await show_upcoming_menu(from_number, user["id"])
        elif content == "upcoming_today":
            await show_upcoming(from_number, user["id"], days=0)
        elif content == "upcoming_3days":
            await show_upcoming(from_number, user["id"], days=3)
        elif content == "upcoming_week":
            await show_upcoming(from_number, user["id"], days=7)
        elif content == "menu_dashboard":
            await send_dashboard_link(from_number, user["id"])
        elif content == "menu_other":
            send_text(from_number, f"{RLM}במה אוכל לעזור? 😊\n{RLM}כתוב לי חופשי או שלח הודעה קולית 🎤")
        elif content == "menu_status":
            await send_status_report(from_number, user["id"])
        elif content == "back_main":
            send_main_menu(from_number, name)
        elif content == "course_all":
            await show_assignments(from_number, user["id"], None, user=user)
        elif content.startswith("course_"):
            course_id = int(content.replace("course_", ""))
            await show_assignments(from_number, user["id"], course_id, user=user)
        elif content == "back_grades":
            await show_grades(from_number, user["id"])
        elif content.startswith("grades_course_"):
            course_id = int(content.replace("grades_course_", ""))
            await show_grades_for_course(from_number, user["id"], course_id)
