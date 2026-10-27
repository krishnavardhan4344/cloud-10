"""Create sample students and 20 school days of attendance.

    python scripts/generate_sample_data.py            # only if there are no students yet
    python scripts/generate_sample_data.py --reset    # DELETE current data and load the sample data

The sample data ends yesterday, so the dashboard looks realistic today.
"""
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as attendance_app  # noqa: E402

STUDENTS = [
    ("CS101", "Aarav Sharma", "Computer Science", "2", "aarav.sharma@example.com", "9876500001"),
    ("CS102", "Diya Patel", "Computer Science", "2", "diya.patel@example.com", "9876500002"),
    ("CS103", "Rohan Mehta", "Computer Science", "2", "rohan.mehta@example.com", "9876500003"),
    ("CS104", "Ananya Iyer", "Computer Science", "2", "ananya.iyer@example.com", "9876500004"),
    ("CS105", "Karthik Reddy", "Computer Science", "2", "karthik.reddy@example.com", "9876500005"),
    ("EC201", "Vikram Singh", "Electronics", "3", "vikram.singh@example.com", "9876500006"),
    ("EC202", "Sneha Gupta", "Electronics", "3", "sneha.gupta@example.com", "9876500007"),
    ("EC203", "Arjun Das", "Electronics", "3", "arjun.das@example.com", "9876500008"),
    ("EC204", "Priya Kumar", "Electronics", "3", "priya.kumar@example.com", "9876500009"),
    ("ME301", "Rahul Verma", "Mechanical", "1", "rahul.verma@example.com", "9876500010"),
    ("ME302", "Meera Nair", "Mechanical", "1", "meera.nair@example.com", "9876500011"),
    ("ME303", "Imran Khan", "Mechanical", "1", "imran.khan@example.com", "9876500012"),
]

# Number of days (out of 20) each student is absent. Three students end up below 75 %
# (70 %, 65 %, 70 %) so the low-attendance features can be demonstrated.
ABSENT_DAYS = [1, 2, 3, 6, 1, 2, 1, 7, 2, 3, 1, 6]


def main():
    reset = "--reset" in sys.argv
    store = attendance_app.get_store()
    if store.list_students() and not reset:
        print("Data already exists - nothing changed. Use --reset to replace it with the sample data.")
        return
    if reset:
        for student in store.list_students():
            store.delete_student(student["register_no"])
    for reg, name, dept, year, email, phone in STUDENTS:
        store.add_student({"register_no": reg, "name": name, "department": dept,
                           "year": year, "email": email, "phone": phone})
    rng = random.Random(2026)  # fixed seed -> same pattern every time
    # the 20 most recent weekdays (Monday-Friday) ending yesterday
    days, day = [], date.today() - timedelta(days=1)
    while len(days) < 20:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day -= timedelta(days=1)
    absent_on = {reg: set(rng.sample(range(20), ABSENT_DAYS[i])) for i, (reg, *_rest) in enumerate(STUDENTS)}
    for index, day_text in enumerate(days):
        entries = {reg: ("Absent" if index in absent_on[reg] else "Present") for reg, *_rest in STUDENTS}
        store.save_attendance(day_text, entries)
    marked = len(days)
    print(f"Loaded {len(STUDENTS)} students and {marked} days of attendance into {store.data_dir}")


if __name__ == "__main__":
    main()
