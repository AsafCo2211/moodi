from bot.sender import send_text, send_buttons, send_list
from database import get_connection
from datetime import datetime
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
    return "אסף"


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

    if not user:
        send_text(from_number,
            f"{RLM}היי! 👋 אני מודי, העוזר האישי שלך למודל.\n"
            f"{RLM}כדי להתחיל שלח לי את קוד ההרשמה שקיבלת."
        )
        return

    if msg_type == "text":
        send_main_menu(from_number, name)
        return

    if msg_type == "button":
        if content == "back_main":
            send_main_menu(from_number, name)
        elif content == "menu_other":
            send_text(from_number, f"{RLM}במה אוכל לעזור? שלח לי הודעה חופשית 💬")

    elif msg_type == "list":
        if content == "menu_assignments":
            await show_course_selection(from_number, user["id"])
        elif content == "menu_grades":
            await show_grades(from_number, user["id"])
        elif content == "menu_today":
            await show_today(from_number, user["id"])
        elif content == "menu_other":
            send_text(from_number, f"{RLM}במה אוכל לעזור? שלח לי הודעה חופשית 💬")
        elif content == "back_main":
            send_main_menu(from_number, name)
        elif content == "course_all":
            await show_assignments(from_number, user["id"], None)
        elif content.startswith("course_"):
            course_id = int(content.replace("course_", ""))
            await show_assignments(from_number, user["id"], course_id)


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
                {"id": "menu_other", "title": "💬 עניין אחר"},
            ]
        }]
    )


async def show_course_selection(to: str, user_id: int):
    conn = get_connection()
    courses = conn.execute("""
    SELECT DISTINCT uc.course_id, uc.course_name
    FROM user_courses uc
    WHERE uc.user_id = ?
    AND EXISTS (
        SELECT 1 FROM assignments a
        WHERE a.user_id = uc.user_id
        AND a.course_name = uc.course_name
        AND (a.due_date IS NULL OR a.due_date > ?)
    )
    ORDER BY uc.added_at DESC
""", (user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))).fetchall()
    conn.close()

    if not courses:
        send_text(to, f"{RLM}🎉 אין לך מטלות פתוחות כרגע!")
        send_main_menu(to, "אסף")
        return

    rows = [{"id": "course_all", "title": "📋 כל הקורסים"}]
    for c in courses[:9]:
        short = get_short_name(c["course_id"], c["course_name"].strip())
        rows.append({
            "id": f"course_{c['course_id']}",
            "title": short
        })

    send_list(
        to=to,
        message=f"{RLM}באיזה קורס תרצה לראות מטלות?",
        button_text="בחר קורס",
        sections=[{"title": "הקורסים שלך", "rows": rows}]
    )


async def show_assignments(to: str, user_id: int, course_id):
    """מציג מטלות — כל הקורסים או קורס ספציפי"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_connection()

    if course_id is None:
        assignments = conn.execute("""
            SELECT course_name, assignment_name, due_date
            FROM assignments
            WHERE user_id = ?
            AND (due_date IS NULL OR due_date > ?)
            ORDER BY 
                CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
                due_date ASC
        """, (user_id, now)).fetchall()
    else:
        course_name = conn.execute(
            "SELECT course_name FROM user_courses WHERE course_id = ? AND user_id = ?",
            (course_id, user_id)
        ).fetchone()["course_name"]

        assignments = conn.execute("""
            SELECT course_name, assignment_name, due_date
            FROM assignments
            WHERE user_id = ?
            AND course_name = ?
            AND (due_date IS NULL OR due_date > ?)
            ORDER BY
                CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
                due_date ASC
        """, (user_id, course_name, now)).fetchall()
    conn.close()

    if not assignments:
        send_text(to, f"{RLM}🎉 אין מטלות פתוחות!")
        send_main_menu(to, "אסף")
        return

    message = f"{RLM}📋 *המטלות הפתוחות שלך:*\n\n"
    for a in assignments:
        message += format_assignment(a)
    message += f"{RLM}• - - - - - - - - - - - - - - - - - - - - •"

    send_text(to, message)
    send_buttons(to, f"{RLM}מה תרצה לעשות?", [
        {"id": "back_main", "title": "⬅️ תפריט ראשי"},
    ])


async def show_grades(to: str, user_id: int):
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
        send_text(to, f"{RLM}אין ציונים עדיין 📊")
        send_main_menu(to, "אסף")
        return

    message = f"{RLM}🎓 *הציונים האחרונים שלך:*\n\n"
    for g in grades:
        message += f"{RLM}───────────────\n"
        message += f"{RLM}📊 *{g['item_name']}*\n"
        message += f"{RLM}📖 `({g['course_name']})`\n"
        message += f"{RLM}✅ ציון: *{g['grade']}*\n"
    message += f"{RLM}───────────────"

    send_text(to, message)
    send_buttons(to, f"{RLM}מה תרצה לעשות?", [
        {"id": "back_main", "title": "⬅️ תפריט ראשי"},
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
    conn.close()

    if not assignments:
        send_text(to, f"{RLM}✅ אין לך מטלות להגשה היום. תהנה!")
        send_main_menu(to, "אסף")
        return

    message = f"{RLM}📅 *מטלות להגשה היום:*\n"
    for a in assignments:
        message += format_assignment(a)
    message += f"{RLM}───────────────"

    send_text(to, message)
    send_buttons(to, f"{RLM}מה תרצה לעשות?", [
        {"id": "back_main", "title": "⬅️ תפריט ראשי"},
    ])