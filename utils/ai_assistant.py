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

Extract ALL intents from the user's message and return ONLY valid JSON, no markdown, no explanation.
A single message may contain multiple tasks — return all of them.

{existing_tasks_section}

Supported actions:
- add_task: add a personal task/reminder
- update_task: update an existing task
- delete_task: delete a task
- list_tasks: show upcoming tasks
- unsupported: anything else

JSON format (always return an array, even for a single action):
{{
  "actions": [
    {{
      "action": "add_task" | "update_task" | "delete_task" | "list_tasks" | "unsupported",
      "title": "task title in Hebrew or null",
      "due_datetime": "YYYY-MM-DD HH:MM" or null,
      "reminders": ["YYYY-MM-DD HH:MM", ...] or [],
      "task_id": <integer id from existing tasks list, for update/delete> or null,
      "task_reference": "partial task name fallback for update/delete" or null,
      "reason": "why unsupported" or null
    }}
  ]
}}

Examples:
User: "יש לי תור לספר ביום חמישי בשעה 11 תזכיר לי ערב לפני, וגם יש לי פגישה ביום שישי בשעה 14"
-> {{"actions":[{{"action":"add_task","title":"תור לספר","due_datetime":"2026-05-07 11:00","reminders":["2026-05-06 20:00"],"task_id":null,"task_reference":null,"reason":null}},{{"action":"add_task","title":"פגישה","due_datetime":"2026-05-08 14:00","reminders":[],"task_id":null,"task_reference":null,"reason":null}}]}}

User: "תזיז את הספר לשעה 12"
-> {{"actions":[{{"action":"update_task","title":null,"due_datetime":"2026-05-07 12:00","reminders":[],"task_id":3,"task_reference":"ספר","reason":null}}]}}

User: "מה המשימות שלי?"
-> {{"actions":[{{"action":"list_tasks","title":null,"due_datetime":null,"reminders":[],"task_id":null,"task_reference":null,"reason":null}}]}}

User: "קבע לי טיסה לתאילנד"
-> {{"actions":[{{"action":"unsupported","title":null,"due_datetime":null,"reminders":[],"task_id":null,"task_reference":null,"reason":"הזמנת טיסות"}}]}}
"""


def parse_user_request(text: str, user_name: str, existing_tasks: list = []) -> list:
    today = datetime.now().strftime('%Y-%m-%d, %A')

    if existing_tasks:
        tasks_json = json.dumps(
            [{"id": t["id"], "title": t["title"], "due": t["due_datetime"]} for t in existing_tasks],
            ensure_ascii=False
        )
        existing_section = f"User's existing personal tasks (use the id field for update/delete):\n{tasks_json}"
    else:
        existing_section = ""

    prompt = _SYSTEM_PROMPT.format(today=today, existing_tasks_section=existing_section)
    prompt += f"\n\nUser: {text}"

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        raw = response.text.strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw.strip())
        parsed = json.loads(raw)

        # Normalise: accept {"actions": [...]} or a bare list or a bare dict
        if isinstance(parsed, dict):
            if "actions" in parsed:
                return parsed["actions"]
            return [parsed]
        if isinstance(parsed, list):
            return parsed
        return [{"action": "unsupported", "reason": "unexpected_format", "reminders": []}]

    except Exception as e:
        logger.error(f"parse_user_request failed: {e}")
        return [{"action": "unsupported", "reason": "parse_error", "reminders": [],
                 "title": None, "due_datetime": None, "task_reference": None, "task_id": None}]


def generate_status_report(first_name: str, assignments: list, personal_tasks: list) -> str:
    from datetime import timezone, timedelta
    RLM = "‏"
    israel_tz = timezone(timedelta(hours=3))
    today = datetime.now(israel_tz).strftime("%Y-%m-%d %H:%M")

    prompt = f"""You are Moodi, a personal assistant for Israeli students.
Today is {today}. The user's name is {first_name}.

Write a focused weekly status report in Hebrew.
Format it as a WhatsApp message with RLM (\\u200f) at the start of EVERY line.
Keep it concise — max 20 lines total.

Structure:
1. Short greeting line
2. Section "📚 מטלות לשבוע הקרוב:" — list Moodle assignments with due dates
3. Section "🗓️ משימות אישיות:" — list personal tasks with dates
4. One short motivating closing line

If a section is empty, write "אין 🎉" for that section.
Use emojis for visual clarity.
Every line MUST start with \\u200f.

Moodle assignments this week:
{json.dumps([{{'name': a['assignment_name'], 'course': a['course_name'], 'due': a['due_date']}} for a in assignments], ensure_ascii=False)}

Personal tasks this week:
{json.dumps([{{'title': t['title'], 'due': t['due_datetime']}} for t in personal_tasks], ensure_ascii=False)}
"""

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        return response.text
    except Exception as e:
        logger.error(f"Status report generation failed: {e}")
        return f"{RLM}לא הצלחתי ליצור דוח מצב כרגע, נסה שוב מאוחר יותר"


def transcribe_audio(audio_bytes: bytes) -> str:
    try:
        part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg; codecs=opus")
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                part,
                "Transcribe this Hebrew audio message exactly as spoken. Return only the transcribed text, no explanations."
            ]
        )
        return response.text.strip() if response.text else ""
    except Exception as e:
        logger.error(f"transcribe_audio failed: {e}")
        return ""
