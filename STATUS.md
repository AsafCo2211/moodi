# מוודי — סטטוס פיתוח
_עודכן: אפריל 2026 | Branch פעיל: `feature/grades-flow`_

---

## 1. מה זה מוודי

בוט WhatsApp לסטודנטים באוניברסיטת בן-גוריון. מתחבר למודל (Moodle BGU) דרך ה-Web Services API ומאפשר לסטודנט לראות את המטלות, הציונים והמועדים שלו בלי להיכנס לאתר. הבוט סורק את מודל כל 5 דקות ועתידו לשלוח התראות פרואקטיביות על ציונים חדשים ומועדי הגשה קרובים.

---

## 2. ארכיטקטורה טכנית

**Stack:**
- Python 3.14, FastAPI + Uvicorn
- SQLite (קובץ `moodi.db`)
- APScheduler `BackgroundScheduler` (polling כל 5 דקות)
- Meta WhatsApp Cloud API v25.0
- Moodle Web Services REST API (BGU: `moodle.bgu.ac.il/moodle`)
- Google Gemini API (קיצור שמות קורסים)

**מודולים ותפקידיהם:**

| קובץ | תפקיד |
|---|---|
| `main.py` | FastAPI app — מאתחל DB, מפעיל scheduler, מאחד router |
| `config.py` | כל משתני הסביבה מ-`.env` |
| `database.py` | `init_db()` + מיגרציות + `get_connection()` |
| `bot/webhook.py` | Endpoint `/webhook` — GET (verify) + POST (קבלת הודעות) |
| `bot/menu.py` | לב הבוט — ניתוב הודעות + בניית כל התגובות |
| `bot/sender.py` | `send_text`, `send_buttons`, `send_list` — קריאות גולמיות ל-WhatsApp API |
| `moodle/client.py` | `call_moodle()` + wrappers לכל פונקציית API |
| `moodle/parser.py` | המרת תגובות גולמיות מ-Moodle ל-dicts נקיים |
| `moodle/poller.py` | מנוע ה-polling — seeding, שמירת מטלות/ציונים, sync סטטוס הגשות |
| `notifications/scheduler.py` | APScheduler — מפעיל `poll_all_users()` כל 5 דקות |
| `notifications/engine.py` | **ריק** — מיועד לשליחת התראות פרואקטיביות |
| `utils/course_namer.py` | קיצור שם קורס דרך Gemini, עם cache בטבלת `courses_cache` |
| `auth/webview.py` | **ריק** — מיועד לתהליך ההרשמה |
| `auth/token_store.py` | **ריק** — מיועד לאחסון מוצפן של wstoken |

**סכמת DB:**
- `users` — טלפון, moodle_user_id, wstoken, token_expires_at, first_name
- `assignments` — מטלות לפי משתמש עם flags: `notified_new`, `notified_today`, `notified_evening`, `is_submitted`
- `grades` — ציונים לפי משתמש עם `grade_range`, `notified`, `detected_at`
- `user_courses` — מיפוי משתמש ↔ קורסים
- `courses_cache` — שמות קורסים מקוצרים (Gemini)

---

## 3. מה עובד היום — End to End

### תשתית
- ✅ FastAPI עולה עם `uvicorn main:app`
- ✅ Webhook מאומת מול Meta (GET verify)
- ✅ POST webhook — מפרסר הודעות טקסט, button_reply ו-list_reply
- ✅ Scheduler עולה ב-startup, נסגר ב-shutdown, ניתן לכיבוי דרך `POLLING_ENABLED=false`

### תפריט ומשתמש
- ✅ כל הודעת טקסט → תפריט ראשי (send_list עם 4 אפשרויות)
- ✅ שם פרטי של המשתמש נשלף מ-Moodle (core_webservice_get_site_info) בזמן ה-seed ונשמר ב-DB
- ✅ RTL עברית נכונה בכל ההודעות (RLM prefix על כל שורה)

### פלו מטלות
- ✅ בחירת קורס מרשימה (רק קורסים עם מטלות פתוחות; "כל הקורסים" אחרון)
- ✅ תצוגת triage: top-3 ממוינות לפי דחיפות + ספירת שאר + overdue בנפרד
- ✅ ארגון דחיפות לפי תאריך (לא שניות): 🔴 היום, 🟡 1-3 ימים, 🟢 4+, ⚪ ללא תאריך, ❗️ באיחור
- ✅ כפתור "הצג הכל" → full view עם כל המטלות
- ✅ בחירת קורס ספציפי או "כל הקורסים"

### פלו ציונים (חדש — feature/grades-flow)
- ✅ בחירת קורס מרשימה (רק קורסים שיש בהם ציונים ב-DB)
- ✅ תצוגת ציונים לקורס בפורמט: `📝 {item_name}` / `📊 ציון: X / max`
- ✅ grade_range נשמר ב-DB ומוצג בפורמט `X / max` אם קיים
- ✅ כפתור "חזור לקורסים" + "תפריט ראשי"

### פלו "להגשה היום"
- ✅ שליפת מטלות שמועד הגשתן הוא היום, לפי תאריך

### Polling
- ✅ `poll_all_users()` — רץ כל 5 דקות
- ✅ Seed אוטומטי של `user_courses` ממודל בסריקה הראשונה
- ✅ שמירת מטלות חדשות עם `INSERT OR IGNORE`
- ✅ ציונים נשלפים תמיד דרך `gradereport_user_get_grades_table` (כולל grade_range)
- ✅ זיהוי ציון חדש (INSERT) vs עדכון ציון (UPDATE + notified=0)
- ✅ sync סטטוס הגשות — כל מטלה לא מוגשת נבדקת דרך `mod_assign_get_submission_status`

---

## 4. מה חסר — לפי סדר עדיפויות

### 🔴 קריטי

**1. מנוע התראות (`notifications/engine.py` — ריק)**
הפולר כבר מזהה ציונים חדשים (`notified=0`) ומטלות חדשות (`notified_new=0`) — אין מי שישלח אותן. זה הערך המרכזי של המוצר.
- צריך: פונקציה `send_pending_notifications(user_id)` שנקראת אחרי כל `poll_user()`
- ציון חדש: `grades WHERE notified=0` → שלח הודעה → `notified=1`
- מטלה חדשה: `assignments WHERE notified_new=0` → שלח הודעה → `notified_new=1`
- מועד הגשה היום (בוקר): `assignments WHERE notified_today=0 AND due_date=today`
- מועד הגשה ערב: `assignments WHERE notified_evening=0 AND due_date=tomorrow`

**2. תהליך הרשמה (`auth/webview.py`, `auth/token_store.py` — ריקים)**
כרגע אין דרך לרשום משתמש חדש. wstoken צריך להיות מוכנס ידנית ל-DB. בלי זה אי אפשר להרחיב מעבר למשתמש מפתח אחד.

### 🟡 חשוב

**3. בדיקת תפוגת wstoken**
עמודת `token_expires_at` קיימת בסכמה אבל לעולם לא נבדקת. אם טוקן פג תוקף, הפולר נכשל בשקט.

**4. משוב שגיאות למשתמש**
כשמודל API נכשל, הפולר מדפיס לקונסול אבל המשתמש לא מקבל הודעה.

**5. `send_main_menu` ב-`sender.py` — dead code**
`sender.py` מכיל `send_main_menu()` שמשתמשת ב-`send_buttons` (3 כפתורים). `menu.py` מגדירה `send_main_menu()` משלה עם `send_list` (4 אפשרויות). הגרסה ב-`sender.py` לא נקראת לעולם — צריך למחוק.

### 🟢 שיפורים

**6. הצפנת wstoken**
`cryptography` כבר ב-`requirements.txt` אבל `auth/token_store.py` ריק. wstoken נשמר plain text ב-DB.

**7. לוגינג**
כל ה-logging דרך `print()`. מומלץ לעבור ל-`logging` standard library עם רמות וconfiguration.

---

## 5. החלטות ארכיטקטורה שכבר התקבלו

| נושא | החלטה | סיבה |
|---|---|---|
| שליפת ציונים | תמיד `get_grades_table` בלבד | ה-API הראשי לא מחזיר `grade_range` |
| Polling on-demand | הוסר — polling רק דרך scheduler | סיבוכיות asyncio, מספיק 5 דקות |
| flags התראות | `notified_new`, `notified_today`, `notified_evening` נפרדים | שליחה פעם אחת בלבד לכל סוג אירוע |
| sync הגשות | בודק כל המטלות הלא מוגשות (לא רק overdue) | סטודנט יכול להגיש מוקדם |
| קיצור שמות קורסים | Gemini עם cache ב-`courses_cache` | שמות קורסים ב-BGU חורגים מ-24 תווים (מגבלת WhatsApp) |
| RTL | כל שורה מתחילה ב-`\u200f` | WhatsApp לא מזהה עברית אוטומטית בhודעות mixed |
| grades flow | בחירת קורס → ציונים לקורס ספציפי בלבד | מגבלת 10 שורות ב-`send_list` + פשטות |
| User-Agent | iPhone MoodleMobile | BGU חוסם user-agents שאינם mobile app |
| extract_item_name | שליפה מתג `<a>` ב-HTML ולא strip_html גולמי | BGU מחזיר שמות פריטים בתוך anchor בלבד |

---

## 6. שאלות פתוחות

1. **הרשמה**: איך סטודנט חדש נרשם? האם הוא שולח username+password בוואטסאפ? האם יש webview שמחובר לבוט?
2. **תזמון התראות**: מתי בדיוק לשלוח התראת "מועד הגשה קרוב"? רק ביום לפני? בוקר ביום הגשה?
3. **תפוגת טוקן**: האם BGU מודל מנפיק טוקנים עם תפוגה? מה עושים כשהטוקן פג — שולחים הודעה למשתמש?
4. **גודל הודעה**: WhatsApp מגביל גוף הודעה ל-4096 תווים. בפלו "כל הקורסים" עם הרבה מטלות — אפשר להגיע לגבול. האם לפגינייט?
5. **סקלה**: כמה משתמשים מתוכננים? אם הרבה — SQLite יספיק לטווח הקצר-בינוני?

---

## 7. הצעדים הבאים

### שלב א׳ — התראות (highest ROI)
1. מימוש `notifications/engine.py`:
   - `send_grade_notifications(user_id)` — שולח הודעה WhatsApp על כל ציון עם `notified=0`, מעדכן ל-`notified=1`
   - `send_assignment_notifications(user_id)` — מטלות חדשות + ריענון יומי ובוקר
2. חיבור לסוף `poll_user()` ב-`moodle/poller.py`

### שלב ב׳ — הרשמה
3. מימוש תהליך רישום משתמש — קבלת פרטים → wstoken → שמירה
4. הצפנת wstoken ב-DB דרך `auth/token_store.py` עם `cryptography`

### שלב ג׳ — ניקיון
5. מחיקת `send_main_menu` המת מ-`sender.py`
6. בדיקת תפוגת טוקן לפני כל poll
7. מעבר מ-`print` ל-`logging`
