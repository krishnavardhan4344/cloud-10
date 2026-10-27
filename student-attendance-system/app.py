"""Student Attendance Management System
=====================================
Flask web application that stores everything in local files (no database server):

    data/students.csv    - registered students
    data/attendance.csv  - one row per (date, student): Present / Absent
    data/admin.json      - the administrator account (password stored as a hash)

Run it with:   python app.py      (or double-click run_windows.bat)
"""
import csv
import io
import json
import os
import re
import secrets
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent

STUDENT_FIELDS = ["register_no", "name", "department", "year", "email", "phone", "created_at"]
ATTENDANCE_FIELDS = ["date", "register_no", "status"]
STATUSES = ("Present", "Absent")
YEARS = ("1", "2", "3", "4")

DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"  # demo password - change it after the first login


def _int_env(name, default):
    try:
        value = int(os.environ.get(name, default))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


app = Flask(__name__)
app.config.update(
    DATA_DIR=os.environ.get("DATA_DIR") or str(BASE_DIR / "data"),
    LOW_ATTENDANCE_THRESHOLD=_int_env("LOW_ATTENDANCE_THRESHOLD", 75),
    REPORT_DISPLAY_LIMIT=_int_env("REPORT_DISPLAY_LIMIT", 500),
    LOGIN_MAX_ATTEMPTS=_int_env("LOGIN_MAX_ATTEMPTS", 5),
    LOGIN_LOCK_SECONDS=_int_env("LOGIN_LOCK_SECONDS", 300),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=4),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


# =============================================================================
# 1. STORAGE  (CSV + JSON files)
# =============================================================================
class StorageError(Exception):
    """A data file could not be read or written (e.g. it is open in Excel)."""


class DuplicateStudentError(ValueError):
    """The register number already exists."""


class NotFoundError(LookupError):
    """The student does not exist."""


def natural_key(text):
    """Sort 'S2' before 'S10'."""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", text or "")]


class DataStore:
    """Reads and writes the data files. Writes are atomic and protected by a lock."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.students_path = self.data_dir / "students.csv"
        self.attendance_path = self.data_dir / "attendance.csv"
        self.admin_path = self.data_dir / "admin.json"
        self._lock = threading.RLock()
        with self._lock:
            for path, fields in ((self.students_path, STUDENT_FIELDS), (self.attendance_path, ATTENDANCE_FIELDS)):
                if not path.exists() or path.stat().st_size == 0:
                    self._write_csv(path, fields, [])
            if not self.admin_path.exists() or self.admin_path.stat().st_size == 0:
                self._write_json(self.admin_path, {
                    "username": DEFAULT_ADMIN_USER,
                    "password_hash": generate_password_hash(DEFAULT_ADMIN_PASSWORD),
                })

    # ---- low level -------------------------------------------------------
    def _read_csv(self, path, fields):
        try:
            with open(path, newline="", encoding="utf-8-sig") as handle:
                rows = []
                for raw in csv.DictReader(handle):
                    row = {k: (raw.get(k) or "").strip() for k in fields}
                    if row[fields[0]] or row[fields[1]]:
                        rows.append(row)
                return rows
        except FileNotFoundError:
            self._write_csv(path, fields, [])
            return []
        except (OSError, csv.Error, UnicodeDecodeError) as exc:
            raise StorageError(f"Could not read '{path.name}'. If it is open in Excel, close it and try again. ({exc})") from exc

    def _atomic_write(self, path, writer):
        tmp = path.with_name(path.name + ".tmp")
        try:
            with open(tmp, "w", newline="", encoding="utf-8") as handle:
                writer(handle)
            os.replace(tmp, path)
        except OSError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise StorageError(f"Could not save '{path.name}'. If it is open in Excel, close it and try again. ({exc})") from exc

    def _write_csv(self, path, fields, rows):
        def writer(handle):
            w = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        self._atomic_write(path, writer)

    def _write_json(self, path, data):
        self._atomic_write(path, lambda handle: json.dump(data, handle, indent=2))

    # ---- admin -----------------------------------------------------------
    def read_admin(self):
        try:
            with open(self.admin_path, encoding="utf-8") as handle:
                data = json.load(handle)
            if not data.get("username") or not data.get("password_hash"):
                raise ValueError("missing fields")
            return data
        except (OSError, ValueError) as exc:
            raise StorageError("admin.json is damaged. Delete it and restart the app to recreate the default admin.") from exc

    def check_admin(self, username, password):
        admin = self.read_admin()
        password_ok = check_password_hash(admin["password_hash"], password)  # always run: constant-ish time
        return password_ok and username.strip().lower() == admin["username"].lower()

    def set_admin_password(self, new_password):
        with self._lock:
            admin = self.read_admin()
            admin["password_hash"] = generate_password_hash(new_password)
            self._write_json(self.admin_path, admin)

    def uses_default_password(self):
        admin = self.read_admin()
        return check_password_hash(admin["password_hash"], DEFAULT_ADMIN_PASSWORD)

    # ---- students --------------------------------------------------------
    def list_students(self):
        with self._lock:
            rows = self._read_csv(self.students_path, STUDENT_FIELDS)
        return sorted(rows, key=lambda r: (r["department"].lower(), natural_key(r["register_no"])))

    def get_student(self, register_no):
        wanted = (register_no or "").lower()
        return next((s for s in self.list_students() if s["register_no"].lower() == wanted), None)

    def add_student(self, data):
        with self._lock:
            rows = self._read_csv(self.students_path, STUDENT_FIELDS)
            if any(r["register_no"].lower() == data["register_no"].lower() for r in rows):
                raise DuplicateStudentError(f"Register number '{data['register_no']}' already exists.")
            row = {k: data.get(k, "") for k in STUDENT_FIELDS}
            row["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rows.append(row)
            self._write_csv(self.students_path, STUDENT_FIELDS, rows)
            return row

    def update_student(self, register_no, data):
        with self._lock:
            rows = self._read_csv(self.students_path, STUDENT_FIELDS)
            for row in rows:
                if row["register_no"].lower() == register_no.lower():
                    for key in ("name", "department", "year", "email", "phone"):
                        row[key] = data.get(key, row[key])
                    self._write_csv(self.students_path, STUDENT_FIELDS, rows)
                    return row
        raise NotFoundError(f"Student '{register_no}' was not found.")

    def delete_student(self, register_no):
        """Delete the student and all of their attendance records."""
        with self._lock:
            rows = self._read_csv(self.students_path, STUDENT_FIELDS)
            removed = next((r for r in rows if r["register_no"].lower() == register_no.lower()), None)
            if removed is None:
                raise NotFoundError(f"Student '{register_no}' was not found.")
            keep = [r for r in rows if r is not removed]
            records = [r for r in self._read_csv(self.attendance_path, ATTENDANCE_FIELDS)
                       if r["register_no"].lower() != register_no.lower()]
            self._write_csv(self.students_path, STUDENT_FIELDS, keep)
            self._write_csv(self.attendance_path, ATTENDANCE_FIELDS, records)
            return removed

    # ---- attendance ------------------------------------------------------
    def list_attendance(self):
        with self._lock:
            rows = self._read_csv(self.attendance_path, ATTENDANCE_FIELDS)
        return [r for r in rows if r["status"] in STATUSES]

    def save_attendance(self, date_str, entries):
        """Save {register_no: status} for one date, replacing earlier entries of that date."""
        with self._lock:
            known = {s["register_no"].lower(): s["register_no"] for s in self._read_csv(self.students_path, STUDENT_FIELDS)}
            clean = {known[r.lower()]: st for r, st in entries.items() if r.lower() in known and st in STATUSES}
            if not clean:
                return 0
            rows = [r for r in self._read_csv(self.attendance_path, ATTENDANCE_FIELDS)
                    if not (r["date"] == date_str and r["register_no"] in clean)]
            rows.extend({"date": date_str, "register_no": r, "status": st} for r, st in clean.items())
            rows.sort(key=lambda r: (r["date"], natural_key(r["register_no"])))
            self._write_csv(self.attendance_path, ATTENDANCE_FIELDS, rows)
            return len(clean)


_stores = {}


def get_store():
    key = str(Path(app.config["DATA_DIR"]).resolve())
    if key not in _stores:
        _stores[key] = DataStore(key)
    return _stores[key]


# =============================================================================
# 2. VALIDATION + CALCULATIONS
# =============================================================================
REG_RE = re.compile(r"^[A-Za-z0-9_-]{2,20}$")
NAME_RE = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ .'-])*$", re.UNICODE)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9 -]{5,18}[0-9]$")


def clean_student_form(form, require_reg=True):
    data = {
        "register_no": (form.get("register_no") or "").strip(),
        "name": " ".join((form.get("name") or "").split()),
        "department": " ".join((form.get("department") or "").split()),
        "year": (form.get("year") or "").strip(),
        "email": (form.get("email") or "").strip(),
        "phone": (form.get("phone") or "").strip(),
    }
    errors = []
    if require_reg and not REG_RE.match(data["register_no"]):
        errors.append("Register number must be 2-20 characters: letters, numbers, hyphen or underscore (no spaces or slashes).")
    if not (2 <= len(data["name"]) <= 60) or not NAME_RE.match(data["name"]):
        errors.append("Name must be 2-60 characters and contain only letters, spaces, dots, apostrophes or hyphens.")
    if not (1 <= len(data["department"]) <= 40):
        errors.append("Department is required (up to 40 characters).")
    if data["year"] not in YEARS:
        errors.append("Please select the year of study (1-4).")
    if data["email"] and (len(data["email"]) > 100 or not EMAIL_RE.match(data["email"])):
        errors.append("Please enter a valid email address or leave it empty.")
    if data["phone"] and not PHONE_RE.match(data["phone"]):
        errors.append("Phone must have 7-20 digits (spaces, hyphens and a leading + allowed) or be empty.")
    return data, errors


def parse_date(text):
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def percent(present, total):
    """Attendance % = present days / recorded days x 100 (None if nothing recorded)."""
    return round(present * 100 / total, 1) if total > 0 else None


def totals(records):
    present = sum(1 for r in records if r["status"] == "Present")
    absent = sum(1 for r in records if r["status"] == "Absent")
    total = present + absent
    return {"present": present, "absent": absent, "total": total, "percent": percent(present, total)}


def per_student(students, records):
    by_reg = defaultdict(list)
    for r in records:
        by_reg[r["register_no"].lower()].append(r)
    out = []
    for s in students:
        summary = totals(by_reg.get(s["register_no"].lower(), []))
        summary.update(s)
        out.append(summary)
    return out


def per_date(records):
    by_date = defaultdict(list)
    for r in records:
        by_date[r["date"]].append(r)
    rows = []
    for day in sorted(by_date, reverse=True):
        summary = totals(by_date[day])
        summary["date"] = day
        rows.append(summary)
    return rows


def departments_of(students):
    return sorted({s["department"] for s in students if s["department"]}, key=str.lower)


def student_matches(student, q, department):
    """Search by name or register number (case-insensitive, partial match)."""
    if department and student["department"].lower() != department.lower():
        return False
    if q:
        needle = q.lower()
        return needle in student["name"].lower() or needle in student["register_no"].lower()
    return True


def safe_cell(value):
    """Prevent spreadsheet formula injection in exported CSV files."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def csv_response(filename, header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([safe_cell(v) for v in row])
    # The BOM lets Excel on Windows read the file as UTF-8.
    return Response("﻿" + buffer.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def read_filters():
    """Validate the filter fields shared by Records, Percentage and the CSV exports."""
    errors = []
    texts = {k: request.args.get(k, "").strip() for k in ("date_from", "date_to")}
    parsed = {k: (parse_date(v) if v else None) for k, v in texts.items()}
    if texts["date_from"] and parsed["date_from"] is None:
        errors.append("'From' date is not valid (use YYYY-MM-DD).")
    if texts["date_to"] and parsed["date_to"] is None:
        errors.append("'To' date is not valid (use YYYY-MM-DD).")
    if parsed["date_from"] and parsed["date_to"] and parsed["date_from"] > parsed["date_to"]:
        errors.append("'From' date must not be after 'To' date.")
    status = request.args.get("status", "").strip()
    if status and status not in STATUSES:
        errors.append("Unknown status filter.")
        status = ""
    return {
        "date_from": parsed["date_from"].isoformat() if parsed["date_from"] else "",
        "date_to": parsed["date_to"].isoformat() if parsed["date_to"] else "",
        "department": request.args.get("department", "").strip(),
        "q": request.args.get("q", "").strip(),
        "register_no": request.args.get("register_no", "").strip(),
        "status": status,
        "sort": request.args.get("sort", "register").strip(),
        "below": request.args.get("below", "").strip(),
        "errors": errors,
    }


def apply_filters(f):
    """Return (students matching, attendance records of those students inside the date range)."""
    students = get_store().list_students()
    if f["register_no"]:
        students = [s for s in students if s["register_no"].lower() == f["register_no"].lower()]
    students = [s for s in students if student_matches(s, f["q"], f["department"])]
    if f["errors"]:
        return students, []
    wanted = {s["register_no"].lower() for s in students}
    records = [r for r in get_store().list_attendance()
               if r["register_no"].lower() in wanted
               and not (f["date_from"] and r["date"] < f["date_from"])
               and not (f["date_to"] and r["date"] > f["date_to"])]
    return students, records


def filter_args(f, keys=("date_from", "date_to", "department", "q", "register_no", "status", "sort", "below")):
    return {k: f[k] for k in keys if f.get(k)}


# =============================================================================
# 3. SECURITY  (login gate, CSRF, headers, error pages)
# =============================================================================
_failed_logins = {}  # {ip: (count, locked_until)}


def reset_login_throttle():
    _failed_logins.clear()


@app.before_request
def gate():
    g.admin = session.get("admin")
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not expected or not sent or not secrets.compare_digest(sent, expected):
            abort(400, description="Security token missing or expired. Go back, refresh the page and try again.")
    if request.endpoint in (None, "login", "static"):
        return None
    if not g.admin:
        flash("Please log in as administrator to continue.", "info")
        return redirect(url_for("login"))
    return None


@app.context_processor
def template_helpers():
    def csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]
    return {"csrf_token": csrf_token}


@app.template_filter("pct")
def pct_filter(value):
    return "N/A" if value is None else f"{value:.1f}%"


@app.after_request
def add_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "frame-ancestors 'none'; form-action 'self'")
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
    return response


def show_error(status, title, message):
    return render_template("error.html", status=status, title=title, message=message), status


@app.errorhandler(StorageError)
def handle_storage_error(e):
    app.logger.error("Storage error: %s", e)
    return show_error(500, "Data file problem", str(e))


@app.errorhandler(HTTPException)
def handle_http_error(e):
    return show_error(e.code or 500, e.name, e.description or "Something went wrong.")


@app.errorhandler(Exception)
def handle_unexpected_error(e):
    app.logger.exception("Unhandled error: %s", e)
    return show_error(500, "Server error", "Something went wrong. Please go back and try again.")


def ensure_secret_key():
    if app.config.get("SECRET_KEY"):
        return
    key = os.environ.get("SECRET_KEY")
    if not key:
        data_dir = Path(app.config["DATA_DIR"])
        data_dir.mkdir(parents=True, exist_ok=True)
        key_file = data_dir / ".secret_key"
        key = key_file.read_text(encoding="utf-8").strip() if key_file.exists() else ""
        if not key:
            key = secrets.token_hex(32)
            key_file.write_text(key, encoding="utf-8")
    app.config["SECRET_KEY"] = key


ensure_secret_key()


# =============================================================================
# 4. PAGES
# =============================================================================
@app.route("/login", methods=("GET", "POST"))
def login():
    if g.admin:
        return redirect(url_for("dashboard"))
    errors, username = [], ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip = request.remote_addr or "?"
        count, locked_until = _failed_logins.get(ip, (0, 0))
        if locked_until > time.time():
            minutes = max(1, int((locked_until - time.time() + 59) // 60))
            errors.append(f"Too many failed attempts. Try again in about {minutes} minute(s).")
        else:
            if locked_until:  # lock expired
                _failed_logins.pop(ip, None)
                count = 0
            if get_store().check_admin(username, password):
                _failed_logins.pop(ip, None)
                session.clear()
                session["admin"] = get_store().read_admin()["username"]
                session.permanent = True
                flash("Welcome! You are logged in.", "success")
                return redirect(url_for("dashboard"))
            count += 1
            lock = time.time() + app.config["LOGIN_LOCK_SECONDS"] if count >= app.config["LOGIN_MAX_ATTEMPTS"] else 0
            _failed_logins[ip] = (count, lock)
            errors.append("Invalid username or password.")
    return render_template("login.html", errors=errors, username=username,
                           default_user=DEFAULT_ADMIN_USER), (401 if errors else 200)


@app.route("/logout", methods=("POST",))
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/change-password", methods=("GET", "POST"))
def change_password():
    errors = []
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not get_store().check_admin(g.admin, current):
            errors.append("Current password is incorrect.")
        if len(new) < 8 or len(new) > 128 or not (re.search(r"[A-Za-z]", new) and re.search(r"\d", new)):
            errors.append("New password must be 8-128 characters and contain at least one letter and one number.")
        if new != confirm:
            errors.append("New password and confirmation do not match.")
        if new == current and new:
            errors.append("New password must be different from the current password.")
        if not errors:
            get_store().set_admin_password(new)
            flash("Password changed successfully.", "success")
            return redirect(url_for("dashboard"))
    return render_template("change_password.html", errors=errors), (400 if errors else 200)


@app.route("/")
def dashboard():
    store = get_store()
    students = store.list_students()
    records = store.list_attendance()
    threshold = app.config["LOW_ATTENDANCE_THRESHOLD"]
    today_str = date.today().isoformat()
    summaries = per_student(students, records)
    low = sorted((s for s in summaries if s["percent"] is not None and s["percent"] < threshold),
                 key=lambda s: s["percent"])
    by_dept = []
    for dept in departments_of(students):
        members = [s for s in summaries if s["department"] == dept]
        dept_totals = totals([r for r in records if r["register_no"].lower() in {m["register_no"].lower() for m in members}])
        by_dept.append({"department": dept, "count": len(members), "percent": dept_totals["percent"]})
    days = per_date(records)
    chart = list(reversed(days[:7]))  # oldest -> newest
    for i, d in enumerate(chart):
        d["bar_x"] = 30 + i * 62
        d["bar_h"] = round((d["percent"] or 0) * 1.4, 1)
        d["bar_y"] = round(165 - d["bar_h"], 1)
        d["label"] = d["date"][5:]
    return render_template(
        "dashboard.html", student_count=len(students), dept_count=len(departments_of(students)),
        overall=totals(records), todays=totals([r for r in records if r["date"] == today_str]),
        today_str=today_str, low=low[:8], low_count=len(low), by_dept=by_dept, chart=chart,
        day_count=len(days), threshold=threshold, default_password=store.uses_default_password())


# ---- students ---------------------------------------------------------------
@app.route("/students")
def students_list():
    q = request.args.get("q", "").strip()
    department = request.args.get("department", "").strip()
    everyone = get_store().list_students()
    summaries = per_student(everyone, get_store().list_attendance())
    shown = [s for s in summaries if student_matches(s, q, department)]
    return render_template("students.html", students=shown, total=len(everyone),
                           departments=departments_of(everyone), q=q, department=department,
                           threshold=app.config["LOW_ATTENDANCE_THRESHOLD"])


@app.route("/students/add", methods=("GET", "POST"))
def student_add():
    form, errors = {"register_no": "", "name": "", "department": "", "year": "", "email": "", "phone": ""}, []
    if request.method == "POST":
        form, errors = clean_student_form(request.form)
        if not errors:
            try:
                get_store().add_student(form)
            except DuplicateStudentError as exc:
                errors.append(str(exc))
            else:
                flash(f"{form['name']} ({form['register_no']}) was added.", "success")
                return redirect(url_for("students_list"))
    return render_template("student_form.html", form=form, errors=errors, editing=False, years=YEARS,
                           departments=departments_of(get_store().list_students())), (400 if errors else 200)


@app.route("/students/<register_no>/edit", methods=("GET", "POST"))
def student_edit(register_no):
    student = get_store().get_student(register_no)
    if student is None:
        abort(404, description="Student not found.")
    form, errors = dict(student), []
    if request.method == "POST":
        form, errors = clean_student_form(request.form, require_reg=False)
        form["register_no"] = student["register_no"]
        if not errors:
            try:
                get_store().update_student(student["register_no"], form)
            except NotFoundError:
                abort(404, description="Student not found.")
            flash(f"{form['name']} was updated.", "success")
            return redirect(url_for("student_view", register_no=student["register_no"]))
    return render_template("student_form.html", form=form, errors=errors, editing=True, years=YEARS,
                           departments=departments_of(get_store().list_students())), (400 if errors else 200)


@app.route("/students/<register_no>/delete", methods=("POST",))
def student_delete(register_no):
    try:
        removed = get_store().delete_student(register_no)
    except NotFoundError:
        abort(404, description="Student not found.")
    flash(f"{removed['name']} and all their attendance records were deleted.", "success")
    return redirect(url_for("students_list"))


@app.route("/students/<register_no>")
def student_view(register_no):
    student = get_store().get_student(register_no)
    if student is None:
        abort(404, description="Student not found.")
    records = sorted((r for r in get_store().list_attendance()
                      if r["register_no"].lower() == student["register_no"].lower()),
                     key=lambda r: r["date"], reverse=True)
    return render_template("student_view.html", student=student, summary=totals(records), records=records,
                           threshold=app.config["LOW_ATTENDANCE_THRESHOLD"])


# ---- daily attendance ---------------------------------------------------------
@app.route("/attendance", methods=("GET", "POST"))
def attendance_mark():
    source = request.form if request.method == "POST" else request.args
    date_text = source.get("date", "").strip() or date.today().isoformat()
    department = source.get("department", "").strip()
    chosen = parse_date(date_text)
    everyone = get_store().list_students()
    roster = [s for s in everyone if not department or s["department"].lower() == department.lower()]
    posted = {}

    if request.method == "POST":
        if chosen is None:
            flash("Please choose a valid date.", "error")
        elif chosen > date.today():
            flash("You cannot mark attendance for a future date.", "error")
        elif not roster:
            flash("There are no students to mark.", "error")
        else:
            entries = {s["register_no"]: request.form.get(f"status_{s['register_no']}", "") for s in roster}
            posted = entries
            missing = [r for r, st in entries.items() if st not in STATUSES]
            if missing:
                flash(f"Please mark Present or Absent for every student ({len(missing)} not marked).", "error")
            else:
                get_store().save_attendance(chosen.isoformat(), entries)
                present = list(entries.values()).count("Present")
                flash(f"Attendance saved for {chosen.isoformat()}: {present} present, {len(entries) - present} absent.", "success")
                return redirect(url_for("attendance_mark", date=chosen.isoformat(), department=department))

    existing = {}
    if chosen is not None:
        existing = {r["register_no"].lower(): r["status"]
                    for r in get_store().list_attendance() if r["date"] == chosen.isoformat()}
    rows = [{**s, "saved": s["register_no"].lower() in existing,
             "current": posted.get(s["register_no"]) or existing.get(s["register_no"].lower(), "Present")}
            for s in roster]
    return render_template(
        "attendance.html", rows=rows, date_value=(chosen or date.today()).isoformat(),
        max_date=date.today().isoformat(), department=department, departments=departments_of(everyone),
        statuses=STATUSES, already_saved=any(r["saved"] for r in rows), student_total=len(everyone),
    ), (400 if request.method == "POST" else 200)


# ---- date-wise records --------------------------------------------------------
@app.route("/records")
def records():
    f = read_filters()
    for message in f["errors"]:
        flash(message, "error")
    students_f, recs = apply_filters(f)
    if f["status"]:
        recs = [r for r in recs if r["status"] == f["status"]]
    by_reg = {s["register_no"].lower(): s for s in students_f}
    limit = app.config["REPORT_DISPLAY_LIMIT"]
    detail = sorted(recs, key=lambda r: (r["date"], r["register_no"]), reverse=True)
    detail_rows = [{**r, "name": by_reg[r["register_no"].lower()]["name"],
                    "department": by_reg[r["register_no"].lower()]["department"]} for r in detail[:limit]]
    return render_template("records.html", f=f, departments=departments_of(get_store().list_students()),
                           statuses=STATUSES, by_date=per_date(recs), overall=totals(recs), detail=detail_rows,
                           detail_total=len(recs), limit=limit, export_args=filter_args(f))


# ---- attendance percentage ------------------------------------------------------
@app.route("/percentage")
def percentage():
    f = read_filters()
    for message in f["errors"]:
        flash(message, "error")
    students_f, recs = apply_filters(f)
    rows = per_student(students_f, recs)
    threshold = app.config["LOW_ATTENDANCE_THRESHOLD"]
    if f["below"]:
        rows = [r for r in rows if r["percent"] is not None and r["percent"] < threshold]
    sorters = {
        "name": lambda r: r["name"].lower(),
        "percent-asc": lambda r: (r["percent"] is None, r["percent"] or 0),
        "percent-desc": lambda r: (r["percent"] is None, -(r["percent"] or 0)),
    }
    if f["sort"] in sorters:
        rows.sort(key=sorters[f["sort"]])
    else:
        f["sort"] = "register"
    return render_template("percentage.html", f=f, rows=rows, departments=departments_of(get_store().list_students()),
                           overall=totals(recs), threshold=threshold, export_args=filter_args(f))


# ---- CSV exports -----------------------------------------------------------------
@app.route("/export/students.csv")
def export_students():
    summaries = per_student(get_store().list_students(), get_store().list_attendance())
    rows = [[s["register_no"], s["name"], s["department"], s["year"], s["email"], s["phone"],
             s["present"], s["absent"], s["total"], "" if s["percent"] is None else s["percent"]] for s in summaries]
    return csv_response("students.csv", ["Register No", "Name", "Department", "Year", "Email", "Phone",
                                         "Present", "Absent", "Days Recorded", "Attendance %"], rows)


@app.route("/export/attendance.csv")
def export_attendance():
    f = read_filters()
    if f["errors"]:
        abort(400, description=" ".join(f["errors"]))
    students_f, recs = apply_filters(f)
    if f["status"]:
        recs = [r for r in recs if r["status"] == f["status"]]
    by_reg = {s["register_no"].lower(): s for s in students_f}
    recs.sort(key=lambda r: (r["date"], natural_key(r["register_no"])))
    rows = [[r["date"], r["register_no"], by_reg[r["register_no"].lower()]["name"],
             by_reg[r["register_no"].lower()]["department"], r["status"]] for r in recs]
    name = "attendance_report"
    if f["date_from"] or f["date_to"]:
        name += f"_{f['date_from'] or 'start'}_to_{f['date_to'] or 'latest'}"
    return csv_response(name + ".csv", ["Date", "Register No", "Name", "Department", "Status"], rows)


@app.route("/export/percentage.csv")
def export_percentage():
    f = read_filters()
    if f["errors"]:
        abort(400, description=" ".join(f["errors"]))
    students_f, recs = apply_filters(f)
    rows = per_student(students_f, recs)
    if f["below"]:
        rows = [r for r in rows if r["percent"] is not None and r["percent"] < app.config["LOW_ATTENDANCE_THRESHOLD"]]
    out = [[s["register_no"], s["name"], s["department"], s["present"], s["absent"], s["total"],
            "" if s["percent"] is None else s["percent"]] for s in rows]
    return csv_response("attendance_percentage.csv", ["Register No", "Name", "Department", "Present", "Absent",
                                                      "Days Recorded", "Attendance %"], out)


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("PORT", "5000"))
    except ValueError:
        port = 5000
    get_store()  # creates data files + default admin on first run
    print(f"\n  Student Attendance System is running ->  http://{host}:{port}")
    print(f"  Default login:  {DEFAULT_ADMIN_USER} / {DEFAULT_ADMIN_PASSWORD}   (change it after logging in)")
    print("  Keep this window open. Press CTRL+C to stop.\n")
    app.run(host=host, port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
