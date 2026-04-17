import requests
from config import MOODLE_BASE_URL, MOODLE_USER_AGENT

ENDPOINT = f"{MOODLE_BASE_URL}/webservice/rest/server.php"

def call_moodle(wstoken: str, wsfunction: str, params: dict = {}) -> dict:
    """
    שולח בקשה ל-Moodle API ומחזיר את התוצאה כ-dict.
    כל הבקשות עוברות דרך הפונקציה הזו.
    """
    data = {
        "wstoken": wstoken,
        "moodlewsrestformat": "json",
        "wsfunction": wsfunction,
        **params
    }

    response = requests.post(
        ENDPOINT,
        headers={"User-Agent": MOODLE_USER_AGENT},
        data=data,
        verify=False,
        timeout=15
    )

    response.raise_for_status()
    result = response.json()

    if isinstance(result, dict) and "exception" in result:
        raise Exception(f"Moodle API error: {result.get('message', 'Unknown error')}")

    return result


def get_user_courses(wstoken: str, user_id: int) -> list:
    """מחזיר את רשימת הקורסים של המשתמש"""
    result = call_moodle(wstoken, "core_enrol_get_users_courses", {
        "userid": user_id
    })
    return result if isinstance(result, list) else []


def get_assignments(wstoken: str, course_ids: list) -> list:
    """מחזיר את כל המטלות של הקורסים שנתקבלו"""
    params = {f"courseids[{i}]": cid for i, cid in enumerate(course_ids)}
    result = call_moodle(wstoken, "mod_assign_get_assignments", params)
    return result.get("courses", [])


def get_grades(wstoken: str, user_id: int, course_id: int) -> list:
    """מחזיר את הציונים של משתמש בקורס מסוים"""
    result = call_moodle(wstoken, "gradereport_user_get_grade_items", {
        "userid": user_id,
        "courseid": course_id
    })
    return result.get("usergrades", [{}])[0].get("gradeitems", [])