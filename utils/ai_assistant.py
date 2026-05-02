from google import genai
from google.genai import types
from config import GEMINI_API_KEY
from utils.logger import get_logger
import json
import re
from datetime import datetime

logger = get_logger(__name__)
client = genai.Client(api_key=GEMINI_API_KEY)

_SYSTEM_PROMPT = """You are Moodi's intent parser. The user is an Israeli student.
Today is {today}.

Extract the user's intent and return ONLY valid JSON, no markdown, no explanation.

Supported actions:
- add_task: add a personal task/reminder
- update_task: update an existing task
- delete_task: delete a task
- list_tasks: show upcoming tasks
- unsupported: anything else

JSON format:
{{
  "action": "add_task" | "update_task" | "delete_task" | "list_tasks" | "unsupported",
  "title": "task title in Hebrew",
  "due_datetime": "YYYY-MM-DD HH:MM" or null,
  "reminders": ["YYYY-MM-DD HH:MM", ...] or [],
  "task_reference": "partial task name for update/delete" or null,
  "reason": "why unsupported" or null
}}

Examples:
User: "יש לי תור לספר ביום חמישי בשעה 11 תזכיר לי ערב לפני"
-> {{"action":"add_task","title":"תור לספר","due_datetime":"2026-05-07 11:00","reminders":["2026-05-06 20:00"],"task_reference":null,"reason":null}}

User: "קבע לי טיסה לתאילנד"
-> {{"action":"unsupported","title":null,"due_datetime":null,"reminders":[],"task_reference":null,"reason":"הזמנת טיסות"}}

User: "מה המשימות שלי?"
-> {{"action":"list_tasks","title":null,"due_datetime":null,"reminders":[],"task_reference":null,"reason":null}}
"""


def parse_user_request(text: str, user_name: str) -> dict:
    today = datetime.now().strftime('%Y-%m-%d, %A')
    prompt = _SYSTEM_PROMPT.format(today=today) + f"\n\nUser: {text}"
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        raw = response.text.strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw.strip())
        return json.loads(raw)
    except Exception as e:
        logger.error(f"parse_user_request failed: {e}")
        return {"action": "unsupported", "reason": "parse_error", "reminders": [], "title": None, "due_datetime": None, "task_reference": None}


def transcribe_audio(audio_bytes: bytes) -> str:
    try:
        part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg; codecs=opus")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                part,
                "Transcribe this Hebrew audio message exactly as spoken. Return only the transcribed text, no explanations."
            ]
        )
        return response.text.strip() if response.text else ""
    except Exception as e:
        logger.error(f"transcribe_audio failed: {e}")
        return ""
