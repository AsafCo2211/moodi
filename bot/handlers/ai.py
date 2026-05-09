"""
הנדלר לבקשות AI — עיבוד הודעות טקסט ואודיו דרך Gemini.
מנהל יצירת משימות, עדכון, מחיקה, ותזכורות דרך שיחה חופשית.
"""

from bot.sender import send_text, send_buttons
from utils.ai_assistant import parse_user_request, transcribe_audio
from utils.task_manager import (
    create_task, get_upcoming_tasks,
    delete_task_by_id, delete_task_by_reference,
    update_task_by_id, update_task_datetime, add_reminders_to_task,
)
from utils.whatsapp_media import download_whatsapp_audio
from notifications.scheduler import schedule_reminder
from utils.logger import get_logger

logger = get_logger(__name__)

RLM = "‏"


async def handle_audio_message(from_number: str, media_id: str, user):
    """
    מוריד הודעת אודיו מ-WhatsApp, מתמלל אותה ומעביר לטיפול AI.

    Args:
        from_number: מספר הטלפון של השולח.
        media_id: מזהה המדיה ב-WhatsApp API.
        user: שורת המשתמש מה-DB.
    """
    audio_bytes = download_whatsapp_audio(media_id)
    if not audio_bytes:
        send_text(from_number, f"{RLM}לא הצלחתי לעבד את ההקלטה, נסה שוב")
        return

    text = transcribe_audio(audio_bytes)
    if not text:
        send_text(from_number, f"{RLM}לא הצלחתי להבין את ההקלטה, נסה לכתוב")
        return

    await handle_ai_request(from_number, text, user)


async def handle_ai_request(from_number: str, text: str, user):
    """
    מנתח בקשת טקסט חופשי בעברית ומבצע פעולות ניהול משימות.

    פעולות נתמכות: add_task, list_tasks, delete_task, update_task.
    בקשות שאינן נתמכות מקבלות הסבר ידידותי.

    Args:
        from_number: מספר הטלפון של השולח.
        text: תוכן ההודעה שנשלחה (טקסט או תמלול אודיו).
        user: שורת המשתמש מה-DB.
    """
    from bot.menu import get_first_name

    name = get_first_name(user)
    existing_tasks = get_upcoming_tasks(user["id"], days=365)

    try:
        results = parse_user_request(text, name, existing_tasks=existing_tasks)
    except Exception as e:
        logger.error(f"AI parse failed: {e}")
        send_text(from_number, f"{RLM}מצטער, לא הצלחתי לעבד את הבקשה כרגע. נסה שוב מאוחר יותר 🙏")
        return

    if not results:
        send_text(from_number, f"{RLM}מצטער, לא הצלחתי להבין את הבקשה. נסה לנסח אחרת 🙏")
        return

    messages = []
    for item in results:
        action = item.get("action")

        if action == "add_task":
            task_id = create_task(
                user["id"],
                item["title"],
                item.get("due_datetime"),
                item.get("reminders", [])
            )
            for remind_at in item.get("reminders", []):
                schedule_reminder(task_id, user["id"], from_number, item["title"], remind_at)
            due_str = f" ב-{item['due_datetime']}" if item.get("due_datetime") else ""
            reminders_str = f"\n{RLM}⏰ תזכורות הוגדרו" if item.get("reminders") else ""
            messages.append(f"{RLM}✅ נוסף: {item['title']}{due_str}{reminders_str}")

        elif action == "list_tasks":
            tasks = get_upcoming_tasks(user["id"])
            if not tasks:
                messages.append(f"{RLM}אין לך משימות אישיות קרובות 🎉")
            else:
                msg = f"{RLM}📋 המשימות האישיות שלך:\n"
                for t in tasks:
                    due = f" | {t['due_datetime'][:16]}" if t['due_datetime'] else ""
                    msg += f"{RLM}• {t['title']}{due}\n"
                messages.append(msg)

        elif action == "delete_task":
            task_id = item.get("task_id")
            if task_id:
                success = delete_task_by_id(task_id, user["id"])
            else:
                success = delete_task_by_reference(user["id"], item.get("task_reference") or "")
            if not success:
                send_text(from_number, f"{RLM}לא מצאתי משימה תואמת. האם שמה נכון?")
                continue
            messages.append(f"{RLM}✅ המשימה הוסרה")

        elif action == "update_task":
            task_id = item.get("task_id")
            if task_id:
                resolved_id = update_task_by_id(task_id, user["id"], item.get("title"), item.get("due_datetime"))
            else:
                resolved_id = update_task_datetime(user["id"], item.get("task_reference") or "", item.get("due_datetime"))
            if not resolved_id:
                send_text(from_number, f"{RLM}לא מצאתי משימה תואמת. האם שמה נכון?")
                continue
            reminders = item.get("reminders") or []
            logger.debug(f"update_task resolved_id={resolved_id}, reminders={reminders}")
            if reminders:
                add_reminders_to_task(resolved_id, user["id"], reminders)
                for remind_at in reminders:
                    schedule_reminder(resolved_id, user["id"], from_number,
                                      item.get("title") or "תזכורת", remind_at)
            reminders_str = f"\n{RLM}⏰ תזכורות הוגדרו" if reminders else ""
            messages.append(f"{RLM}✅ המשימה עודכנה{reminders_str}")

        else:
            messages.append(
                f"{RLM}לצערי, אני יכול לעזור רק עם ניהול משימות ותזכורות אישיות 😊\n"
                f"{RLM}לדוגמה: ״תור לספר מחר בשעה 11״ או ״תזכיר לי על X ב-Y״"
            )

    if messages:
        send_text(from_number, "\n\n".join(messages))

    send_buttons(from_number, f"{RLM}מה עוד?", [
        {"id": "back_main", "title": "⬅️ תפריט ראשי"}
    ])
