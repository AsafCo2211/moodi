from fastapi import APIRouter, Request, HTTPException
from config import WHATSAPP_VERIFY_TOKEN
from bot.menu import handle_message

router = APIRouter()


@router.get("/webhook")
async def verify_webhook(request: Request):
    """
    Meta שולחת GET request לאימות ה-Webhook.
    אנחנו צריכים להחזיר את ה-challenge שהיא שולחת.
    """
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        return int(challenge)

    raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/webhook")
async def receive_message(request: Request):
    """
    Meta שולחת POST request עם כל הודעה נכנסת.
    אנחנו מוציאים את המידע הרלוונטי ומעבירים לתפריט.
    """
    body = await request.json()
    print("WEBHOOK BODY:", body)

    try:
        entry = body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        # אם אין הודעות — התעלם
        if "messages" not in value:
            return {"status": "ok"}

        message = value["messages"][0]
        from_number = message["from"]
        msg_type = message["type"]

        # הודעת טקסט רגילה
        if msg_type == "text":
            text = message["text"]["body"]
            await handle_message(from_number, "text", text)

        # לחיצה על כפתור
        elif msg_type == "interactive":
            interactive = message["interactive"]
            interactive_type = interactive.get("type")
            
            if interactive_type == "button_reply":
                button_id = interactive["button_reply"]["id"]
                await handle_message(from_number, "button", button_id)
            
            elif interactive_type == "list_reply":
                list_id = interactive["list_reply"]["id"]
                await handle_message(from_number, "list", list_id)

    except Exception as e:
        print("ERROR:", e)
        import traceback
        traceback.print_exc()

    return {"status": "ok"}