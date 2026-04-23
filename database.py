import sqlite3
from config import DATABASE_URL

def get_connection():
    conn = sqlite3.connect(DATABASE_URL)
    conn.row_factory = sqlite3.Row
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
    """)

    conn.commit()

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
        conn.commit()
    except Exception:
        pass  # column already exists

    conn.close()
    print("Database initialized successfully")

if __name__ == "__main__":
    init_db()