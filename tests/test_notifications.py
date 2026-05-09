import sqlite3
import pytest
from unittest.mock import patch
from datetime import datetime, date, timedelta

from notifications.engine import (
    send_morning_summary,
    send_evening_reminder,
    send_due_date_changed_notifications,
)
from moodle.poller import poll_user

TEST_DB_URI = "file:moodi_test?mode=memory&cache=shared"


def make_connection():
    conn = sqlite3.connect(TEST_DB_URI, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def make_future_dt(days_ahead: int) -> datetime:
    return (
        datetime.now().replace(hour=23, minute=59, second=0, microsecond=0)
        + timedelta(days=days_ahead)
    )


@pytest.fixture(scope="session")
def init_test_db():
    conn = make_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT UNIQUE NOT NULL,
            moodle_user_id INTEGER,
            wstoken TEXT,
            is_active BOOLEAN DEFAULT 1,
            first_name TEXT
        );
        CREATE TABLE IF NOT EXISTS user_courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            course_name TEXT NOT NULL,
            UNIQUE(user_id, course_id)
        );
        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            moodle_assign_id INTEGER NOT NULL,
            course_name TEXT,
            assignment_name TEXT,
            due_date DATETIME,
            is_submitted BOOLEAN DEFAULT 0,
            notified_new BOOLEAN DEFAULT 0,
            notified_today BOOLEAN DEFAULT 0,
            notified_evening BOOLEAN DEFAULT 0,
            notified_due_changed BOOLEAN DEFAULT 1,
            UNIQUE(user_id, moodle_assign_id)
        );
        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_name TEXT,
            item_name TEXT,
            grade REAL,
            grade_range TEXT,
            notified BOOLEAN DEFAULT 0,
            detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, course_name, item_name)
        );
        INSERT OR IGNORE INTO users (phone_number, first_name, wstoken, moodle_user_id, is_active)
        VALUES ('972500000001', 'טסט', 'fake_token', 999, 1);
    """)
    conn.execute("""
        INSERT OR IGNORE INTO user_courses (user_id, course_id, course_name)
        SELECT id, 101, 'קורס טסט' FROM users WHERE phone_number='972500000001'
    """)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def clean_assignments(init_test_db):
    init_test_db.execute("DELETE FROM assignments")
    init_test_db.commit()
    yield


def get_user_id(conn):
    return conn.execute(
        "SELECT id FROM users WHERE phone_number='972500000001'"
    ).fetchone()[0]


# ─── Morning Summary ──────────────────────────────────────────────────────────

def test_morning_summary_sends_when_assignment_today(init_test_db, clean_assignments):
    uid = get_user_id(init_test_db)
    today_str = date.today().isoformat()
    init_test_db.execute(
        "INSERT INTO assignments "
        "(user_id, moodle_assign_id, course_name, assignment_name, due_date, is_submitted, notified_today) "
        "VALUES (?, 1, 'קורס', 'מטלה ראשונה', ?, 0, 0)",
        (uid, f"{today_str} 23:59:00"),
    )
    init_test_db.commit()

    with patch("notifications.engine.get_connection", side_effect=make_connection), \
         patch("notifications.engine.send_text") as mock_text, \
         patch("notifications.engine.send_buttons"):
        send_morning_summary()

    assert mock_text.called
    assert "מטלה ראשונה" in mock_text.call_args[0][1]

    row = make_connection().execute(
        "SELECT notified_today FROM assignments WHERE user_id=? AND moodle_assign_id=1", (uid,)
    ).fetchone()
    assert row["notified_today"] == 1


def test_morning_summary_skips_when_no_assignment_today(init_test_db, clean_assignments):
    uid = get_user_id(init_test_db)
    tomorrow_str = (date.today() + timedelta(days=1)).isoformat()
    init_test_db.execute(
        "INSERT INTO assignments "
        "(user_id, moodle_assign_id, course_name, assignment_name, due_date, is_submitted, notified_today) "
        "VALUES (?, 2, 'קורס', 'מטלה עתידית', ?, 0, 0)",
        (uid, f"{tomorrow_str} 23:59:00"),
    )
    init_test_db.commit()

    with patch("notifications.engine.get_connection", side_effect=make_connection), \
         patch("notifications.engine.send_text") as mock_text, \
         patch("notifications.engine.send_buttons"):
        send_morning_summary()

    assert not mock_text.called


def test_morning_summary_skips_submitted(init_test_db, clean_assignments):
    uid = get_user_id(init_test_db)
    today_str = date.today().isoformat()
    init_test_db.execute(
        "INSERT INTO assignments "
        "(user_id, moodle_assign_id, course_name, assignment_name, due_date, is_submitted, notified_today) "
        "VALUES (?, 3, 'קורס', 'מטלה שהוגשה', ?, 1, 0)",
        (uid, f"{today_str} 23:59:00"),
    )
    init_test_db.commit()

    with patch("notifications.engine.get_connection", side_effect=make_connection), \
         patch("notifications.engine.send_text") as mock_text, \
         patch("notifications.engine.send_buttons"):
        send_morning_summary()

    assert not mock_text.called


# ─── Evening Reminder ─────────────────────────────────────────────────────────

def test_evening_reminder_sends_when_assignment_today(init_test_db, clean_assignments):
    uid = get_user_id(init_test_db)
    today_str = date.today().isoformat()
    init_test_db.execute(
        "INSERT INTO assignments "
        "(user_id, moodle_assign_id, course_name, assignment_name, due_date, is_submitted, notified_evening) "
        "VALUES (?, 4, 'קורס', 'מטלת ערב', ?, 0, 0)",
        (uid, f"{today_str} 23:59:00"),
    )
    init_test_db.commit()

    with patch("notifications.engine.get_connection", side_effect=make_connection), \
         patch("notifications.engine.send_text") as mock_text, \
         patch("notifications.engine.send_buttons"):
        send_evening_reminder()

    assert mock_text.called
    assert "מטלת ערב" in mock_text.call_args[0][1]


def test_evening_reminder_skips_already_notified(init_test_db, clean_assignments):
    uid = get_user_id(init_test_db)
    today_str = date.today().isoformat()
    init_test_db.execute(
        "INSERT INTO assignments "
        "(user_id, moodle_assign_id, course_name, assignment_name, due_date, is_submitted, notified_evening) "
        "VALUES (?, 5, 'קורס', 'מטלה שנשלחה', ?, 0, 1)",
        (uid, f"{today_str} 23:59:00"),
    )
    init_test_db.commit()

    with patch("notifications.engine.get_connection", side_effect=make_connection), \
         patch("notifications.engine.send_text") as mock_text, \
         patch("notifications.engine.send_buttons"):
        send_evening_reminder()

    assert not mock_text.called


# ─── Poll User — Due Date Change ──────────────────────────────────────────────

def test_poll_user_detects_due_date_change(init_test_db, clean_assignments):
    uid = get_user_id(init_test_db)
    old_due_str = make_future_dt(1).strftime("%Y-%m-%d %H:%M:%S")
    init_test_db.execute(
        "INSERT INTO assignments "
        "(user_id, moodle_assign_id, course_name, assignment_name, due_date, notified_due_changed) "
        "VALUES (?, 42, 'קורס טסט', 'מטלה ראשונה', ?, 1)",
        (uid, old_due_str),
    )
    init_test_db.commit()

    new_due_dt = make_future_dt(11)
    new_due_ts = int(new_due_dt.timestamp())
    expected_due_str = datetime.fromtimestamp(new_due_ts).strftime("%Y-%m-%d %H:%M:%S")

    mock_raw = [{"fullname": "קורס טסט", "assignments": [
        {"id": 42, "name": "מטלה ראשונה", "duedate": new_due_ts}
    ]}]

    with patch("moodle.poller.get_connection", side_effect=make_connection), \
         patch("moodle.poller.get_assignments", return_value=mock_raw), \
         patch("moodle.poller.get_grades_table", return_value=[]), \
         patch("moodle.client.get_submission_status", return_value="not_submitted"):
        poll_user(
            user_id=uid,
            moodle_user_id=999,
            wstoken="fake_token",
            course_ids=[101],
            course_map={101: "קורס טסט"},
            skip_notifications=True,
        )

    row = make_connection().execute(
        "SELECT due_date, notified_due_changed FROM assignments WHERE user_id=? AND moodle_assign_id=42",
        (uid,),
    ).fetchone()
    assert row["notified_due_changed"] == 0
    assert row["due_date"] == expected_due_str


# ─── Deadline Extension Notification ─────────────────────────────────────────

def test_due_date_changed_notification_sends_and_marks(init_test_db, clean_assignments):
    uid = get_user_id(init_test_db)
    due_str = make_future_dt(5).strftime("%Y-%m-%d %H:%M:%S")
    init_test_db.execute(
        "INSERT INTO assignments "
        "(user_id, moodle_assign_id, course_name, assignment_name, due_date, notified_due_changed) "
        "VALUES (?, 99, 'קורס', 'מטלה מורחבת', ?, 0)",
        (uid, due_str),
    )
    init_test_db.commit()

    with patch("notifications.engine.get_connection", side_effect=make_connection), \
         patch("notifications.engine.send_text") as mock_text, \
         patch("notifications.engine.send_buttons"):
        send_due_date_changed_notifications(uid, "972500000001")

    assert mock_text.called
    assert "מטלה מורחבת" in mock_text.call_args[0][1]

    row = make_connection().execute(
        "SELECT notified_due_changed FROM assignments WHERE user_id=? AND moodle_assign_id=99",
        (uid,),
    ).fetchone()
    assert row["notified_due_changed"] == 1
