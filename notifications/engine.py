from database import get_connection
from bot.sender import send_text
from datetime import datetime, date
from utils.logger import get_logger
import re

RLM = "‏"

logger = get_logger(__name__)


def parse_max_grade(grade_range: str) -> float | None:
    try:
        parts = re.split(r'[–\-]', grade_range)
        return float(parts[-1].strip())
    except Exception:
        return None


def get_active_users() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT id, phone_number, first_name FROM users WHERE is_active = 1 AND wstoken IS NOT NULL"
    ).fetchall()
    conn.close()
    return [{"user_id": r["id"], "phone_number": r["phone_number"], "first_name": r["first_name"]} for r in rows]


def send_new_assignment_notifications(user_id: int, phone_number: str):
    conn = get_connection()
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT moodle_assign_id, course_name, assignment_name, due_date "
        "FROM assignments WHERE user_id = ? AND notified_new = 0",
        (user_id,)
    ).fetchall()
    conn.close()

    for row in rows:
        try:
            if row["due_date"]:
                dt = datetime.fromisoformat(row["due_date"])
                due_line = f"{RLM}📅 מועד הגשה: {dt.strftime('%d/%m/%y | %H:%M')}"
            else:
                due_line = f"{RLM}📅 מועד הגשה: ללא תאריך"

            message = (
                f"{RLM}📋 מטלה חדשה ב{row['course_name']}!\n"
                f"{RLM}{row['assignment_name']}\n"
                f"{due_line}"
            )
            send_text(phone_number, message)

            conn2 = get_connection()
            conn2.execute(
                "UPDATE assignments SET notified_new=1 WHERE user_id=? AND moodle_assign_id=?",
                (user_id, row["moodle_assign_id"])
            )
            conn2.commit()
            conn2.close()
        except Exception as e:
            logger.error(f"Error notifying new assignment {row['moodle_assign_id']} for user {user_id}: {e}")


def send_due_date_changed_notifications(user_id: int, phone_number: str):
    """
    שולח התראה על מועד הגשה שהוארך על ידי הפרופסור.

    מחפש מטלות עם notified_due_changed=0, שולח הודעת WhatsApp עם המועד החדש,
    ומעדכן את הדגל ל-1 לאחר שליחה מוצלחת.
    """
    conn = get_connection()
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT moodle_assign_id, course_name, assignment_name, due_date "
        "FROM assignments WHERE user_id = ? AND notified_due_changed = 0",
        (user_id,)
    ).fetchall()
    conn.close()

    for row in rows:
        try:
            if row["due_date"]:
                dt = datetime.fromisoformat(row["due_date"])
                due_line = f"{RLM}📅 מועד חדש: {dt.strftime('%d/%m/%y | %H:%M')}"
            else:
                due_line = f"{RLM}📅 מועד חדש: ללא תאריך"

            message = (
                f"{RLM}📅 מועד הגשה עודכן ב{row['course_name']}!\n"
                f"{RLM}{row['assignment_name']}\n"
                f"{due_line}"
            )
            send_text(phone_number, message)
            send_buttons(phone_number, f"{RLM}מה תרצה לעשות?", [
                {"id": "back_main", "title": "⬅️ תפריט ראשי"}
            ])

            conn2 = get_connection()
            conn2.execute(
                "UPDATE assignments SET notified_due_changed=1 WHERE user_id=? AND moodle_assign_id=?",
                (user_id, row["moodle_assign_id"])
            )
            conn2.commit()
            conn2.close()
        except Exception as e:
            logger.error(f"Error notifying due date change {row['moodle_assign_id']} for user {user_id}: {e}")


def send_new_grade_notifications(user_id: int, phone_number: str):
    conn = get_connection()
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT course_name, item_name, grade, grade_range "
        "FROM grades WHERE user_id = ? AND notified = 0",
        (user_id,)
    ).fetchall()
    conn.close()

    for row in rows:
        try:
            max_grade = parse_max_grade(row["grade_range"] or "")
            if max_grade is not None:
                grade_display = f"{row['grade']:.0f}/{max_grade:.0f}"
            else:
                grade_display = f"{row['grade']:.0f}"

            message = (
                f"{RLM}🎓 ציון חדש ב{row['course_name']}!\n"
                f"{RLM}{row['item_name']}: {grade_display}"
            )
            send_text(phone_number, message)
            send_buttons(phone_number, f"{RLM}מה תרצה לעשות?", [
                {"id": "back_main", "title": "⬅️ תפריט ראשי"}
            ])

            conn2 = get_connection()
            conn2.execute(
                "UPDATE grades SET notified=1 WHERE user_id=? AND course_name=? AND item_name=?",
                (user_id, row["course_name"], row["item_name"])
            )
            conn2.commit()
            conn2.close()
        except Exception as e:
            logger.error(f"Error notifying grade for user {user_id}: {e}")


def send_morning_summary():
    users = get_active_users()
    today_str = date.today().isoformat()
    today_pattern = f"{today_str}%"

    for user in users:
        try:
            conn = get_connection()
            cursor = conn.cursor()
            rows = cursor.execute(
                "SELECT assignment_name, due_date FROM assignments "
                "WHERE user_id = ? AND is_submitted = 0 AND notified_today = 0 AND due_date LIKE ? "
                "ORDER BY due_date ASC",
                (user["user_id"], today_pattern)
            ).fetchall()
            conn.close()

            if not rows:
                continue

            lines = []
            for row in rows:
                dt = datetime.fromisoformat(row["due_date"])
                time_str = dt.strftime("%H:%M")
                lines.append(f"{RLM}• {row['assignment_name']}\n{RLM}\t     👈 להגיש עד השעה {time_str}")

            message = (
                f"{RLM}בוקר טוב {user['first_name']} 😄\n"
                f"{RLM}אני מקווה שאנחנו כבר אחרי הקפה של הבוקר? ☕️ יש לנו כמה דברים חשובים להיום.\n\n"
                f"{RLM}לא לשכוח שיש להגיש את המטלות הבאות היום:\n\n"
                + "\n".join(lines) + "\n\n"
                + f"{RLM}שיהיה לנו יום יעיל ואפקטיבי, וכמובן שמוודי פה לכל שאלה 😄"
            )
            send_text(user["phone_number"], message)
            send_buttons(user["phone_number"], f"{RLM}המטלות שלי", [
                {"id": "back_main", "title": "⬅️ תפריט ראשי"}
            ])

            conn2 = get_connection()
            conn2.execute(
                "UPDATE assignments SET notified_today=1 "
                "WHERE user_id=? AND is_submitted=0 AND due_date LIKE ?",
                (user["user_id"], today_pattern)
            )
            conn2.commit()
            conn2.close()
        except Exception as e:
            logger.error(f"Error in morning summary for user {user['user_id']}: {e}")


def send_evening_reminder():
    users = get_active_users()
    today_str = date.today().isoformat()
    today_pattern = f"{today_str}%"

    for user in users:
        try:
            conn = get_connection()
            cursor = conn.cursor()
            rows = cursor.execute(
                "SELECT assignment_name, due_date FROM assignments "
                "WHERE user_id = ? AND is_submitted = 0 AND notified_evening = 0 AND due_date LIKE ? "
                "ORDER BY due_date ASC",
                (user["user_id"], today_pattern)
            ).fetchall()
            conn.close()

            if not rows:
                continue

            lines = []
            for row in rows:
                dt = datetime.fromisoformat(row["due_date"])
                time_str = dt.strftime("%H:%M")
                lines.append(f"{RLM}• {row['assignment_name']}\n{RLM}\t     👈 להגיש עד השעה {time_str}")

            message = (
                f"{RLM}היי {user['first_name']}, אני מאמין שהיה יום עמוס..\n\n"
                f"{RLM}אני פה כדי להזכיר שעדיין לא הגשת את המטלות הבאות:\n\n"
                + "\n".join(lines) + "\n\n"
                + f"{RLM}מזכיר שההגשה של המטלות האלו היא להיום."
            )
            send_text(user["phone_number"], message)
            send_buttons(user["phone_number"], f"{RLM}המטלות שלי", [
                {"id": "back_main", "title": "⬅️ תפריט ראשי"}
            ])

            conn2 = get_connection()
            conn2.execute(
                "UPDATE assignments SET notified_evening=1 "
                "WHERE user_id=? AND is_submitted=0 AND due_date LIKE ?",
                (user["user_id"], today_pattern)
            )
            conn2.commit()
            conn2.close()
        except Exception as e:
            logger.error(f"Error in evening reminder for user {user['user_id']}: {e}")


def reset_daily_flags():
    today_str = date.today().isoformat()
    conn = get_connection()
    conn.execute(
        "UPDATE assignments SET notified_today = 0, notified_evening = 0 WHERE due_date >= ?",
        (today_str,)
    )
    conn.execute(
        "UPDATE personal_tasks SET status='done' "
        "WHERE due_datetime < datetime('now', '-1 hour') AND status='open'"
    )
    conn.execute("""
        DELETE FROM task_reminders
        WHERE task_id IN (
            SELECT id FROM personal_tasks
            WHERE status IN ('deleted', 'done')
        )
    """)
    conn.execute("""
        DELETE FROM personal_tasks
        WHERE status IN ('deleted', 'done')
        AND created_at < datetime('now', '-7 days')
    """)
    conn.commit()
    conn.close()
    logger.info(f"Daily flags reset and personal task cleanup done at {datetime.now()}")
