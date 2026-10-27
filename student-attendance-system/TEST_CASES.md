# Test Cases

Two kinds of tests are provided:

1. **Automated** - 71 tests in `tests/test_app.py` (`run_tests.bat` or `python -m unittest discover -s tests -v`).
2. **Manual** - the checklist below (use the sample data that ships with the project; log in as `admin` / `admin123`).

## Manual test cases

| ID | Feature | Steps | Expected result |
|----|---------|-------|-----------------|
| TC-01 | Login protection | Open `/students` without logging in | Redirected to the login page |
| TC-02 | Login (valid) | Enter `admin` / `admin123` | Dashboard opens, "Welcome" message |
| TC-03 | Login (invalid) | Enter a wrong password | "Invalid username or password." |
| TC-04 | Login lock-out | Enter a wrong password 5 times | "Too many failed attempts" even for the right password |
| TC-05 | Logout | Click **Log out**, then press the browser Back button and refresh | Login page; no data visible |
| TC-06 | Change password | Click `admin` -> enter current + new password (letter + number, 8+) | "Password changed"; new password works, old one does not |
| TC-07 | Change password (invalid) | Use a wrong current password / short new password / mismatching confirmation | Red error message for each case |
| TC-08 | Add student | Students -> Add: `CS106`, `Test Student`, `Computer Science`, Year 2 | Student appears in the list |
| TC-09 | Add - validation | Leave name empty; use e-mail `abc`; phone `xyz` | Error messages, typed values remain |
| TC-10 | Add - duplicate | Add register number `CS101` again (or `cs101`) | "already exists" |
| TC-11 | Edit student | Edit `CS106`, change the department | "was updated"; new department shown; register number field is read-only |
| TC-12 | View student | Click a student's name | Details, percentage, history table |
| TC-13 | Delete student | Delete `CS106`, confirm | Removed from list; their attendance rows are gone from `data/attendance.csv` |
| TC-14 | Delete - cancel | Click Delete, press Cancel in the dialog | Nothing is deleted |
| TC-15 | Search by name | Students -> search `priya` | Only Priya Kumar |
| TC-16 | Search by register no. | Search `EC2` | The four Electronics students |
| TC-17 | Search - no result | Search `zzzz` | "No matching students" |
| TC-18 | Department filter | Choose *Mechanical* | Only Mechanical students |
| TC-19 | Mark attendance | Mark attendance (today) -> set 2 students Absent -> Save | "Attendance saved ...: X present, 2 absent" |
| TC-20 | Live counters | Click Absent/Present pills | Counters at the bottom change immediately |
| TC-21 | Mark all | Click **All absent**, then **All present** | All radio buttons switch |
| TC-22 | Update existing day | Load today again, change one student, Save | Updated; the day still has one row per student in `attendance.csv` |
| TC-23 | Future date | Type a future date manually (date picker blocks it) via the URL `?date=2099-01-01` and Save | "You cannot mark attendance for a future date." |
| TC-24 | Records - all | Open Records | One summary row per date, detailed list below |
| TC-25 | Records - range | From = To = a single date | Only that day |
| TC-26 | Records - status | Status = Absent | Only Absent rows |
| TC-27 | Records - invalid date | Use the URL `/records?date_from=abc` | Red "not valid" message, no crash |
| TC-28 | Percentage values | Percentage page: pick any student, divide *Present* by *Days* and multiply by 100 (e.g. Priya Kumar: 18 present of 20 days) | Same value as the Percentage column (90.0 %) |
| TC-29 | Low attendance | Tick *Only below 75 %* | The 3 sample students under 75 % (Ananya Iyer 70 %, Arjun Das 65 %, Imran Khan 70 %) shown in red |
| TC-30 | Percentage - N/A | Add a new student, open Percentage | New student shows N/A |
| TC-31 | Export students | Students -> Export CSV | `students.csv` downloads, opens in Excel with percentage column |
| TC-32 | Export records | Apply a date filter, click Export records CSV | File contains only the filtered rows |
| TC-33 | Export percentage | Percentage -> Export percentage CSV | One row per student with Attendance % |
| TC-34 | Dashboard | Open Dashboard | Total students 12, overall %, "Below 75 %" = 3, chart with up to 7 bars, department table |
| TC-35 | Dashboard - today | Mark today's attendance, reopen Dashboard | "Today" card shows the percentage |
| TC-36 | Unknown page | Open `/students/NOPE` or `/abc` | Friendly 404 page |
| TC-37 | Data file open in Excel | Open `data\students.csv` in Excel, add a student in the app | Clear message to close Excel; app keeps running |
| TC-38 | Responsive | Narrow the window to phone width | Menu button, tables become cards |
| TC-39 | Persistence | Stop the app (CTRL+C), start it again | All students/attendance still there |
| TC-40 | Default-password warning | Log in with `admin123` | Red banner on the Dashboard until the password is changed |

## Automated test coverage

| Area | Tests (examples) |
|------|------------------|
| Admin login | pages need login, valid/invalid/empty login, lock-out, logout (POST only), CSRF, hashed password in `admin.json`, change password + validation |
| Students | add, saved in CSV, validation (each rule), duplicates (case-insensitive), edit, register number locked, view, delete removes attendance, 404s, search by name / register number, department filter, XSS rejected |
| Attendance | page lists students, present/absent saved, saved in CSV, update instead of duplicate, prefilled values, department-only update, future/invalid date, unmarked student, invalid status, CSRF |
| Reports | percentage formula, per-student %, N/A, date range, below-threshold, sort, date-wise summary, date/status/department/search filters, invalid filters |
| Export | records, filtered, single student, percentage, students, invalid filter -> 400, UTF-8 BOM, formula-injection protection |
| Dashboard | empty state, statistics, "not marked yet" |
| Robustness | 404 page, security headers, friendly 500 page, persistence, recreated missing files, Excel-style CSV (BOM, blank lines), natural sort, damaged `admin.json` |
