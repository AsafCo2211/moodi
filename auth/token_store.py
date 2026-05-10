"""מודול הצפנה — מאחסן ומשחזר ערכים רגישים מוצפנים עם Fernet."""
from cryptography.fernet import Fernet
from config import ENCRYPTION_KEY


def encrypt(value: str) -> str | None:
    if not value:
        return None
    return Fernet(ENCRYPTION_KEY.encode()).encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    if not value:
        return None
    return Fernet(ENCRYPTION_KEY.encode()).decrypt(value.encode()).decode()
