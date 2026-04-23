import requests
from config import WHATSAPP_TOKEN, WHATSAPP_PHONE_ID

BASE_URL = f"https://graph.facebook.com/v25.0/{WHATSAPP_PHONE_ID}/messages"

HEADERS = {
    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
    "Content-Type": "application/json"
}


def send_text(to: str, message: str):
    """שולח הודעת טקסט פשוטה"""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    response = requests.post(BASE_URL, headers=HEADERS, json=payload)
    response.raise_for_status()
    return response.json()


def send_buttons(to: str, message: str, buttons: list):
    """
    שולח הודעה עם כפתורים אינטראקטיביים.
    buttons = [{"id": "btn_1", "title": "המטלות שלי"}]
    מקסימום 3 כפתורים.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": message},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": btn["id"],
                            "title": btn["title"]
                        }
                    }
                    for btn in buttons[:3]
                ]
            }
        }
    }
    response = requests.post(BASE_URL, headers=HEADERS, json=payload)
    response.raise_for_status()
    return response.json()


def send_main_menu(to: str, name: str):
    """שולח את התפריט הראשי"""
    send_buttons(
        to=to,
        message=f"היי {name} 👋 מה תרצה לבדוק היום?",
        buttons=[
            {"id": "menu_assignments", "title": "📋 המטלות שלי"},
            {"id": "menu_grades", "title": "🎓 ציונים אחרונים"},
            {"id": "menu_today", "title": "📅 להגשה היום"},
        ]
    )

def send_list(to: str, message: str, button_text: str, sections: list):
    """
    שולח תפריט רשימה אינטראקטיבי.
    sections = [{"title": "כותרת", "rows": [{"id": "id1", "title": "אפשרות"}]}]
    מקסימום 10 שורות סה"כ.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": message},
            "action": {
                "button": button_text,
                "sections": sections
            }
        }
    }
    response = requests.post(BASE_URL, headers=HEADERS, json=payload)
    response.raise_for_status()
    return response.json()