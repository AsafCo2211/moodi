from google import genai
from config import GEMINI_API_KEY
from database import get_connection

client = genai.Client(api_key=GEMINI_API_KEY)


def get_short_name(course_id: int, full_name: str) -> str:
    conn = get_connection()
    cached = conn.execute(
        "SELECT short_name FROM courses_cache WHERE moodle_course_id = ?",
        (course_id,)
    ).fetchone()

    if cached:
        conn.close()
        return cached["short_name"]

    short = _shorten_with_gemini(full_name)

    conn.execute(
        "INSERT OR IGNORE INTO courses_cache (moodle_course_id, full_name, short_name) VALUES (?, ?, ?)",
        (course_id, full_name, short)
    )
    conn.commit()
    conn.close()
    return short


def _shorten_with_gemini(full_name: str) -> str:
    try:
        # פרומפט משופר - "System Instruction" סטייל
        prompt = (
            f"Task: Shorten this university course name.\n"
            f"Constraints:\n"
            f"- Max 3 words\n"
            f"- Max 20 characters\n"
            f"- Language: Same as input\n"
            f"- Output: Only the shortened name, no punctuation, no explanations.\n"
            f"Name: {full_name}"
        )
        
        # שים לב: המודל ללא קידומת models/
        response = client.models.generate_content(
            model="gemini-2.5-flash", # <--- במקום ה-lite
            contents=prompt
        )
        
        if not response.text:
            raise ValueError("Empty response from Gemini")
            
        short = response.text.strip()
        
        # ניקוי גרשיים שהמודל לפעמים מוסיף
        short = short.replace('"', '').replace("'", "")
        
        # חיתוך בטיחותי ל-WhatsApp (מגבלת 24 תווים)
        if len(short) > 24:
            short = short[:23] + "…"
            
        return short
        
    except Exception as e:
        print(f"DEBUG - Gemini Error: {e}")
        # Fallback בסיסי אם ה-API נכשל
        return full_name[:23] + "…" if len(full_name) > 24 else full_name