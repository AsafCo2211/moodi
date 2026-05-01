import random
import requests
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from config import MOODLE_BASE_URL, MOODLE_USER_AGENT
from moodle.client import call_moodle
from database import get_connection

router = APIRouter()

TOKEN_URL = f"{MOODLE_BASE_URL}/login/token.php?lang=he"


class LoginRequest(BaseModel):
    phone: str
    username: str
    password: str


@router.get("/login", response_class=HTMLResponse)
async def login_page():
    with open("templates/login.html", encoding="utf-8") as f:
        return f.read()


@router.post("/auth/login")
async def auth_login(body: LoginRequest):
    resp = requests.post(
        TOKEN_URL,
        data={
            "username": body.username,
            "password": body.password,
            "service": "moodle_mobile_app",
        },
        headers={"User-Agent": MOODLE_USER_AGENT},
        verify=False,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        return JSONResponse(status_code=401, content={"error": "שם משתמש או סיסמה שגויים"})

    wstoken = data["token"]

    site_info = call_moodle(wstoken, "core_webservice_get_site_info", {})
    moodle_user_id = site_info["userid"]
    first_name = site_info["fullname"].split()[0]

    code = str(random.randint(100000, 999999))

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO pending_registrations
                (phone_number, code, wstoken, moodle_user_id, first_name, expires_at)
            VALUES (?, ?, ?, ?, ?, datetime('now', '+10 minutes'))
            """,
            (body.phone, code, wstoken, moodle_user_id, first_name),
        )
        conn.commit()
    finally:
        conn.close()

    return {"code": code, "first_name": first_name}
