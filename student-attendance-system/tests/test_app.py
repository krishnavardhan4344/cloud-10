"""Automated tests.  From the project folder run:

    python -m unittest discover -s tests -v

Every test uses its own temporary data folder, so your real data is never touched.
"""
import csv
import io
import logging
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as attendance_app  # noqa: E402
from app import app, percent, totals  # noqa: E402

ADMIN_USER, ADMIN_PASS = "admin", "admin123"


def csv_rows(response):
    text = response.get_data(as_text=True).lstrip("﻿")
    return list(csv.reader(io.StringIO(text)))


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="attendance-test-")
        app.config.update(TESTING=True, SECRET_KEY="test-secret", DATA_DIR=self.tmp,
                          LOGIN_MAX_ATTEMPTS=3, LOW_ATTENDANCE_THRESHOLD=75)
        attendance_app.reset_login_throttle()
        self.client = app.test_client()
        self.store = attendance_app.get_store()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers
    def token(self, client=None, url="/login"):
        client = client or self.client
        html = client.get(url).get_data(as_text=True)
        found = re.search(r'name="csrf_token" value="([^"]+)"', html)
        return found.group(1)

    def login(self, user=ADMIN_USER, password=ADMIN_PASS, client=None):
        client = client or self.client
        return client.post("/login", data={"csrf_token": self.token(client), "username": user, "password": password})

    def logged_in(self):
        self.assertEqual(self.login().status_code, 302)
        return self.client

    def post(self, url, data=None, url_for_token="/students"):
        data = dict(data or {})
        data["csrf_token"] = self.token(url=url_for_token)
        return self.client.post(url, data=data)

    def add(self, reg="CS101", name="Aarav Sharma", dept="Computer Science", year="2", **extra):
        form = {"register_no": reg, "name": name, "department": dept, "year": year, "email": "", "phone": ""}
        form.update(extra)
        return self.post("/students/add", form, "/students/add")

    def mark(self, day, statuses, department="", url_token="/attendance"):
        data = {"date": day, "department": department}
        data.update({f"status_{reg}": st for reg, st in statuses.items()})
        return self.post("/attendance", data, url_token)


# ------------------------------------------------------------------ 1. admin login
class LoginTests(BaseCase):
    def test_pages_require_login(self):
        for url in ("/", "/students", "/students/add", "/attendance", "/records", "/percentage",
                    "/export/students.csv", "/export/attendance.csv", "/export/percentage.csv", "/change-password"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/login", r.headers["Location"])

    def test_login_page_loads(self):
        self.assertEqual(self.client.get("/login").status_code, 200)

    def test_login_success_and_dashboard(self):
        client = self.logged_in()
        self.assertEqual(client.get("/").status_code, 200)

    def test_wrong_password(self):
        r = self.login(password="wrong-pass1")
        self.assertEqual(r.status_code, 401)
        self.assertIn("Invalid username or password", r.get_data(as_text=True))

    def test_unknown_user(self):
        r = self.login(user="hacker")
        self.assertEqual(r.status_code, 401)

    def test_empty_credentials(self):
        self.assertEqual(self.login(user="", password="").status_code, 401)

    def test_lockout_after_repeated_failures(self):
        for _ in range(3):
            self.login(password="nope-nope1")
        r = self.login()  # correct password but locked
        self.assertEqual(r.status_code, 401)
        self.assertIn("Too many failed attempts", r.get_data(as_text=True))

    def test_logout(self):
        client = self.logged_in()
        client.post("/logout", data={"csrf_token": self.token(url="/")})
        self.assertEqual(client.get("/students").status_code, 302)

    def test_logout_needs_post(self):
        self.logged_in()
        self.assertEqual(self.client.get("/logout").status_code, 405)

    def test_csrf_protection(self):
        r = self.client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Security token", r.get_data(as_text=True))

    def test_password_is_hashed_in_json_file(self):
        text = (Path(self.tmp) / "admin.json").read_text()
        self.assertNotIn(ADMIN_PASS, text)
        self.assertIn("password_hash", text)

    def test_change_password(self):
        self.logged_in()
        r = self.post("/change-password", {"current_password": ADMIN_PASS, "new_password": "NewPass123",
                                           "confirm_password": "NewPass123"}, "/change-password")
        self.assertEqual(r.status_code, 302)
        self.client.post("/logout", data={"csrf_token": self.token(url="/")})
        self.assertEqual(self.login(password=ADMIN_PASS).status_code, 401)
        attendance_app.reset_login_throttle()
        self.assertEqual(self.login(password="NewPass123").status_code, 302)

    def test_change_password_validation(self):
        self.logged_in()
        bad = [
            {"current_password": "wrong", "new_password": "NewPass123", "confirm_password": "NewPass123"},
            {"current_password": ADMIN_PASS, "new_password": "short1", "confirm_password": "short1"},
            {"current_password": ADMIN_PASS, "new_password": "onlyletters", "confirm_password": "onlyletters"},
            {"current_password": ADMIN_PASS, "new_password": "NewPass123", "confirm_password": "Different123"},
        ]
        for data in bad:
            self.assertEqual(self.post("/change-password", data, "/change-password").status_code, 400, data)

    def test_default_password_warning_on_dashboard(self):
        self.logged_in()
        self.assertIn("default password", self.client.get("/").get_data(as_text=True))


# ------------------------------------------------------------------ 2. student CRUD
class StudentTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.logged_in()

    def test_add_student_and_view_in_list(self):
        r = self.add()
        self.assertEqual(r.status_code, 302)
        page = self.client.get("/students").get_data(as_text=True)
        self.assertIn("Aarav Sharma", page)
        self.assertIn("CS101", page)

    def test_student_saved_in_csv_file(self):
        self.add(email="a@example.com", phone="9876543210")
        text = (Path(self.tmp) / "students.csv").read_text()
        self.assertIn("CS101,Aarav Sharma,Computer Science,2,a@example.com,9876543210", text)

    def test_add_validation_errors(self):
        r = self.add(reg="x y", name="A", dept="", year="9", email="bad", phone="abc")
        self.assertEqual(r.status_code, 400)
        page = r.get_data(as_text=True)
        for text in ("Register number must be", "Name must be", "Department is required", "year of study",
                     "valid email", "Phone must have"):
            self.assertIn(text, page)

    def test_numbers_not_allowed_in_name(self):
        self.assertEqual(self.add(name="R2D2").status_code, 400)

    def test_duplicate_register_number_case_insensitive(self):
        self.add()
        r = self.add(reg="cs101", name="Someone Else")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already exists", r.get_data(as_text=True))

    def test_form_keeps_values_after_error(self):
        r = self.add(name="Valid Name", dept="")
        self.assertIn('value="Valid Name"', r.get_data(as_text=True))

    def test_edit_student(self):
        self.add()
        page = self.client.get("/students/CS101/edit")
        self.assertEqual(page.status_code, 200)
        r = self.post("/students/CS101/edit", {"name": "Aarav S. Sharma", "department": "Maths", "year": "3",
                                               "email": "", "phone": ""}, "/students/CS101/edit")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.store.get_student("CS101")["name"], "Aarav S. Sharma")
        self.assertEqual(self.store.get_student("CS101")["department"], "Maths")

    def test_edit_cannot_change_register_number(self):
        self.add()
        self.post("/students/CS101/edit", {"register_no": "HACK9", "name": "Aarav Sharma",
                                           "department": "Computer Science", "year": "2"}, "/students/CS101/edit")
        self.assertIsNotNone(self.store.get_student("CS101"))
        self.assertIsNone(self.store.get_student("HACK9"))

    def test_edit_validation(self):
        self.add()
        r = self.post("/students/CS101/edit", {"name": "", "department": "X", "year": "2"}, "/students/CS101/edit")
        self.assertEqual(r.status_code, 400)

    def test_view_student(self):
        self.add()
        r = self.client.get("/students/CS101")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Aarav Sharma", r.get_data(as_text=True))

    def test_delete_student_removes_attendance(self):
        self.add()
        self.add(reg="CS102", name="Diya Patel")
        self.mark("2026-01-05", {"CS101": "Present", "CS102": "Absent"})
        r = self.post("/students/CS101/delete")
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(self.store.get_student("CS101"))
        regs = {row["register_no"] for row in self.store.list_attendance()}
        self.assertEqual(regs, {"CS102"})

    def test_delete_requires_csrf(self):
        self.add()
        self.assertEqual(self.client.post("/students/CS101/delete").status_code, 400)
        self.assertIsNotNone(self.store.get_student("CS101"))

    def test_unknown_student_404(self):
        for url in ("/students/NOPE", "/students/NOPE/edit"):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(self.post("/students/NOPE/delete").status_code, 404)

    def test_search_by_name_and_register_number(self):
        self.add()
        self.add(reg="EC201", name="Vikram Singh", dept="Electronics")
        by_name = self.client.get("/students?q=vikram").get_data(as_text=True)
        self.assertIn("Vikram Singh", by_name)
        self.assertNotIn("Aarav Sharma", by_name)
        by_reg = self.client.get("/students?q=cs10").get_data(as_text=True)
        self.assertIn("Aarav Sharma", by_reg)
        self.assertNotIn("Vikram Singh", by_reg)
        self.assertIn("No matching students", self.client.get("/students?q=zzzz").get_data(as_text=True))

    def test_filter_by_department(self):
        self.add()
        self.add(reg="EC201", name="Vikram Singh", dept="Electronics")
        page = self.client.get("/students?department=Electronics").get_data(as_text=True)
        self.assertIn("Vikram Singh", page)
        self.assertNotIn("Aarav Sharma", page)

    def test_html_in_name_is_rejected_or_escaped(self):
        self.assertEqual(self.add(name="<script>alert(1)</script>").status_code, 400)

    def test_csv_formula_injection_is_neutralised_in_export(self):
        self.add(name="Eve =cmd")  # allowed characters; formula chars in name are not
        self.store.add_student({"register_no": "F1", "name": "=HYPERLINK(1)", "department": "D", "year": "1"})
        rows = csv_rows(self.client.get("/export/students.csv"))
        self.assertTrue(any(r[1] == "'=HYPERLINK(1)" for r in rows[1:]))


# ------------------------------------------------------------------ 3. mark attendance
class AttendanceTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.logged_in()
        self.add("CS101", "Aarav Sharma", "Computer Science")
        self.add("CS102", "Diya Patel", "Computer Science")
        self.add("EC201", "Vikram Singh", "Electronics")

    def test_attendance_page_lists_students(self):
        page = self.client.get("/attendance").get_data(as_text=True)
        for name in ("Aarav Sharma", "Diya Patel", "Vikram Singh"):
            self.assertIn(name, page)

    def test_mark_present_and_absent(self):
        r = self.mark("2026-03-02", {"CS101": "Present", "CS102": "Absent", "EC201": "Present"})
        self.assertEqual(r.status_code, 302)
        saved = {(x["register_no"], x["status"]) for x in self.store.list_attendance()}
        self.assertEqual(saved, {("CS101", "Present"), ("CS102", "Absent"), ("EC201", "Present")})

    def test_attendance_saved_in_csv_file(self):
        self.mark("2026-03-02", {"CS101": "Present", "CS102": "Absent", "EC201": "Present"})
        text = (Path(self.tmp) / "attendance.csv").read_text()
        self.assertIn("2026-03-02,CS102,Absent", text)

    def test_marking_again_updates_instead_of_duplicating(self):
        self.mark("2026-03-02", {"CS101": "Present", "CS102": "Present", "EC201": "Present"})
        self.mark("2026-03-02", {"CS101": "Absent", "CS102": "Present", "EC201": "Present"})
        rows = [r for r in self.store.list_attendance() if r["date"] == "2026-03-02"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(next(r for r in rows if r["register_no"] == "CS101")["status"], "Absent")

    def test_existing_values_are_prefilled(self):
        self.mark("2026-03-02", {"CS101": "Absent", "CS102": "Present", "EC201": "Present"})
        page = self.client.get("/attendance?date=2026-03-02").get_data(as_text=True)
        self.assertIn("already saved", page)
        self.assertRegex(page, r'name="status_CS101" value="Absent" checked')

    def test_only_selected_department_is_changed(self):
        self.mark("2026-03-02", {"CS101": "Present", "CS102": "Present", "EC201": "Present"})
        self.mark("2026-03-02", {"EC201": "Absent"}, department="Electronics")
        rows = {r["register_no"]: r["status"] for r in self.store.list_attendance()}
        self.assertEqual(rows["EC201"], "Absent")
        self.assertEqual(rows["CS101"], "Present")

    def test_future_date_rejected(self):
        future = (date.today() + timedelta(days=2)).isoformat()
        r = self.mark(future, {"CS101": "Present", "CS102": "Present", "EC201": "Present"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("future date", r.get_data(as_text=True))
        self.assertEqual(self.store.list_attendance(), [])

    def test_invalid_date_rejected(self):
        r = self.mark("not-a-date", {"CS101": "Present", "CS102": "Present", "EC201": "Present"})
        self.assertEqual(r.status_code, 400)

    def test_unmarked_student_rejected(self):
        r = self.mark("2026-03-02", {"CS101": "Present", "CS102": "Present"})  # EC201 missing
        self.assertEqual(r.status_code, 400)
        self.assertIn("not marked", r.get_data(as_text=True))
        self.assertEqual(self.store.list_attendance(), [])

    def test_invalid_status_rejected(self):
        r = self.mark("2026-03-02", {"CS101": "Late", "CS102": "Present", "EC201": "Present"})
        self.assertEqual(r.status_code, 400)

    def test_attendance_needs_csrf(self):
        r = self.client.post("/attendance", data={"date": "2026-03-02"})
        self.assertEqual(r.status_code, 400)


# ------------------------------------------------------------------ 4/5/7. records, percentage, export
class ReportTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.logged_in()
        self.add("CS101", "Aarav Sharma", "Computer Science")
        self.add("CS102", "Diya Patel", "Computer Science")
        self.add("EC201", "Vikram Singh", "Electronics")
        self.mark("2026-03-02", {"CS101": "Present", "CS102": "Absent", "EC201": "Present"})
        self.mark("2026-03-03", {"CS101": "Present", "CS102": "Absent", "EC201": "Absent"})
        self.mark("2026-03-04", {"CS101": "Absent", "CS102": "Present", "EC201": "Present"})
        self.mark("2026-03-05", {"CS101": "Present", "CS102": "Absent", "EC201": "Present"})

    def test_percentage_formula(self):
        self.assertEqual(percent(3, 4), 75.0)
        self.assertEqual(percent(1, 3), 33.3)
        self.assertEqual(percent(0, 5), 0.0)
        self.assertEqual(percent(5, 5), 100.0)
        self.assertIsNone(percent(0, 0))
        self.assertEqual(totals([{"status": "Present"}, {"status": "Absent"}])["percent"], 50.0)

    def test_percentage_per_student(self):
        page = self.client.get("/percentage").get_data(as_text=True)
        self.assertIn("75.0%", page)   # Aarav 3/4
        self.assertIn("25.0%", page)   # Diya 1/4

    def test_percentage_with_no_records_is_na(self):
        self.add("ME301", "Rahul Verma", "Mechanical")
        self.assertIn("N/A", self.client.get("/percentage?q=rahul").get_data(as_text=True))

    def test_percentage_date_range(self):
        page = self.client.get("/percentage?q=CS101&date_from=2026-03-04&date_to=2026-03-05").get_data(as_text=True)
        self.assertIn("50.0%", page)  # absent on 04, present on 05

    def test_percentage_below_threshold_filter(self):
        page = self.client.get("/percentage?below=1").get_data(as_text=True)
        self.assertIn("Diya Patel", page)       # 25%
        self.assertNotIn("Aarav Sharma", page)  # exactly 75% is not below 75

    def test_percentage_sort(self):
        page = self.client.get("/percentage?sort=percent-asc").get_data(as_text=True)
        self.assertLess(page.index("Diya Patel"), page.index("Aarav Sharma"))

    def test_records_date_wise_summary(self):
        page = self.client.get("/records").get_data(as_text=True)
        for day in ("2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05"):
            self.assertIn(day, page)

    def test_records_filter_by_date_range(self):
        page = self.client.get("/records?date_from=2026-03-03&date_to=2026-03-04").get_data(as_text=True)
        shown = set(re.findall(r'<td data-label="Date">(?:<a [^>]*>)?(\d{4}-\d{2}-\d{2})', page))
        self.assertEqual(shown, {"2026-03-03", "2026-03-04"})

    def test_records_filter_by_status_and_department(self):
        page = self.client.get("/records?status=Absent&department=Electronics").get_data(as_text=True)
        self.assertIn("Vikram Singh", page)
        self.assertNotIn("Aarav Sharma", page)

    def test_records_search(self):
        page = self.client.get("/records?q=diya").get_data(as_text=True)
        self.assertIn("Diya Patel", page)
        self.assertNotIn("Aarav Sharma", page)

    def test_invalid_filters_show_error(self):
        page = self.client.get("/records?date_from=abc").get_data(as_text=True)
        self.assertIn("not valid", page)
        page = self.client.get("/records?date_from=2026-03-05&date_to=2026-03-01").get_data(as_text=True)
        self.assertIn("must not be after", page)

    def test_export_attendance_all(self):
        r = self.client.get("/export/attendance.csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["Content-Type"])
        self.assertIn("attachment", r.headers["Content-Disposition"])
        rows = csv_rows(r)
        self.assertEqual(rows[0], ["Date", "Register No", "Name", "Department", "Status"])
        self.assertEqual(len(rows) - 1, 12)
        self.assertIn(["2026-03-02", "CS102", "Diya Patel", "Computer Science", "Absent"], rows)

    def test_export_attendance_filtered(self):
        r = self.client.get("/export/attendance.csv?date_from=2026-03-03&date_to=2026-03-03&status=Absent")
        rows = csv_rows(r)[1:]
        self.assertEqual({row[1] for row in rows}, {"CS102", "EC201"})
        self.assertIn("2026-03-03", r.headers["Content-Disposition"])

    def test_export_attendance_single_student(self):
        rows = csv_rows(self.client.get("/export/attendance.csv?register_no=CS101"))[1:]
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row[1] == "CS101" for row in rows))

    def test_export_percentage(self):
        rows = csv_rows(self.client.get("/export/percentage.csv"))
        self.assertEqual(rows[0][-1], "Attendance %")
        aarav = next(r for r in rows if r[0] == "CS101")
        self.assertEqual(aarav[3:], ["3", "1", "4", "75.0"])

    def test_export_students(self):
        rows = csv_rows(self.client.get("/export/students.csv"))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0][:3], ["Register No", "Name", "Department"])

    def test_export_with_invalid_filter_is_400(self):
        self.assertEqual(self.client.get("/export/attendance.csv?date_from=bad").status_code, 400)

    def test_export_has_utf8_bom_for_excel(self):
        self.assertTrue(self.client.get("/export/students.csv").data.startswith(b"\xef\xbb\xbf"))


# ------------------------------------------------------------------ 8. dashboard
class DashboardTests(BaseCase):
    def test_empty_dashboard(self):
        self.logged_in()
        self.assertIn("Welcome", self.client.get("/").get_data(as_text=True))

    def test_dashboard_statistics(self):
        self.logged_in()
        self.add("CS101", "Aarav Sharma", "Computer Science")
        self.add("CS102", "Diya Patel", "Computer Science")
        today = date.today().isoformat()
        self.mark(today, {"CS101": "Present", "CS102": "Absent"})
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn("Total students", page)
        self.assertIn("50.0%", page)             # today's and overall percentage
        self.assertIn("1 present · 1 absent", page)
        self.assertIn("Diya Patel", page)         # below 75% list
        self.assertIn("Computer Science", page)   # department summary
        self.assertIn("<svg", page)               # chart

    def test_dashboard_not_marked_yet(self):
        self.logged_in()
        self.add()
        self.mark("2020-01-06", {"CS101": "Present"})
        self.assertIn("Not marked yet", self.client.get("/").get_data(as_text=True))


# ------------------------------------------------------------------ 9. validation, errors, storage
class RobustnessTests(BaseCase):
    def test_404_page(self):
        r = self.client.get("/does-not-exist")
        self.assertEqual(r.status_code, 404)
        self.assertIn("Not Found", r.get_data(as_text=True))

    def test_security_headers(self):
        r = self.client.get("/login")
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertIn("script-src 'self'", r.headers["Content-Security-Policy"])

    def test_unexpected_error_shows_friendly_page(self):
        self.logged_in()
        app.config["PROPAGATE_EXCEPTIONS"] = False
        logging.disable(logging.CRITICAL)  # keep the expected traceback out of the test output
        try:
            with mock.patch.object(attendance_app, "per_student", side_effect=RuntimeError("secret internals")):
                r = self.client.get("/students")
        finally:
            logging.disable(logging.NOTSET)
            app.config["PROPAGATE_EXCEPTIONS"] = None
        self.assertEqual(r.status_code, 500)
        self.assertIn("Server error", r.get_data(as_text=True))
        self.assertNotIn("secret internals", r.get_data(as_text=True))

    def test_data_persists_between_store_instances(self):
        self.store.add_student({"register_no": "P1", "name": "Persist Test", "department": "D", "year": "1"})
        fresh = attendance_app.DataStore(self.tmp)
        self.assertEqual(fresh.get_student("p1")["name"], "Persist Test")

    def test_missing_csv_files_are_recreated(self):
        (Path(self.tmp) / "students.csv").unlink()
        self.assertEqual(self.store.list_students(), [])
        self.assertTrue((Path(self.tmp) / "students.csv").exists())

    def test_excel_style_file_with_bom_and_blank_lines_is_read(self):
        (Path(self.tmp) / "students.csv").write_text(
            "﻿register_no,name,department,year,email,phone,created_at\r\n"
            "A1,Bom Student,Dept,1,,,\r\n\r\n", encoding="utf-8")
        self.assertEqual(self.store.list_students()[0]["name"], "Bom Student")

    def test_natural_sort_order(self):
        for reg in ("S10", "S2", "S1"):
            self.store.add_student({"register_no": reg, "name": "Student " + reg.lower(), "department": "D", "year": "1"})
        self.assertEqual([s["register_no"] for s in self.store.list_students()], ["S1", "S2", "S10"])

    def test_unreadable_data_shows_error_page_not_crash(self):
        self.logged_in()
        (Path(self.tmp) / "admin.json").write_text("{not json")
        # the session is still valid, other pages keep working
        self.assertEqual(self.client.get("/students").status_code, 200)
        logging.disable(logging.CRITICAL)  # keep the expected error line out of the test output
        try:
            r = self.client.get("/")  # dashboard reads admin.json for the password warning
        finally:
            logging.disable(logging.NOTSET)
        self.assertEqual(r.status_code, 500)
        self.assertIn("admin.json", r.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
