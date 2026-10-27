"""Capture the screenshots used in the report (docs/screenshots/*.png).

Uses a TEMPORARY copy of the sample data, so your real data is never touched.

Setup once:   pip install -r requirements-dev.txt   and   playwright install chromium
Run:          python scripts/capture_screenshots.py
"""
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("Playwright is not installed. Run:  pip install -r requirements-dev.txt  &&  playwright install chromium")

from werkzeug.serving import make_server  # noqa: E402

import app as attendance_app  # noqa: E402

OUT = ROOT / "docs" / "screenshots"


def main():
    tmp = Path(tempfile.mkdtemp(prefix="attendance-shots-"))
    shutil.copytree(ROOT / "data", tmp / "data", ignore=shutil.ignore_patterns(".secret_key", "admin.json", "*.tmp"))
    attendance_app.app.config.update(DATA_DIR=str(tmp / "data"), SECRET_KEY="screenshots-only")
    OUT.mkdir(parents=True, exist_ok=True)
    server = make_server("127.0.0.1", 0, attendance_app.app, threaded=True)
    base = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def shot(page, name, full=True):
        page.screenshot(path=str(OUT / name), full_page=full)
        print("saved", name)

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:
                browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()

            page.goto(base + "/login")
            page.fill("input[name=username]", "admin")
            page.fill("input[name=password]", "wrong-password")
            page.click("button[type=submit]")
            shot(page, "01_login_error.png", full=False)
            page.fill("input[name=username]", "admin")
            page.fill("input[name=password]", "admin123")
            shot(page, "02_login.png", full=False)
            page.click("button[type=submit]")
            page.wait_for_url(base + "/")
            page.wait_for_timeout(300)
            shot(page, "03_dashboard.png")

            page.goto(base + "/students")
            shot(page, "04_students.png")
            page.fill("input[name=q]", "ra")
            page.click("button:has-text('Search')")
            shot(page, "05_search.png")

            page.goto(base + "/students/add")
            page.fill("input[name=register_no]", "CS101")   # duplicate on purpose
            page.fill("input[name=name]", "Test Student")
            page.fill("input[name=department]", "Computer Science")
            page.select_option("select[name=year]", "2")
            page.fill("input[name=email]", "not-an-email")
            page.click("button:has-text('Add student')")
            shot(page, "06_form_validation.png")

            page.fill("input[name=register_no]", "CS106")
            page.fill("input[name=email]", "test.student@example.com")
            page.click("button:has-text('Add student')")
            page.wait_for_url("**/students")
            page.goto(base + "/students/CS106/edit")
            shot(page, "07_edit_student.png")
            page.goto(base + "/students/CS104")
            shot(page, "08_student_view.png")

            page.goto(base + "/attendance?department=Computer+Science")
            # click the visible pill (the radio itself is visually hidden), like a real user
            page.click("label.seg-absent:has(input[name=status_CS102])")
            page.click("label.seg-absent:has(input[name=status_CS104])")
            shot(page, "09_mark_attendance.png")
            page.click("button:has-text('Save attendance')")
            page.wait_for_selector(".flash-success")
            shot(page, "10_attendance_saved.png")

            page.goto(base + "/records")
            shot(page, "11_records.png")
            page.goto(base + "/records?status=Absent&department=Electronics")
            shot(page, "12_records_filtered.png")
            page.goto(base + "/percentage?sort=percent-asc")
            shot(page, "13_percentage.png")

            with page.expect_download() as info:
                page.goto(base + "/records")
                page.click("text=Export records CSV")
            info.value.save_as(str(tmp / "export.csv"))
            print("export ok:", (tmp / "export.csv").read_text(encoding="utf-8-sig").splitlines()[0])

            mobile = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True)
            m = mobile.new_page()
            m.goto(base + "/login")
            m.fill("input[name=username]", "admin")
            m.fill("input[name=password]", "admin123")
            m.click("button[type=submit]")
            m.wait_for_url(base + "/")
            shot(m, "14_mobile_dashboard.png")
            m.goto(base + "/attendance")
            shot(m, "15_mobile_attendance.png", full=False)
            browser.close()
    finally:
        server.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    print("Screenshots saved to", OUT)


if __name__ == "__main__":
    main()
