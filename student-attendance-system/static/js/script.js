/* Student Attendance System - front-end behaviour (plain JavaScript, no libraries). */
(function () {
  "use strict";

  function $(selector, root) { return (root || document).querySelector(selector); }
  function $all(selector, root) { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); }

  /* ---------- shared: mobile menu, flash messages, confirmations, password toggle ---------- */
  function initCommon() {
    var toggle = $("[data-nav-toggle]");
    var nav = $("#site-nav");
    if (toggle && nav) {
      toggle.addEventListener("click", function () {
        var open = nav.classList.toggle("open");
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
      });
    }

    document.addEventListener("click", function (event) {
      var close = event.target.closest(".flash-close");
      if (close && close.parentElement) { close.parentElement.remove(); }
    });

    // Success messages disappear by themselves after a few seconds.
    $all(".flash-success").forEach(function (el) {
      window.setTimeout(function () { el.remove(); }, 6000);
    });

    // <form data-confirm="Are you sure?"> asks before it submits (used for Delete).
    document.addEventListener("submit", function (event) {
      var message = event.target.getAttribute && event.target.getAttribute("data-confirm");
      if (message && !window.confirm(message)) { event.preventDefault(); }
    });

    $all("[data-toggle-password]").forEach(function (button) {
      button.addEventListener("click", function () {
        var input = document.getElementById(button.getAttribute("data-toggle-password"));
        if (!input) { return; }
        var show = input.type === "password";
        input.type = show ? "text" : "password";
        button.textContent = show ? "Hide" : "Show";
      });
    });
  }

  /* ---------- Mark attendance page: live counters, mark-all, name filter ---------- */
  function initAttendance() {
    var form = $("#attendance-form");
    if (!form) { return; }
    var presentOut = $("#count-present");
    var absentOut = $("#count-absent");

    function updateCounts() {
      var present = form.querySelectorAll('input[type="radio"][value="Present"]:checked').length;
      var absent = form.querySelectorAll('input[type="radio"][value="Absent"]:checked').length;
      presentOut.textContent = present;
      absentOut.textContent = absent;
    }

    form.addEventListener("change", updateCounts);

    $all("[data-mark-all]").forEach(function (button) {
      button.addEventListener("click", function () {
        var value = button.getAttribute("data-mark-all");
        $all("#roster tbody tr", form).forEach(function (row) {
          if (row.hidden) { return; } // only the rows that are currently visible
          var radio = row.querySelector('input[type="radio"][value="' + value + '"]');
          if (radio) { radio.checked = true; }
        });
        updateCounts();
      });
    });

    var filter = $("#name-filter");
    if (filter) {
      filter.addEventListener("input", function () {
        var needle = filter.value.trim().toLowerCase();
        $all("#roster tbody tr", form).forEach(function (row) {
          row.hidden = needle !== "" && (row.getAttribute("data-search") || "").indexOf(needle) === -1;
        });
      });
    }

    // Do not let Enter inside the filter box submit (save) the whole form by accident.
    form.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && event.target === filter) { event.preventDefault(); }
    });

    updateCounts();
  }

  /* ---------- Student form: friendly client-side checks (server validates again) ---------- */
  function initStudentForm() {
    var form = $('form input[name="register_no"]') && $('form input[name="register_no"]').form;
    if (!form || !form.elements.name || !form.elements.department) { return; }
    form.addEventListener("submit", function (event) {
      var problems = [];
      var reg = form.elements.register_no;
      if (!reg.readOnly && !/^[A-Za-z0-9_-]{2,20}$/.test(reg.value.trim())) {
        problems.push("Register number: 2-20 letters, numbers, - or _ (no spaces).");
      }
      if (form.elements.name.value.trim().length < 2) { problems.push("Please enter the student's name."); }
      if (!form.elements.department.value.trim()) { problems.push("Please enter the department."); }
      if (!form.elements.year.value) { problems.push("Please select the year of study."); }
      if (problems.length) {
        event.preventDefault();
        var box = $(".form-errors", form.parentElement) || document.createElement("div");
        box.className = "form-errors";
        box.setAttribute("role", "alert");
        box.textContent = "";
        var list = document.createElement("ul");
        problems.forEach(function (text) {
          var li = document.createElement("li");
          li.textContent = text;
          list.appendChild(li);
        });
        box.appendChild(list);
        if (!box.parentElement) { form.parentElement.insertBefore(box, form); }
        box.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initCommon();
    initAttendance();
    initStudentForm();
  });
})();
