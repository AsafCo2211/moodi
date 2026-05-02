from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from database import get_connection
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

_SESSION_EXPIRED_HTML = """<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>מוודי — סשן פג</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      min-height: 100vh; display: flex; align-items: center; justify-content: center;
      background: #f0f4ff;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      padding: 24px 16px; color: #1e293b;
    }
    .card {
      background: #fff; border-radius: 20px;
      box-shadow: 0 4px 24px rgba(37,99,235,0.10), 0 1px 4px rgba(0,0,0,0.06);
      padding: 40px 36px; width: 100%; max-width: 420px; text-align: center;
    }
    .icon { font-size: 48px; margin-bottom: 16px; }
    h2 { font-size: 20px; font-weight: 700; color: #1e293b; margin-bottom: 10px; }
    p { color: #64748b; font-size: 15px; line-height: 1.6; }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">⏱️</div>
    <h2>הסשן פג</h2>
    <p>חזור למוודי בוואטסאפ ובקש קישור חדש לדאשבורד.</p>
  </div>
</body>
</html>"""


def _validate_session(phone: str, code: str) -> None:
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM dashboard_sessions WHERE phone_number=? AND code=? AND expires_at > datetime('now')",
        (phone, code),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="Session expired")
    conn.execute(
        "UPDATE dashboard_sessions SET last_active=datetime('now'), expires_at=datetime('now','+10 minutes') "
        "WHERE phone_number=? AND code=?",
        (phone, code),
    )
    conn.commit()
    conn.close()


def _get_user_id(phone: str) -> int:
    conn = get_connection()
    row = conn.execute("SELECT id FROM users WHERE phone_number=?", (phone,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row["id"]


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(phone: str, code: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM dashboard_sessions WHERE phone_number=? AND code=? AND expires_at > datetime('now')",
        (phone, code),
    ).fetchone()
    if not row:
        conn.close()
        logger.warning(f"Dashboard access denied for phone={phone}")
        return HTMLResponse(content=_SESSION_EXPIRED_HTML, status_code=401)
    conn.execute(
        "UPDATE dashboard_sessions SET last_active=datetime('now'), expires_at=datetime('now','+10 minutes') "
        "WHERE phone_number=? AND code=?",
        (phone, code),
    )
    conn.commit()
    conn.close()
    with open("templates/dashboard.html", encoding="utf-8") as f:
        return f.read()


@router.get("/api/dashboard/courses")
async def get_courses(phone: str, code: str):
    _validate_session(phone, code)
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT uc.course_id, uc.course_name,
               COALESCE(ucs.is_active, 1) as is_active
        FROM user_courses uc
        LEFT JOIN user_course_settings ucs
          ON uc.user_id = ucs.user_id AND uc.course_id = ucs.course_id
        WHERE uc.user_id = (SELECT id FROM users WHERE phone_number = ?)
        ORDER BY
            COALESCE(ucs.is_active, 1) DESC,
            uc.added_at DESC
        """,
        (phone,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


class ToggleCourseBody(BaseModel):
    phone: str
    code: str
    course_id: int
    is_active: bool


@router.post("/api/dashboard/courses/toggle")
async def toggle_course(body: ToggleCourseBody):
    _validate_session(body.phone, body.code)
    user_id = _get_user_id(body.phone)
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO user_course_settings (user_id, course_id, is_active) VALUES (?, ?, ?)",
        (user_id, body.course_id, 1 if body.is_active else 0),
    )
    conn.commit()
    conn.close()
    logger.info(f"Course {body.course_id} toggled to {body.is_active} for user {user_id}")
    return {"ok": True}


@router.get("/api/dashboard/assignments")
async def get_assignments(phone: str, code: str):
    _validate_session(phone, code)
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT a.moodle_assign_id, a.course_name, a.assignment_name, a.due_date,
               COALESCE(uas.status, 'open') as status
        FROM assignments a
        LEFT JOIN user_assignment_settings uas
          ON a.user_id = uas.user_id AND a.moodle_assign_id = uas.moodle_assign_id
        WHERE a.user_id = (SELECT id FROM users WHERE phone_number = ?)
          AND a.is_submitted = 0
          AND COALESCE(uas.status, 'open') = 'open'
        ORDER BY
            CASE WHEN a.due_date IS NULL THEN 1 ELSE 0 END ASC,
            a.due_date ASC
        """,
        (phone,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


class UpdateAssignmentBody(BaseModel):
    phone: str
    code: str
    moodle_assign_id: int
    status: str


@router.post("/api/dashboard/assignments/update")
async def update_assignment(body: UpdateAssignmentBody):
    _validate_session(body.phone, body.code)
    user_id = _get_user_id(body.phone)
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO user_assignment_settings (user_id, moodle_assign_id, status) VALUES (?, ?, ?)",
        (user_id, body.moodle_assign_id, body.status),
    )
    if body.status == "team_submitted":
        conn.execute(
            "UPDATE assignments SET is_submitted = 1 WHERE user_id = ? AND moodle_assign_id = ?",
            (user_id, body.moodle_assign_id),
        )
    elif body.status == "open":
        conn.execute(
            "UPDATE assignments SET is_submitted = 0 WHERE user_id = ? AND moodle_assign_id = ?",
            (user_id, body.moodle_assign_id),
        )
    conn.commit()
    conn.close()
    logger.info(f"Assignment {body.moodle_assign_id} set to '{body.status}' for user {user_id}")
    return {"ok": True}


@router.get("/api/dashboard/personal-tasks")
async def get_personal_tasks(phone: str, code: str):
    _validate_session(phone, code)
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, title, due_datetime
        FROM personal_tasks
        WHERE user_id=(SELECT id FROM users WHERE phone_number=?)
          AND status='open' AND due_datetime IS NOT NULL
        ORDER BY due_datetime ASC
        """,
        (phone,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/api/dashboard/personal-tasks-full")
async def get_personal_tasks_full(phone: str, code: str):
    _validate_session(phone, code)
    conn = get_connection()
    tasks = conn.execute(
        """
        SELECT id, title, due_datetime, status, created_at
        FROM personal_tasks
        WHERE user_id=(SELECT id FROM users WHERE phone_number=?)
          AND status='open'
        ORDER BY
            CASE WHEN due_datetime IS NULL THEN 1 ELSE 0 END ASC,
            due_datetime ASC
        """,
        (phone,),
    ).fetchall()
    result = []
    for t in tasks:
        task = dict(t)
        reminders = conn.execute(
            "SELECT remind_at, sent FROM task_reminders WHERE task_id=? AND sent=0",
            (t["id"],),
        ).fetchall()
        task["reminders"] = [dict(r) for r in reminders]
        result.append(task)
    conn.close()
    return result


class UpdatePersonalTaskBody(BaseModel):
    phone: str
    code: str
    task_id: int
    title: str
    due_datetime: str | None = None


@router.post("/api/dashboard/personal-tasks/update")
async def update_personal_task(body: UpdatePersonalTaskBody):
    _validate_session(body.phone, body.code)
    user_id = _get_user_id(body.phone)
    conn = get_connection()
    conn.execute(
        "UPDATE personal_tasks SET title=?, due_datetime=? WHERE id=? AND user_id=?",
        (body.title, body.due_datetime, body.task_id, user_id),
    )
    conn.commit()
    conn.close()
    logger.info(f"Personal task {body.task_id} updated for user {user_id}")
    return {"ok": True}


class DeletePersonalTaskBody(BaseModel):
    phone: str
    code: str
    task_id: int


@router.post("/api/dashboard/personal-tasks/delete")
async def delete_personal_task(body: DeletePersonalTaskBody):
    _validate_session(body.phone, body.code)
    user_id = _get_user_id(body.phone)
    conn = get_connection()
    conn.execute(
        "UPDATE personal_tasks SET status='deleted' WHERE id=? AND user_id=?",
        (body.task_id, user_id),
    )
    conn.commit()
    conn.close()
    logger.info(f"Personal task {body.task_id} deleted for user {user_id}")
    return {"ok": True}


class RefreshSessionBody(BaseModel):
    phone: str
    code: str


@router.post("/api/dashboard/session/refresh")
async def refresh_session(body: RefreshSessionBody):
    conn = get_connection()
    conn.execute(
        "UPDATE dashboard_sessions SET expires_at=datetime('now','+10 minutes'), last_active=datetime('now') "
        "WHERE phone_number=? AND code=?",
        (body.phone, body.code),
    )
    conn.commit()
    conn.close()
    return {"ok": True}
