# הקלטות — מסמך טכני

## 1. סקירה כללית

הפיצ'ר מאפשר למשתמשי מודי לצפות בהקלטות שיעורים ותרגולים ישירות מהדאשבורד, ללא צורך בכניסה ידנית למודל. הנתונים מגיעים מהבלוק `blocks/video` שמותקן על שרת BGU Moodle, אשר מציג רשימת סרטונים לפי קורס.

הפיצ'ר נבנה כי:
- הקלטות הן אחד המשאבים הנפוצים ביותר שסטודנטים מחפשים במודל
- הגישה הנוכחית דורשת ניווט ידני בתוך ממשק מודל המסורבל
- מודי כבר מחזיק wstoken — ניתן לנצל אותו לאוטומציה מלאה

---

## 2. תהליך הגילוי

### מה ניסינו ומה לא עבד

| גישה | תוצאה |
|---|---|
| `mod_opencast_*`, `tool_opencast_*` | ❌ לא מותקן ב-BGU |
| `mod_zoom_get_recordings` | ❌ לא חשוף ב-WS |
| `mod_videostream_*` | ❌ פלאגין קיים אך ללא WS functions |
| `block_video_get_*`, `local_video_*` | ❌ אין רשומות ב-`external_functions` |
| `core_course_get_contents` → `.mp4` | ✅ עובד — 30 קבצים בקורס בסיסי נתונים |
| `core_course_get_contents` → `videostream` | ✅ מטא-דאטה בלבד, URL לדף Moodle |

### הפתרון שנמצא

BGU משתמשת בבלוק מותאם אישית בנתיב:
```
/moodle/blocks/video/videoslist.php?courseid=X&page=N
```

הבלוק מציג טבלת HTML עם שם הסרטון, שם המרצה, משך, ותאריך. אין API — רק HTML scraping.

הבעיה: הדף דורש **MoodleSession** תקפה. wstoken לא עובד כ-URL param ולא כ-cookie.

הפתרון: **`tool_mobile_get_autologin_key`** — פונקציית Moodle WS רשמית שמחזירה מפתח חד-פעמי לכניסה אוטומטית דרך הדפדפן.

---

## 3. תהליך האימות

### שלב 1 — רישום (קיים, דורש שינוי)

`auth/webview.py` → `POST /auth/login` קורא ל-`token.php` ומקבל:
```json
{ "token": "wstoken_value", "privatetoken": "privatetoken_value" }
```

`privatetoken` נשמר כעת ב-DB (מוצפן). הוא נדרש לשלב הבא.

### שלב 2 — יצירת autologin key

```python
result = call_moodle(wstoken, "tool_mobile_get_autologin_key", {
    "privatetoken": privatetoken
})
# result = {"key": "KEY_VALUE", "autologinurl": "https://...", "warnings": []}
```

**מגבלה קריטית:** ניתן לייצר מפתח פעם אחת בכל 6 דקות לכל משתמש. ניסיון מוקדם יותר מחזיר שגיאה.

### שלב 3 — המרה ל-MoodleSession

```
GET https://moodle.bgu.ac.il/moodle/auth/mnet/autologin.php
    ?key=KEY_VALUE
    &userid=MOODLE_USER_ID
```

התגובה כוללת redirect עם Set-Cookie: `MoodleSession=SESSION_VALUE`. שומרים את ה-cookie.

### שלב 4 — גרידת רשימת הסרטונים

```
GET /moodle/blocks/video/videoslist.php?courseid=X&page=N
Cookie: MoodleSession=SESSION_VALUE
```

מחזיר HTML. מפענחים עם regex את הטבלה.

### שלב 5 — ניהול Session

- Session תקפה כ-**4 שעות** (`sessiontimeout=14400` בהגדרות Moodle)
- מאחסנים `moodle_session` + `session_expires` ב-DB
- לפני כל בקשה — בודקים אם פג תוקף. אם כן, מייצרים מפתח חדש
- אם עברו פחות מ-6 דקות מהפקה האחרונה → מחזירים status `reconnecting`

### תרשים זרימה

```
[wstoken + privatetoken]
        ↓
tool_mobile_get_autologin_key
        ↓
autologin.php → MoodleSession cookie
        ↓
GET videoslist.php (עם cookie)
        ↓
HTML parsing → רשימת סרטונים
```

---

## 4. מודל הנתונים

### שינויים בטבלת `users`

```sql
ALTER TABLE users ADD COLUMN private_token TEXT;          -- מוצפן עם Fernet
ALTER TABLE users ADD COLUMN moodle_session TEXT;         -- מוצפן עם Fernet
ALTER TABLE users ADD COLUMN session_expires DATETIME;
ALTER TABLE users ADD COLUMN autologin_last_at DATETIME;  -- מניעת קריאות תכופות
```

### טבלה חדשה: `recording_watched`

```sql
CREATE TABLE IF NOT EXISTS recording_watched (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    video_id     TEXT NOT NULL,    -- מזהה מ-videoslist (id או hash)
    course_id    INTEGER NOT NULL,
    watched_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, video_id)
);
```

---

## 5. אבטחה

- `private_token` ו-`moodle_session` מאוחסנים **מוצפנים** עם Fernet (ספריית `cryptography`)
- `ENCRYPTION_KEY` קיים כבר ב-`.env` — אותו מפתח שמשמש לאחסון wstoken
- ההצפנה מממומשת ב-`auth/token_store.py` (כבר קיים כ-stub)
- Session cookie לא נחשף ל-frontend — כל הבקשות עוברות דרך ה-backend
- endpoint `/api/recordings/open` מבצע redirect עם session header בצד השרת, לא מעביר cookie ל-client

---

## 6. API Endpoints

### `GET /api/recordings/courses`
מחזיר רשימת הקורסים של המשתמש (מ-`user_courses`).

**Response:**
```json
[{"course_id": 65602, "course_name": "מודלים חישוביים סמ 2"}]
```

---

### `GET /api/recordings/list?course_id=X`
מחזיר את רשימת הסרטונים לקורס נתון.

מנגנון פנימי:
1. בדיקת session תקפה ב-DB
2. אם פגה — `tool_mobile_get_autologin_key` → session חדשה
3. GET `videoslist.php` → parse HTML
4. מיזוג עם `recording_watched` → הוספת שדה `watched`

**Response:**
```json
[{
  "video_id": "abc123",
  "name": "שיעור 3 — אוטומטים",
  "lecturer": "פרופ׳ פיסמן",
  "duration": "01:12:34",
  "date": "2024-11-10",
  "watched": false
}]
```

**Errors:**
- `503 reconnecting` — מפתח autologin לא ניתן להפקה עדיין (פחות מ-6 דקות)
- `401` — session לא ניתנת לחידוש (privatetoken null) → יש להתחבר מחדש

---

### `POST /api/recordings/watched`
מסמן סרטון כנצפה.

**Body:** `{"course_id": X, "video_id": "abc123"}`

---

### `GET /api/recordings/open?video_id=X&course_id=Y`
מחזיר redirect לדף הסרטון ב-BGU עם session תקפה.

מנגנון: backend מוסיף את `MoodleSession` כ-cookie ב-redirect response, כך שהדפדפן פותח את הדף כמחובר.

---

## 7. מקרי קצה

| מצב | טיפול |
|---|---|
| Session פגה + פחות מ-6 דקות מהפקה אחרונה | status 503 + הודעה "מתחבר מחדש, נסה שוב בעוד X שניות" |
| `private_token` null (משתמש ישן) | status 401 + הפניה ל-`/login?phone=X` לחידוש חיבור |
| `videoslist.php` שינה מבנה HTML | regex נכשל → fallback: מחזיר URL ישיר לדף Moodle |
| קורס ללא הקלטות | מחזיר רשימה ריקה `[]` |
| autologin key נוצר והמשתמש בוטל ממודל | autologin.php מחזיר שגיאה → נרשם ב-log, session לא נשמרת |

---

## 8. ממשק משתמש (דאשבורד)

הטאב **"הקלטות"** כבר קיים ב-`templates/dashboard.html` כ-placeholder.

### מבנה הממשק

```
[בחר קורס ▼]    [שעור / תרגיל ▼]    [מרצה ▼]
─────────────────────────────────────────────
📹 שיעור 1 — אוטומטים סופיים
   פרופ׳ פיסמן | 1:12:34 | 10/11/2024
   [צפייה ↗]  [✓ נצפה]

📹 תרגול 3 — בנייה ממינימום
   ד״ר בן דניאל | 0:45:10 | 17/11/2024
   [צפייה ↗]
```

### אינטראקציות

- **"צפייה"** → `GET /api/recordings/open?video_id=X&course_id=Y` → פתיחה ב-tab חדש
- **"נצפה"** → `POST /api/recordings/watched` → עדכון UI מקומי
- **מצב reconnecting** → spinner + טקסט "מתחבר מחדש..." + ספירה לאחור בשניות
- **privatetoken null** → banner כחול: "יש להתחבר מחדש כדי לפעיל הקלטות" + כפתור "חידוש חיבור"

---

## 9. סדר מימוש

| שלב | קובץ | תיאור |
|---|---|---|
| 1 | `auth/token_store.py` | encrypt/decrypt עם Fernet |
| 2 | `database.py` | עמודות חדשות + טבלת `recording_watched` |
| 3 | `auth/webview.py` | שמירת `privatetoken` בעת רישום |
| 4 | `moodle/recordings.py` | ניהול session + גרידת `videoslist.php` |
| 5 | `auth/dashboard.py` | endpoints חדשים |
| 6 | `templates/dashboard.html` | UI טאב הקלטות |

### תלויות

- `cryptography` — כבר ב-`requirements.txt`
- `beautifulsoup4` או regex טהור — לפענוח HTML של `videoslist.php`
- אין תלויות חיצוניות חדשות נדרשות
