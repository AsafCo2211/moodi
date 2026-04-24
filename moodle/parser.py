from datetime import datetime
import re
import html

def parse_courses(raw_courses: list) -> list:
    active = [
        {
            "id": c["id"],
            "name": c["displayname"],
            "short_name": c["shortname"],
            "start_date": c.get("startdate", 0)
        }
        for c in raw_courses
        if not c.get("hidden", False)
    ]
    return sorted(active, key=lambda x: x["start_date"], reverse=True)


def parse_assignments(raw_courses: list) -> list:
    """
    מקבל את המטלות הגולמיות ומחזיר רשימה שטוחה של מטלות.
    מסנן מטלות שתאריך ההגשה שלהן עבר כבר יותר מ-30 יום.
    """
    assignments = []
    now = datetime.now().timestamp()

    for course in raw_courses:
        course_name = course.get("fullname", "")

        for assign in course.get("assignments", []):
            due_date = assign.get("duedate", 0)

            # אם אין תאריך הגשה — כולל את המטלה
            # אם יש תאריך הגשה — כולל רק אם לא עברו יותר מ-30 יום
            if due_date > 0 and (now - due_date) > 30 * 24 * 3600:
                continue

            assignments.append({
                "moodle_assign_id": assign["id"],
                "course_name": course_name,
                "assignment_name": assign["name"],
                "due_date": datetime.fromtimestamp(due_date) if due_date else None,
            })

    return assignments


def parse_grades(raw_grades: list, course_name: str) -> list:
    """
    מקבל ציונים גולמיים של קורס אחד ומחזיר רשימה נקייה.
    מסנן פריטים ללא ציון.
    """
    grades = []

    for item in raw_grades:
        grade_str = item.get("graderaw")

        if grade_str is None:
            continue

        try:
            grade_value = float(grade_str)
        except (ValueError, TypeError):
            continue

        grades.append({
            "course_name": course_name,
            "item_name": item.get("itemname", ""),
            "grade": grade_value,
        })

    return grades
def strip_html(text: str) -> str:
    """מסיר תגיות HTML ומפענח HTML entities"""
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    return text.strip()

def extract_item_name(content: str) -> str:
    match = re.search(r'<a[^>]*>([^<]+)</a>', content)
    if match:
        return html.unescape(match.group(1)).strip()
    return strip_html(content)


def parse_grades_table(tabledata: list, course_name: str) -> list:
    """
    מפרסר את טבלת הציונים של gradereport_user_get_grades_table.
    עובד גם על קורסים עם סוגי ציון מעורבים.
    """
    grades = []

    for row in tabledata:
        if 'itemname' not in row or 'grade' not in row:
            continue

        name = extract_item_name(row['itemname'].get('content', ''))
        grade_raw = strip_html(row['grade'].get('content', ''))

        if not name or not grade_raw or grade_raw == '-':
            continue

        try:
            grade_value = float(grade_raw)
        except (ValueError, TypeError):
            continue

        grades.append({
            "course_name": course_name,
            "item_name": name,
            "grade": grade_value,
            "grade_range": strip_html(row.get('range', {}).get('content', '')),
        })

    return grades