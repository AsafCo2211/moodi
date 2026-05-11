"""ניהול הקלטות — session autologin + גרידת רשימת סרטונים מ-BGU Moodle."""
import base64
import re
import requests
from datetime import datetime, timedelta

from config import MOODLE_BASE_URL, MOODLE_USER_AGENT
from database import get_connection
from moodle.client import call_moodle
from auth.token_store import encrypt, decrypt
from utils.logger import get_logger

logger = get_logger(__name__)

_AUTOLOGIN_URL = f"{MOODLE_BASE_URL}/admin/tool/mobile/autologin.php"
_VIDEOSLIST_URL = f"{MOODLE_BASE_URL}/blocks/video/videoslist.php"
_VIEWVIDEO_URL = f"{MOODLE_BASE_URL}/blocks/video/viewvideo.php"
_RATE_LIMIT_SECONDS = 360  # 6 minutes


def get_or_refresh_session(user_id: int, wstoken: str, moodle_user_id: int, private_token_encrypted: str) -> str | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT moodle_session, session_expires, autologin_last_at FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    conn.close()

    if row and row["moodle_session"] and row["session_expires"]:
        expires = datetime.fromisoformat(row["session_expires"])
        if expires > datetime.utcnow():
            return decrypt(row["moodle_session"])

    if row and row["autologin_last_at"]:
        last_at = datetime.fromisoformat(row["autologin_last_at"])
        if (datetime.utcnow() - last_at).total_seconds() < _RATE_LIMIT_SECONDS:
            return None

    return _create_new_session(user_id, wstoken, moodle_user_id, private_token_encrypted)


def _create_new_session(user_id: int, wstoken: str, moodle_user_id: int, private_token_encrypted: str) -> str | None:
    try:
        private_token = decrypt(private_token_encrypted)
        if not private_token:
            return None

        result = call_moodle(wstoken, "tool_mobile_get_autologin_key", {"privatetoken": private_token})
        key = result.get("key")
        if not key:
            logger.warning("tool_mobile_get_autologin_key returned no key for user %s", user_id)
            return None

        s = requests.Session()
        resp = s.get(
            _AUTOLOGIN_URL,
            params={"key": key, "userid": moodle_user_id},
            headers={"User-Agent": MOODLE_USER_AGENT},
            allow_redirects=True,
            verify=False,
            timeout=15,
        )

        session = s.cookies.get("MoodleSession")
        if not session:
            logger.warning("No MoodleSession cookie returned for user %s", user_id)
            return None

        now = datetime.utcnow()
        expires = now + timedelta(hours=4)

        conn = get_connection()
        conn.execute(
            """
            UPDATE users
            SET moodle_session=?, session_expires=?, autologin_last_at=?
            WHERE id=?
            """,
            (encrypt(session), expires.isoformat(), now.isoformat(), user_id),
        )
        conn.commit()
        conn.close()

        return session

    except Exception as e:
        logger.error("_create_new_session failed for user %s: %s", user_id, e)
        conn = get_connection()
        conn.execute("UPDATE users SET autologin_last_at=? WHERE id=?", (datetime.utcnow().isoformat(), user_id))
        conn.commit()
        conn.close()
        return None


def get_course_recordings(session_cookie: str, course_id: int) -> list[dict]:
    try:
        def _strip(t): return re.sub(r'<[^>]+>', '', t).strip()

        videos = []
        page = 0
        while True:
            resp = requests.get(
                _VIDEOSLIST_URL,
                params={"courseid": course_id, "page": page},
                cookies={"MoodleSession": session_cookie},
                headers={"User-Agent": MOODLE_USER_AGENT},
                verify=False,
                timeout=15,
            )
            rows = re.findall(
                r'<tr[^>]*id="videoslist_table_r\d+"[^>]*>(.*?)</tr>',
                resp.text,
                re.DOTALL,
            )
            if not rows:
                break

            for row_html in rows:
                m = re.search(r'viewvideo\.php\?id=(\d+)', row_html)
                if not m:
                    continue
                video_id = m.group(1)
                cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL)
                name     = _strip(cells[1]) if len(cells) > 1 else ""
                group    = _strip(cells[2]) if len(cells) > 2 else ""
                duration = _strip(cells[3]) if len(cells) > 3 else ""
                lecturer = _strip(cells[4]) if len(cells) > 4 else ""
                date     = _strip(cells[5]) if len(cells) > 5 else ""

                low = name.lower()
                if "שיעור" in low or "שעור" in low:
                    vtype = "lecture"
                elif "תרגול" in low or "תרגיל" in low:
                    vtype = "tutorial"
                else:
                    vtype = "other"

                videos.append({
                    "video_id": video_id,
                    "name": name,
                    "group": group,
                    "duration": duration,
                    "lecturer": lecturer,
                    "date": date,
                    "type": vtype,
                    "url": f"{_VIEWVIDEO_URL}?id={video_id}&courseid={course_id}&type=2",
                })

            page += 1

        return videos

    except Exception as e:
        logger.error("get_course_recordings failed for course %s: %s", course_id, e)
        return []


def get_course_recordings_cached(course_id: int) -> list[dict] | None:
    """
    מחזיר הקלטות מ-DB תמיד (אם קיים cache).
    מוסיף שדה is_stale=True אם הcache ישן מעל שעה.
    מחזיר None אם אין cache כלל.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM recordings WHERE course_id=? ORDER BY cached_at DESC",
        (course_id,),
    ).fetchall()
    conn.close()

    if not rows:
        return None

    newest = datetime.fromisoformat(rows[0]["cached_at"])
    is_stale = (datetime.utcnow() - newest).total_seconds() > 3600
    result = [dict(r) for r in rows]
    for r in result:
        r["is_stale"] = is_stale
    return result


def save_recordings_cache(course_id: int, recordings: list[dict]) -> None:
    """
    שומר רשימת הקלטות ל-DB עם upsert (ללא מחיקה תחילה).
    שומר thumbnail_b64 אם קיים ב-recording dict.
    """
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    for v in recordings:
        video_id = v.get("video_id", "")
        thumbnail_url = f"{MOODLE_BASE_URL}/local/video_directory/thumb.php?id={video_id}&second=900&mini=1"
        conn.execute(
            """
            INSERT OR REPLACE INTO recordings
                (course_id, video_id, name, lecturer, duration, date, type, thumbnail_url, thumbnail_b64, cached_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                video_id,
                v.get("name", ""),
                v.get("lecturer", ""),
                v.get("duration", ""),
                v.get("date", ""),
                v.get("type", "other"),
                thumbnail_url,
                v.get("thumbnail_b64"),
                now,
            ),
        )
    conn.commit()
    conn.close()
    logger.info("Saved %d recordings to cache for course %s", len(recordings), course_id)


def poll_recordings_for_course(course_id: int) -> bool:
    """
    מבצע scraping לקורס אחד.
    בוחר משתמש רנדומלי שרשום לקורס עם session תקף.
    אם אין session תקף — מנסה ליצור אחד.
    מחזיר True אם הצליח.
    """
    conn = get_connection()
    user = conn.execute(
        """
        SELECT u.id, u.wstoken, u.moodle_user_id, u.private_token,
               u.moodle_session, u.session_expires
        FROM users u
        JOIN user_courses uc ON u.id = uc.user_id
        WHERE uc.course_id = ? AND u.is_active = 1 AND u.wstoken IS NOT NULL
        ORDER BY RANDOM() LIMIT 1
        """,
        (course_id,),
    ).fetchone()
    conn.close()

    if not user or not user["private_token"]:
        logger.debug("No eligible user for recordings poll on course %s", course_id)
        return False

    session = get_or_refresh_session(
        user["id"], user["wstoken"], user["moodle_user_id"], user["private_token"]
    )

    if session is None:
        logger.debug("Could not obtain session for course %s (rate limited or no private_token)", course_id)
        return False

    results = get_course_recordings(session, course_id)
    if results:
        for v in results:
            video_id = v.get("video_id", "")
            thumb_url = f"{MOODLE_BASE_URL}/local/video_directory/thumb.php?id={video_id}&second=900&mini=1"
            try:
                r = requests.get(
                    thumb_url,
                    cookies={"MoodleSession": session},
                    headers={"User-Agent": MOODLE_USER_AGENT},
                    verify=False,
                    timeout=10,
                )
                if r.status_code == 200 and r.content:
                    v["thumbnail_b64"] = base64.b64encode(r.content).decode()
            except Exception:
                pass
        save_recordings_cache(course_id, results)
        return True

    return False


def poll_all_recordings() -> None:
    """
    מרענן הקלטות לכל הקורסים הייחודיים במערכת.
    רץ פעם בשעה מה-scheduler.
    """
    import pytz
    from datetime import datetime as _dt

    israel_tz = pytz.timezone("Asia/Jerusalem")
    now = _dt.now(israel_tz)
    if not (10 <= now.hour < 24 or (now.hour == 0 and now.minute <= 20)):
        return

    conn = get_connection()
    courses = conn.execute("SELECT DISTINCT course_id FROM user_courses").fetchall()
    conn.close()

    refreshed = 0
    skipped = 0
    for row in courses:
        cid = row["course_id"]

        conn = get_connection()
        cache_row = conn.execute(
            "SELECT MAX(cached_at) as newest FROM recordings WHERE course_id=?",
            (cid,)
        ).fetchone()
        conn.close()
        newest = cache_row["newest"] if cache_row else None

        if newest is None:
            logger.debug("course %s: no cache — refreshing", cid)
        elif (datetime.utcnow() - datetime.fromisoformat(newest)).total_seconds() < 3600:
            logger.debug("course %s: fresh cache (%s) — skipping", cid, newest)
            skipped += 1
            continue
        else:
            logger.debug("course %s: stale cache (%s) — refreshing", cid, newest)

        success = poll_recordings_for_course(cid)
        if success:
            refreshed += 1
        else:
            logger.debug("course %s: poll returned no results", cid)

    logger.info("poll_all_recordings: refreshed=%d skipped=%d", refreshed, skipped)


def seconds_until_rate_limit_reset(autologin_last_at_iso: str) -> int:
    last_at = datetime.fromisoformat(autologin_last_at_iso)
    elapsed = (datetime.utcnow() - last_at).total_seconds()
    return max(0, int(_RATE_LIMIT_SECONDS - elapsed))
