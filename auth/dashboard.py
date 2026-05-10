import threading
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from database import get_connection
from utils.logger import get_logger
from moodle.recordings import (
    get_or_refresh_session,
    get_course_recordings,
    get_course_recordings_cached,
    save_recordings_cache,
    seconds_until_rate_limit_reset,
)

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


# ── Tasks (recordings shortcut) ───────────────────────────────────────────────

class CreateTaskBody(BaseModel):
    phone: str
    code: str
    title: str
    video_id: str | None = None


@router.post("/api/tasks")
async def create_task(body: CreateTaskBody):
    _validate_session(body.phone, body.code)
    user_id = _get_user_id(body.phone)
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO personal_tasks (user_id, title, video_id, status) VALUES (?, ?, ?, 'open')",
        (user_id, body.title, body.video_id),
    )
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"task_id": task_id}


class CompleteTaskBody(BaseModel):
    phone: str
    code: str


@router.patch("/api/tasks/{task_id}/complete")
async def complete_task(task_id: int, body: CompleteTaskBody):
    """מסמן משימה כהושלמה ומסנכרן צפייה בהקלטה אם קיימת."""
    _validate_session(body.phone, body.code)
    user_id = _get_user_id(body.phone)
    conn = get_connection()
    row = conn.execute(
        "SELECT video_id FROM personal_tasks WHERE id=? AND user_id=?",
        (task_id, user_id),
    ).fetchone()
    video_id = row["video_id"] if row else None
    conn.execute(
        "UPDATE personal_tasks SET status='deleted' WHERE id=? AND user_id=?",
        (task_id, user_id),
    )
    if video_id:
        conn.execute(
            "INSERT OR REPLACE INTO recording_watched (user_id, video_id, course_id) VALUES (?, ?, 0)",
            (user_id, video_id),
        )
    conn.commit()
    conn.close()
    return {"ok": True, "video_id": video_id}


# ── Recordings ────────────────────────────────────────────────────────────────

@router.get("/api/recordings/courses")
async def get_recording_courses(phone: str, code: str):
    _validate_session(phone, code)
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT uc.course_id, uc.course_name
        FROM user_courses uc
        LEFT JOIN user_course_settings ucs
          ON ucs.user_id = uc.user_id AND ucs.course_id = uc.course_id
        WHERE uc.user_id = (SELECT id FROM users WHERE phone_number = ?)
          AND (ucs.is_active IS NULL OR ucs.is_active = 1)
        ORDER BY uc.course_name
        """,
        (phone,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _refresh_recordings_background(course_id: int, user_id: int, wstoken: str, moodle_user_id: int, private_token: str):
    try:
        session = get_or_refresh_session(user_id, wstoken, moodle_user_id, private_token)
        if session:
            videos = get_course_recordings(session, course_id)
            if videos:
                save_recordings_cache(course_id, videos)
    except Exception as e:
        logger.error("Background recordings refresh failed for course %s: %s", course_id, e)


@router.get("/api/recordings/list")
async def get_recordings_list(phone: str, code: str, course_id: int):
    _validate_session(phone, code)
    conn = get_connection()
    user = conn.execute(
        "SELECT id, wstoken, moodle_user_id, private_token, moodle_session, session_expires, autologin_last_at FROM users WHERE phone_number=?",
        (phone,),
    ).fetchone()
    conn.close()

    videos = get_course_recordings_cached(course_id)

    if videos is not None:
        is_stale = videos[0].get("is_stale", False) if videos else False
        if is_stale and user and user["private_token"]:
            threading.Thread(
                target=_refresh_recordings_background,
                args=(course_id, user["id"], user["wstoken"], user["moodle_user_id"], user["private_token"]),
                daemon=True,
            ).start()
        for v in videos:
            v.pop("is_stale", None)
    else:
        if not user or not user["private_token"]:
            return JSONResponse({"error": "reauth_required"}, status_code=401)

        session = get_or_refresh_session(
            user["id"], user["wstoken"], user["moodle_user_id"], user["private_token"]
        )

        if session is None:
            conn = get_connection()
            row = conn.execute("SELECT autologin_last_at FROM users WHERE id=?", (user["id"],)).fetchone()
            conn.close()
            retry_after = seconds_until_rate_limit_reset(row["autologin_last_at"]) if row and row["autologin_last_at"] else 360
            return JSONResponse({"status": "reconnecting", "retry_after": retry_after}, status_code=503)

        videos = get_course_recordings(session, course_id)
        save_recordings_cache(course_id, videos)

    if not user:
        return videos or []

    user_id = user["id"]
    conn = get_connection()
    watched_ids = {
        r["video_id"]
        for r in conn.execute(
            "SELECT video_id FROM recording_watched WHERE user_id=?",
            (user_id,),
        ).fetchall()
    }
    notes_map = {
        r["video_id"]: r["note"] or ""
        for r in conn.execute(
            "SELECT video_id, note FROM recording_notes WHERE user_id=? AND course_id=?",
            (user_id, course_id),
        ).fetchall()
    }
    tasks_map = {
        r["video_id"]: r["id"]
        for r in conn.execute(
            "SELECT id, video_id FROM personal_tasks WHERE user_id=? AND video_id IS NOT NULL AND status='open'",
            (user_id,),
        ).fetchall()
    }
    conn.close()

    for v in videos:
        vid = v.get("video_id", "")
        v["watched"] = vid in watched_ids
        v["note"] = notes_map.get(vid, "")
        v["task_id"] = tasks_map.get(vid)
        if "thumbnail_url" not in v:
            from config import MOODLE_BASE_URL
            v["thumbnail_url"] = f"{MOODLE_BASE_URL}/local/video_directory/thumb.php?id={vid}&second=900&mini=1"

    return videos


class WatchedBody(BaseModel):
    phone: str
    code: str
    video_id: str
    course_id: int


@router.post("/api/recordings/watched")
async def mark_watched(body: WatchedBody):
    _validate_session(body.phone, body.code)
    user_id = _get_user_id(body.phone)
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO recording_watched (user_id, video_id, course_id) VALUES (?, ?, ?)",
        (user_id, body.video_id, body.course_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


class UnwatchedBody(BaseModel):
    phone: str
    code: str
    video_id: str


@router.delete("/api/recordings/watched")
async def unmark_watched(body: UnwatchedBody):
    _validate_session(body.phone, body.code)
    user_id = _get_user_id(body.phone)
    conn = get_connection()
    conn.execute(
        "DELETE FROM recording_watched WHERE user_id=? AND video_id=?",
        (user_id, body.video_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


class NoteBody(BaseModel):
    phone: str
    code: str
    video_id: str
    course_id: int
    note: str


@router.post("/api/recordings/notes")
async def save_note(body: NoteBody):
    _validate_session(body.phone, body.code)
    user_id = _get_user_id(body.phone)
    conn = get_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO recording_notes (user_id, video_id, course_id, note, updated_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        """,
        (user_id, body.video_id, body.course_id, body.note),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


class DeleteNoteBody(BaseModel):
    phone: str
    code: str
    video_id: str


@router.delete("/api/recordings/notes")
async def delete_note(body: DeleteNoteBody):
    _validate_session(body.phone, body.code)
    user_id = _get_user_id(body.phone)
    conn = get_connection()
    conn.execute(
        "DELETE FROM recording_notes WHERE user_id=? AND video_id=?",
        (user_id, body.video_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.get("/api/recordings/open")
async def open_recording(phone: str, code: str, video_id: str, course_id: int):
    _validate_session(phone, code)
    conn = get_connection()
    user = conn.execute(
        "SELECT id, wstoken, moodle_user_id, private_token, autologin_last_at FROM users WHERE phone_number=?",
        (phone,),
    ).fetchone()
    conn.close()

    if not user or not user["private_token"]:
        raise HTTPException(status_code=401, detail="reauth_required")

    session = get_or_refresh_session(
        user["id"], user["wstoken"], user["moodle_user_id"], user["private_token"]
    )

    if session is None:
        conn = get_connection()
        row = conn.execute("SELECT autologin_last_at FROM users WHERE id=?", (user["id"],)).fetchone()
        conn.close()
        retry_after = seconds_until_rate_limit_reset(row["autologin_last_at"]) if row and row["autologin_last_at"] else 360
        return JSONResponse({"status": "reconnecting", "retry_after": retry_after}, status_code=503)

    from config import MOODLE_BASE_URL
    target = f"{MOODLE_BASE_URL}/blocks/video/viewvideo.php?id={video_id}&courseid={course_id}&type=2"
    response = RedirectResponse(url=target, status_code=302)
    response.set_cookie(
        key="MoodleSession",
        value=session,
        domain="moodle.bgu.ac.il",
        path="/",
        httponly=True,
        samesite="lax",
    )
    return response
