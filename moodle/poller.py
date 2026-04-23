import sqlite3
from datetime import datetime
from database import get_connection
from moodle.client import get_assignments, get_grades, get_grades_table
from moodle.parser import parse_assignments, parse_grades, parse_grades_table


def seed_user_courses_if_empty(cursor, user_id: int, wstoken: str, moodle_user_id: int):
    """If user has no courses in user_courses, fetch from Moodle and insert."""
    count = cursor.execute(
        "SELECT COUNT(*) FROM user_courses WHERE user_id = ?", (user_id,)
    ).fetchone()[0]

    if count > 0:
        return

    from moodle.client import get_user_courses
    from moodle.parser import parse_courses

    raw = get_user_courses(wstoken, moodle_user_id)
    courses = parse_courses(raw)

    for c in courses:
        cursor.execute("""
            INSERT OR IGNORE INTO user_courses (user_id, course_id, course_name)
            VALUES (?, ?, ?)
        """, (user_id, c["id"], c["name"]))

    print(f"[seed] Inserted {len(courses)} courses for user {user_id}")

    from moodle.client import call_moodle
    try:
        site_info = call_moodle(wstoken, 'core_webservice_get_site_info', {})
        full_name = site_info.get('fullname', '')
        first_name = full_name.split()[0] if full_name else ''
        cursor.execute(
            "UPDATE users SET first_name = ? WHERE id = ?",
            (first_name, user_id)
        )
        print(f"  [seed] Saved name: {first_name}")
    except Exception:
        pass


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


def sync_submission_statuses(cursor, user_id: int, wstoken: str):
    """
    Checks and updates submission status for all unsubmitted assignments
    whose due_date has passed. Called only from the 5-minute scheduler cycle.
    """
    from moodle.client import get_submission_status

    overdue = cursor.execute("""
        SELECT moodle_assign_id FROM assignments
        WHERE user_id = ?
        AND is_submitted = 0
    """, (user_id,)).fetchall()

    print(f"  → Checking submission status for {len(overdue)} unsubmitted assignments")

    for row in overdue:
        status = get_submission_status(wstoken, row["moodle_assign_id"])
        if status == "submitted":
            cursor.execute("""
                UPDATE assignments SET is_submitted = 1
                WHERE user_id = ? AND moodle_assign_id = ?
            """, (user_id, row["moodle_assign_id"]))
            print(f"  [submit] Marked assign {row['moodle_assign_id']} as submitted")


def poll_user(user_id: int, moodle_user_id: int, wstoken: str, course_ids: list, course_map: dict):
    """
    סורק מטלות וציונים עבור משתמש אחד.
    course_map: {course_id: course_name}
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Polling user {user_id} — {len(course_ids)} courses")
        seed_user_courses_if_empty(cursor, user_id, wstoken, moodle_user_id)
        conn.commit()
        if not course_ids:
            rows = cursor.execute(
                "SELECT course_id, course_name FROM user_courses WHERE user_id = ?", (user_id,)
            ).fetchall()
            course_ids = [r["course_id"] for r in rows]
            course_map = {r["course_id"]: r["course_name"] for r in rows}

        # --- מטלות ---
        raw_assignments = get_assignments(wstoken, course_ids)
        assignments = parse_assignments(raw_assignments)
        print(f"  → {len(assignments)} assignments fetched")

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

            print(f"  → {course_name}: {len(grades)} grades")
            save_grades(cursor, user_id, grades)

        sync_submission_statuses(cursor, user_id, wstoken)
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
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting scheduled poll for all users")
    conn = get_connection()
    cursor = conn.cursor()

    # Seed courses for active users who have none yet
    users_to_seed = cursor.execute("""
        SELECT id, wstoken, moodle_user_id FROM users
        WHERE is_active = 1 AND wstoken IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM user_courses WHERE user_id = users.id)
    """).fetchall()

    for u in users_to_seed:
        seed_user_courses_if_empty(cursor, u["id"], u["wstoken"], u["moodle_user_id"])

    if users_to_seed:
        conn.commit()

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

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Scheduled poll complete")


def poll_user_on_demand(user_id: int):
    """
    Polls a single user immediately.
    Called as a background task when a user sends a message.
    Fetches their courses from user_courses table and polls assignments + grades.
    """
    conn = get_connection()
    cursor = conn.cursor()

    user = cursor.execute(
        "SELECT id, wstoken, moodle_user_id FROM users "
        "WHERE id = ? AND is_active = 1 AND wstoken IS NOT NULL",
        (user_id,)
    ).fetchone()

    if not user:
        conn.close()
        return

    seed_user_courses_if_empty(cursor, user["id"], user["wstoken"], user["moodle_user_id"])
    conn.commit()

    rows = cursor.execute("""
        SELECT u.id, u.wstoken, u.moodle_user_id,
               uc.course_id, uc.course_name
        FROM users u
        JOIN user_courses uc ON u.id = uc.user_id
        WHERE u.id = ? AND u.is_active = 1 AND u.wstoken IS NOT NULL
    """, (user_id,)).fetchall()
    conn.close()

    if not rows:
        return

    course_ids = [r["course_id"] for r in rows]
    course_map = {r["course_id"]: r["course_name"] for r in rows}
    wstoken = rows[0]["wstoken"]
    moodle_user_id = rows[0]["moodle_user_id"]

    poll_user(user_id, moodle_user_id, wstoken, course_ids, course_map)