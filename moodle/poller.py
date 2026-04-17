import sqlite3
from datetime import datetime
from database import get_connection
from moodle.client import get_assignments, get_grades, get_grades_table
from moodle.parser import parse_assignments, parse_grades, parse_grades_table


def save_grades(cursor, user_id: int, grades: list):
    """שומר ציונים ל-DB, מזהה ציונים חדשים ועדכונים."""
    for grade in grades:
        existing = cursor.execute("""
            SELECT grade FROM grades 
            WHERE user_id = ? AND course_name = ? AND item_name = ?
        """, (user_id, grade["course_name"], grade["item_name"])).fetchone()

        if existing is None:
            cursor.execute("""
                INSERT INTO grades (user_id, course_name, item_name, grade)
                VALUES (?, ?, ?, ?)
            """, (user_id, grade["course_name"], grade["item_name"], grade["grade"]))

        elif existing["grade"] != grade["grade"]:
            cursor.execute("""
                UPDATE grades 
                SET grade = ?, notified = 0, detected_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND course_name = ? AND item_name = ?
            """, (grade["grade"], user_id, grade["course_name"], grade["item_name"]))


def poll_user(user_id: int, moodle_user_id: int, wstoken: str, course_ids: list, course_map: dict):
    """
    סורק מטלות וציונים עבור משתמש אחד.
    course_map: {course_id: course_name}
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # --- מטלות ---
        raw_assignments = get_assignments(wstoken, course_ids)
        assignments = parse_assignments(raw_assignments)

        for assign in assignments:
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO assignments 
                    (user_id, moodle_assign_id, course_name, assignment_name, due_date)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    user_id,
                    assign["moodle_assign_id"],
                    assign["course_name"],
                    assign["assignment_name"],
                    assign["due_date"]
                ))
            except sqlite3.IntegrityError:
                pass

        # --- ציונים ---
        for course_id in course_ids:
            course_name = course_map.get(course_id, "")
            grades = []

            # ניסיון ראשון — API סטנדרטי
            try:
                raw_grades = get_grades(wstoken, moodle_user_id, course_id)
                grades = parse_grades(raw_grades, course_name)
            except Exception:
                pass

            # אם לא קיבלנו ציונים — fallback לגרסה החלופית
            if not grades:
                try:
                    raw_table = get_grades_table(wstoken, moodle_user_id, course_id)
                    grades = parse_grades_table(raw_table, course_name)
                except Exception as e:
                    print(f"  Skipping grades for {course_name}: {e}")
                    continue

            save_grades(cursor, user_id, grades)

        conn.commit()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Polled user {user_id} successfully")

    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error polling user {user_id}: {e}")
        conn.rollback()

    finally:
        conn.close()


def poll_all_users():
    """
    סורק את כל המשתמשים הפעילים במערכת.
    זו הפונקציה שה-Cron job יקרא לה כל 5 דקות.
    """
    conn = get_connection()
    cursor = conn.cursor()

    users = cursor.execute("""
        SELECT u.id, u.wstoken, u.moodle_user_id,
               uc.course_id, uc.course_name
        FROM users u
        JOIN user_courses uc ON u.id = uc.user_id
        WHERE u.is_active = 1 AND u.wstoken IS NOT NULL
    """).fetchall()

    conn.close()

    # קבץ לפי משתמש
    user_data = {}
    for row in users:
        uid = row["id"]
        if uid not in user_data:
            user_data[uid] = {
                "wstoken": row["wstoken"],
                "moodle_user_id": row["moodle_user_id"],
                "course_ids": [],
                "course_map": {}
            }
        user_data[uid]["course_ids"].append(row["course_id"])
        user_data[uid]["course_map"][row["course_id"]] = row["course_name"]

    for uid, data in user_data.items():
        poll_user(
            user_id=uid,
            moodle_user_id=data["moodle_user_id"],
            wstoken=data["wstoken"],
            course_ids=data["course_ids"],
            course_map=data["course_map"]
        )