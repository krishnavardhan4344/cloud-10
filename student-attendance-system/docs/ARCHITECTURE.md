# Architecture

![Architecture](architecture.svg)

## Layers

| Layer | Files | Responsibility |
|-------|-------|----------------|
| Presentation | `templates/*.html`, `static/css/style.css`, `static/js/script.js` | Pages, responsive layout, small helpers (counters, filters, confirmations) |
| Application | `app.py` | Login gate, CSRF, routes, validation, percentage maths, reports, CSV export, error pages |
| Data | `data/students.csv`, `data/attendance.csv`, `data/admin.json` | Persistent records (atomic writes protected by a lock) |

## Request flow

```mermaid
flowchart TD
    B[Browser] --> G{Request gate}
    G -- POST without valid CSRF token --> E400[400 page]
    G -- not logged in --> L[Redirect to /login]
    G -- ok --> R[Route function]
    R --> V[Validate input]
    V -- invalid --> M[Show form with messages]
    V -- valid --> D[(DataStore: CSV / JSON files)]
    D --> R
    R --> T[Render template / CSV file]
    T --> B
```

## Data model

```mermaid
erDiagram
    STUDENTS ||--o{ ATTENDANCE : has
    STUDENTS {
        text register_no PK
        text name
        text department
        int  year
        text email
        text phone
        text created_at
    }
    ATTENDANCE {
        date date PK
        text register_no PK
        text status "Present or Absent"
    }
    ADMIN {
        text username
        text password_hash
    }
```

## Saving attendance (sequence)

```mermaid
sequenceDiagram
    participant A as Admin (browser)
    participant F as Flask (app.py)
    participant S as DataStore
    participant C as attendance.csv
    A->>F: POST /attendance (date, statuses, CSRF token)
    F->>F: check login, CSRF, date not in future, every student marked
    F->>S: save_attendance(date, entries)
    S->>C: read rows, replace that day's rows
    S->>C: write temp file, then atomic replace
    F-->>A: redirect + "Attendance saved" message
```
