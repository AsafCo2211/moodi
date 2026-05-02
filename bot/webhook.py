from fastapi import APIRouter, Request, HTTPException
from config import WHATSAPP_VERIFY_TOKEN
from bot.menu import handle_message
from utils.logger import get_logger

logger = get_logger(__name__)
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

    try:
        entry = body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        if "messages" not in value:
            if "statuses" in value:
                status_obj = value["statuses"][0]
                logger.debug(f"STATUS {status_obj.get('status')} for {status_obj.get('recipient_id')}")
            return {"status": "ok"}

        message = value["messages"][0]
        from_number = message["from"]
        msg_type = message["type"]

        if msg_type == "text":
            text = message["text"]["body"]
            logger.info(f"MSG from {from_number}: text = '{text[:50]}'")
            await handle_message(from_number, "text", text)

        elif msg_type == "interactive":
            interactive = message["interactive"]
            interactive_type = interactive.get("type")

            if interactive_type == "button_reply":
                button_id = interactive["button_reply"]["id"]
                logger.info(f"MSG from {from_number}: button = {button_id}")
                await handle_message(from_number, "button", button_id)

            elif interactive_type == "list_reply":
                list_id = interactive["list_reply"]["id"]
                logger.info(f"MSG from {from_number}: list = {list_id}")
                await handle_message(from_number, "list", list_id)

        elif msg_type == "audio":
            audio_id = message["audio"]["id"]
            logger.info(f"MSG from {from_number}: audio id={audio_id}")
            await handle_message(from_number, "audio", audio_id)

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)

    return {"status": "ok"}
