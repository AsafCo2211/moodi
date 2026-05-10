import sqlite3
from config import DATABASE_URL
from utils.logger import get_logger

logger = get_logger(__name__)

def get_connection():
    conn = sqlite3.connect(DATABASE_URL, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT UNIQUE NOT NULL,
            moodle_user_id INTEGER,
            wstoken TEXT,
            token_expires_at DATETIME,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
            first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, moodle_assign_id)
        );

        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_name TEXT,
            item_name TEXT,
            grade REAL,
            notified BOOLEAN DEFAULT 0,
            detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, course_name, item_name)
        );
                         
        CREATE TABLE IF NOT EXISTS user_courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            course_name TEXT NOT NULL,
            added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, course_id)
        );
                         
        CREATE TABLE IF NOT EXISTS courses_cache (
            moodle_course_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            short_name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pending_registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            code TEXT NOT NULL,
            wstoken TEXT NOT NULL,
            moodle_user_id INTEGER NOT NULL,
            first_name TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dashboard_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            code TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL,
            last_active DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_course_settings (
            user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            PRIMARY KEY (user_id, course_id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS user_assignment_settings (
            user_id INTEGER NOT NULL,
            moodle_assign_id INTEGER NOT NULL,
            status TEXT DEFAULT 'open',
            note TEXT,
            PRIMARY KEY (user_id, moodle_assign_id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS personal_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            due_datetime DATETIME,
            status TEXT DEFAULT 'open',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS task_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            remind_at DATETIME NOT NULL,
            sent BOOLEAN DEFAULT 0,
            FOREIGN KEY (task_id) REFERENCES personal_tasks(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)

    conn.commit()

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
        conn.commit()
    except Exception:
        pass  # column already exists

    try:
        cursor.execute("ALTER TABLE grades ADD COLUMN grade_range TEXT")
        conn.commit()
    except Exception:
        pass  # column already exists

    try:
        cursor.execute("ALTER TABLE assignments ADD COLUMN notified_due_changed BOOLEAN DEFAULT 1")
        conn.commit()
    except Exception:
        pass  # column already exists

    for col, defn in [
        ("private_token",     "TEXT"),
        ("moodle_session",    "TEXT"),
        ("session_expires",   "DATETIME"),
        ("autologin_last_at", "DATETIME"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")
            conn.commit()
        except Exception:
            pass

    try:
        cursor.execute("ALTER TABLE pending_registrations ADD COLUMN private_token TEXT")
        conn.commit()
    except Exception:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recording_watched (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            video_id    TEXT NOT NULL,
            course_id   INTEGER NOT NULL,
            watched_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, video_id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recordings (
            course_id     INTEGER NOT NULL,
            video_id      TEXT NOT NULL,
            name          TEXT,
            lecturer      TEXT,
            duration      TEXT,
            date          TEXT,
            type          TEXT,
            thumbnail_url TEXT,
            cached_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (course_id, video_id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_recordings_course
        ON recordings(course_id, cached_at)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recording_notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            video_id   TEXT NOT NULL,
            course_id  INTEGER NOT NULL,
            note       TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, video_id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()

    try:
        cursor.execute("ALTER TABLE recordings ADD COLUMN thumbnail_url TEXT")
        conn.commit()
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE recordings ADD COLUMN thumbnail_b64 TEXT")
        conn.commit()
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE personal_tasks ADD COLUMN video_id TEXT DEFAULT NULL")
        conn.commit()
    except Exception:
        pass

    conn.close()
    logger.info("Database initialized successfully")

if __name__ == "__main__":
    init_db()