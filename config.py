from dotenv import load_dotenv
import os

load_dotenv()

# WhatsApp
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")

# Moodle
MOODLE_BASE_URL = os.getenv("MOODLE_BASE_URL", "https://moodle.bgu.ac.il/moodle")
MOODLE_USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MoodleMobile 5.1.1 (51100)"

# Encryption
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# DB
DATABASE_URL = os.getenv("DATABASE_URL", "moodi.db")