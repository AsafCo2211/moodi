import threading
from bot.sender import send_text, send_buttons, send_list
from database import get_connection
from datetime import datetime
import re
from utils.course_namer import get_short_name

RLM = "\u200f"


def get_user(phone_number: str):
    conn = get_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE phone_number = ?", (phone_number,)
    ).fetchone()
    conn.close()
    return user


def get_first_name(user) -> str:
    if user and user["first_name"]:
        return user["first_name"]
    return ""


def assignment_emoji(due_date_str: str) -> str:
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


def format_assignment(a) -> str:
    emoji = assignment_emoji(a["due_date"])
    due_str = format_due_date(a["due_date"])

    # ניקוי רווחים מיותרים מהדאטה של Moodle
    course_name = a['course_name'].strip()
    assignment_name = a['assignment_name'].strip()

    return (
        f"{RLM}• - - - - - - - - - - - - - - - - - - - - •\n"
        ##f"{RLM}───────────────\n"
        f"{RLM}📖 *{course_name}*\n\n"
        ##f"{RLM}📖 `({a['course_name']})`\n\n"
        #f"{RLM}{emoji} *בתאריך*: {due_str}\n\n"
        f"{RLM}📋 *מטלה*: {assignment_name}\n\n"
        ##f"{RLM}📋 *שם*: *{a['assignment_name']}*\n\n"
        #f"{RLM}📖 `({a['course_name']})`\n"
        f"{RLM}{emoji} *מועד הגשה*: {due_str}\n"
        ##f"{RLM}{emoji} *בתאריך*: {due_str}\n"
    )


def get_active_courses(user_id: int) -> list:
    """מחזיר רק קורסים פעילים של המשתמש"""
    conn = get_connection()
    courses = conn.execute("""
        SELECT DISTINCT course_name
        FROM assignments
        WHERE user_id = ?
        AND (due_date IS NULL OR due_date > ?)
        ORDER BY due_date ASC
    """, (user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))).fetchall()
    conn.close()
    return [c["course_name"] for c in courses]


async def handle_message(from_number: str, msg_type: str, content: str):
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
                INSERT INTO users (phone_number, moodle_user_id, wstoken, first_name, is_active)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(phone_number) DO UPDATE SET
                    wstoken=excluded.wstoken,
                    moodle_user_id=excluded.moodle_user_id,
                    first_name=excluded.first_name,
                    is_active=1
            """, (from_number, row["moodle_user_id"], row["wstoken"], first_name))
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
                from moodle.poller import poll_user_on_demand
                poll_user_on_demand(user_id, skip_notifications=True)
                conn2 = get_connection()
                conn2.execute("UPDATE assignments SET notified_new=1 WHERE user_id=?", (user_id,))
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

        send_main_menu(from_number, name)
        return

    if not user:
        return

    if msg_type == "button":
        if content == "back_main":
            send_main_menu(from_number, name)
        elif content == "menu_other":
            send_text(from_number, f"{RLM}במה אוכל לעזור? שלח לי הודעה חופשית 💬")
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
        elif content == "menu_today":
            await show_today(from_number, user["id"])
        elif content == "menu_dashboard":
            await send_dashboard_link(from_number, user["id"])
        elif content == "menu_other":
            send_text(from_number, f"{RLM}במה אוכל לעזור? שלח לי הודעה חופשית 💬")
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


async def send_dashboard_link(phone_number: str, user_id: int):
    import random
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


def send_main_menu(to: str, name: str):
    send_list(
        to=to,
        message=f"{RLM}היי {name} 👋, במה אני יכול לעזור לך היום?",
        button_text="בחר אפשרות",
        sections=[{
            "title": "התפריט הראשי",
            "rows": [
                {"id": "menu_assignments", "title": "📋 המטלות שלי"},
                {"id": "menu_grades", "title": "🎓 ציונים בקורסים"},
                {"id": "menu_today", "title": "📅 להגשה היום"},
                {"id": "menu_dashboard", "title": "🖥️ הדאשבורד שלי"},
                {"id": "menu_other", "title": "💬 עניין אחר"},
            ]
        }]
    )


async def show_course_selection(to: str, user_id: int):
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
    name = get_first_name(user) if user else ""
    conn = get_connection()

    if course_id is None:
        rows = conn.execute("""
            SELECT course_name, assignment_name, due_date
            FROM assignments
            WHERE user_id = ?
              AND is_submitted = 0
            ORDER BY
                CASE WHEN due_date IS NULL THEN 1 ELSE 0 END ASC,
                due_date ASC
        """, (user_id,)).fetchall()
        course_header = None
    else:
        course_name_row = conn.execute(
            "SELECT course_name FROM user_courses WHERE course_id = ? AND user_id = ?",
            (course_id, user_id)
        ).fetchone()
        course_header = course_name_row["course_name"]
        rows = conn.execute("""
            SELECT course_name, assignment_name, due_date
            FROM assignments
            WHERE user_id = ?
              AND course_name = ?
              AND is_submitted = 0
            ORDER BY
                CASE WHEN due_date IS NULL THEN 1 ELSE 0 END ASC,
                due_date ASC
        """, (user_id, course_header)).fetchall()
    conn.close()

    # Categorise by date (not by seconds)
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

    # Pair each assignment with its display emoji
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

    # Header
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


def parse_max_grade(grade_range: str):
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


async def show_today(to: str, user_id: int):
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_connection()
    assignments = conn.execute("""
        SELECT course_name, assignment_name, due_date
        FROM assignments
        WHERE user_id = ?
        AND due_date LIKE ?
        AND is_submitted = 0
        ORDER BY due_date ASC
    """, (user_id, f"{today}%")).fetchall()
    name_row = conn.execute("SELECT first_name FROM users WHERE id = ?", (user_id,)).fetchone()
    name = get_first_name(name_row) if name_row else ""
    conn.close()

    if not assignments:
        send_text(to, f"{RLM}✅ אין לך מטלות להגשה היום. תהנה!")
        send_main_menu(to, name)
        return

    message = f"{RLM}📅 *מטלות להגשה היום:*\n"
    for a in assignments:
        message += format_assignment(a)
    message += f"{RLM}───────────────"

    send_text(to, message)
    send_buttons(to, f"{RLM}מה תרצה לעשות?", [
        {"id": "back_main", "title": "⬅️ תפריט ראשי"},
    ])