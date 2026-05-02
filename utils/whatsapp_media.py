import requests
from config import WHATSAPP_TOKEN
from utils.logger import get_logger

logger = get_logger(__name__)


def download_whatsapp_audio(media_id: str) -> bytes | None:
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    try:
        r = requests.get(
            f"https://graph.facebook.com/v25.0/{media_id}",
            headers=headers,
            timeout=10
        )
        r.raise_for_status()
        url = r.json().get("url")
        if not url:
            logger.error(f"No URL in media response for {media_id}")
            return None

        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        return r.content
    except Exception as e:
        logger.error(f"Failed to download audio {media_id}: {e}")
        return None
