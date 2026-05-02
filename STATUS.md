# מוודי — סטטוס פיתוח
_עודכן: אפריל 2026_

---

## 1. מה זה מוודי

בוט WhatsApp לסטודנטים באוניברסיטת בן-גוריון. מתחבר למודל (Moodle BGU) דרך ה-Web Services API ומאפשר לסטודנט לראות את המטלות, הציונים והמועדים שלו בלי להיכנס לאתר. הבוט סורק את מודל כל 5 דקות, שולח התראות פרואקטיביות על ציונים חדשים ומטלות חדשות, ורץ על שרת פרודקשן 24/7.

---

## 2. ארכיטקטורה טכנית

**Stack:**
- Python 3.14, FastAPI + Uvicorn
- SQLite (קובץ `moodi.db`)
- APScheduler `BackgroundScheduler` (polling כל 5 דקות בין 07:00-23:59)
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
| `notifications/scheduler.py` | APScheduler — polling כל 5 דקות בין 07:00-23:59, סיכום בוקר 10:00, תזכורת ערב 20:00, איפוס flags 01:00 |
| `notifications/engine.py` | מנוע התראות — התראות על ציונים חדשים, מטלות חדשות, סיכום בוקר וערב |
| `utils/course_namer.py` | קיצור שם קורס דרך Gemini, עם cache בטבלת `courses_cache` |
| `auth/webview.py` | תהליך הרשמה — POST /auth/login מתחבר ל-BGU, מחזיר קוד 6 ספרות |
| `auth/token_store.py` | **ריק** — מיועד לאחסון מוצפן של wstoken |

**סכמת DB:**
- `users` — טלפון, moodle_user_id, wstoken, token_expires_at, first_name
- `assignments` — מטלות לפי משתמש עם flags: `notified_new`, `notified_today`, `notified_evening`, `is_submitted`
- `grades` — ציונים לפי משתמש עם `grade_range`, `notified`, `detected_at`
- `user_courses` — מיפוי משתמש ↔ קורסים
- `courses_cache` — שמות קורסים מקוצרים (Gemini)
- `pending_registrations` — קוד הרשמה זמני, wstoken, תפוגה 10 דקות

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

### הרשמה
- ✅ תהליך הרשמה מלא דרך https://moodi.aitoolhub.blog/login
- ✅ אימות מול BGU דרך token.php עם username + password
- ✅ קוד 6 ספרות חד-פעמי עם תפוגה של 10 דקות
- ✅ זיהוי קוד שגוי/פג תוקף עם הודעת שגיאה
- ✅ זיהוי invalidtoken בפולר ושליחת קישור חידוש למשתמש
- ✅ דף HTML מקצועי ונקי בעברית RTL

### התראות
- ✅ התראה מיידית על מטלה חדשה (notified_new)
- ✅ התראה מיידית על ציון חדש/מעודכן (notified)
- ✅ סיכום בוקר יומי בשעה 10:00 (מטלות להגשה היום)
- ✅ תזכורת ערב בשעה 20:00 (מטלות שלא הוגשו)
- ✅ איפוס flags יומי בשעה 01:00
- ✅ polling מוגבל לשעות 07:00-23:59 למניעת חסימות Moodle

### תשתית פרודקשן
- ✅ שרת Oracle Cloud VPS רץ 24/7 (IP: 130.61.50.239)
- ✅ Cloudflare Tunnel עם כתובת קבועה: moodi.aitoolhub.blog
- ✅ systemd services: moodi + cloudflared (מופעלים אוטומטית עם השרת)
- ✅ WhatsApp System User Token קבוע (לא מתאפס)
- ✅ Webhook URL קבוע: https://moodi.aitoolhub.blog/webhook
- ✅ שעון שרת: Asia/Jerusalem (IDT)

---

## 4. מה חסר — לפי סדר עדיפויות

### 🔴 קריטי

*(אין פריטים קריטיים פתוחים)*

### 🟡 חשוב

**1. בדיקת תפוגת wstoken**
עמודת `token_expires_at` קיימת בסכמה אבל לעולם לא נבדקת. אם טוקן פג תוקף, הפולר נכשל בשקט.

**2. משוב שגיאות למשתמש**
כשמודל API נכשל, הפולר מדפיס לקונסול אבל המשתמש לא מקבל הודעה.

**3. `send_main_menu` ב-`sender.py` — dead code**
`sender.py` מכיל `send_main_menu()` שמשתמשת ב-`send_buttons` (3 כפתורים). `menu.py` מגדירה `send_main_menu()` משלה עם `send_list` (4 אפשרויות). הגרסה ב-`sender.py` לא נקראת לעולם — צריך למחוק.

### 🟢 שיפורים

**4. הצפנת wstoken**
`cryptography` כבר ב-`requirements.txt` אבל `auth/token_store.py` ריק. wstoken נשמר plain text ב-DB.

**5. לוגינג**
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

1. **תזמון התראות**: מתי בדיוק לשלוח התראת "מועד הגשה קרוב"? רק ביום לפני? בוקר ביום הגשה?
2. **תפוגת טוקן**: האם BGU מודל מנפיק טוקנים עם תפוגה? מה עושים כשהטוקן פג — שולחים הודעה למשתמש?
3. **גודל הודעה**: WhatsApp מגביל גוף הודעה ל-4096 תווים. בפלו "כל הקורסים" עם הרבה מטלות — אפשר להגיע לגבול. האם לפגינייט?
4. **סקלה**: כמה משתמשים מתוכננים? אם הרבה — SQLite יספיק לטווח הקצר-בינוני?

---

## 7. הצעדים הבאים

### שלב א׳ — בטא (עדיפות ראשונה)
1. גיוס 5 סטודנטים מ-BGU לבטא (מגבלת Test Number)
2. מעקב אחר חוויית משתמש ואיסוף פידבק
3. זיהוי באגים בסביבת פרודקשן אמיתית

### שלב ב׳ — מספר WhatsApp אמיתי
3. רכישת SIM ייעודי למוודי
4. רישום מספר אמיתי ב-Meta Business Manager

### שלב ג׳ — Cloudflare Named Tunnel קבוע
5. הרשמה לחשבון Cloudflare אמיתי עם Named Tunnel
   (כרגע הטונל פועל אבל ה-token עלול להשתנות אם cloudflared יתאפס)

### שלב ד׳ — ניקיון
6. מחיקת send_main_menu המת מ-sender.py
7. בדיקת תפוגת wstoken לפני כל poll
8. מעבר מ-print ל-logging
