# ExamCraft AI — Backend

> Enterprise Multi-Tenant AI-Powered Question Paper Generation, Examination, and Assessment Platform.

---

## 1. System Requirements & Scope

ExamCraft AI is built to automate academic assessment creation with strict multi-tenant isolation, source-grounded generative AI question authoring, blueprint-driven paper generation, and assessment workflows.

The system scope **strictly excludes** general LMS/ERP functionality (such as fee collection, attendance management, general timetable scheduling, and general assignment submission).

### The 20 Documented System Modules

1. **M1. User & Access Management** (Phase 1)
2. **M2. Academic Structure & Syllabus Management** (Phase 1)
3. **M3. Question Bank Management** (Phase 1)
4. **M4. AI Question Generation Engine** (Phase 1 — Google Gemini API backend)
5. **M5. Question Verification & Review** (Phase 1)
6. **M6. Blueprint Paper Generation** (Phase 1)
7. **M7. Secure Paper Workflow** (Phase 2)
8. **M8. Audit & Traceability** (Phase 2)
9. **M9. Online Exam Delivery** (Phase 2)
10. **M10. Anti-Collusion & Integrity Monitoring** (Phase 2)
11. **M11. Coding Exam Module** (Phase 2)
12. **M12. Automated Evaluation** (Phase 2)
13. **M13. Handwritten Answer Sheet Evaluation** (Phase 2 — OCR)
14. **M14. Revaluation & Grievance** (Phase 2)
15. **M15. Analytics & Item Analysis** (Phase 2)
16. **M16. Outcome Attainment Reporting (CO/PO)** (Phase 2)
17. **M17. Exam Administration** (Phase 2)
18. **M18. Notification Service** (Phase 2)
19. **M19. Student Learning Support** (Phase 2)
20. **M20. Early-Warning Analytics** (Phase 2)

---

## 2. Technology Stack

- **Runtime:** Python 3.11 / 3.12
- **Framework:** Django 5.2 LTS & Django REST Framework 3.18+
- **Database:** PostgreSQL hosted on Supabase (accessed via `dj-database-url` and `psycopg` 3.3+)
- **Authentication:** JWT via `djangorestframework-simplejwt` with refresh token rotation and token blacklist
- **API Documentation:** OpenAPI 3.0 via `drf-spectacular` (Swagger UI & ReDoc)
- **AI Integration:** Google Gemini API via official `google-genai` SDK
- **Testing:** `pytest` + `pytest-django`

---

## 3. Local Execution & Setup Instructions

### 3.1 Clone & Environment Setup

```bash
# Create and activate Python virtual environment
python3 -m venv venv
source venv/bin/activate

# Install backend dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.2 Configure Environment Variables

Copy the example template and supply your Supabase and Gemini credentials:

```bash
cp .env.example .env
```

Edit `.env` with your private parameters:

```ini
DJANGO_SECRET_KEY="your-production-secret-key"
DJANGO_DEBUG="False"
DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,your-domain.com"

# Supabase PostgreSQL connection string (Transaction pooler or Direct)
DATABASE_URL="postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres?sslmode=require"

# Google Gemini API Key
GEMINI_API_KEY="your-gemini-api-key"
GEMINI_MODEL="gemini-3.8-flash"
```

### 3.3 Apply Migrations & Verify

```bash
# Run database migrations against Supabase PostgreSQL
python manage.py migrate

# Perform Django system check
python manage.py check

# Run automated tests
pytest
```

### 3.4 Start the Backend Server

```bash
# Development server
python manage.py runserver 0.0.0.0:8000

# Production server via Gunicorn
gunicorn examcraft.wsgi:application --bind 0.0.0.0:8000 --workers 4
```

---

## 4. API Documentation & Health Endpoints

- **Swagger UI:** `http://localhost:8000/api/v1/docs/`
- **ReDoc:** `http://localhost:8000/api/v1/redoc/`
- **OpenAPI Schema (JSON/YAML):** `http://localhost:8000/api/v1/schema/`
- **Service Health Check:** `GET /api/v1/health/`
- **Database Health Check:** `GET /api/v1/health/database/` (Safe status check shielded against credential leaks)

## 5. M9 Online Exams & M10 Integrity Monitoring

Exam administrators (institute administrators, or exam staff with the `controller`,
`exam_admin`, or `exam_manager` permission) schedule completed generated papers for
a batch and optionally a section. Exams remain hidden from students until published.
Student access requires an active student membership and placement, a matching batch
and section, and a program/semester subject enrollment.
Since no retake policy exists in the current schema, each placement has one attempt per
scheduled exam; an in-progress attempt can be resumed but a submitted attempt cannot be restarted.

Student endpoints:

- `GET /api/v1/exams/` — published upcoming and in-progress exams for the student's placement.
- `GET /api/v1/exams/{id}/instructions/` — instructions and schedule for an eligible student.
- `POST /api/v1/exams/{id}/start/` — start or resume the student's active attempt.
- `GET /api/v1/exams/{id}/questions/` — sanitized immutable paper questions for an active attempt.
- `GET /api/v1/exams/{id}/my-attempt/` and `/history/` — the student's attempt status/history.
- `GET|PUT /api/v1/exam-attempts/{id}/answers/` — retrieve or save the authenticated student's answers.
- `POST /api/v1/exam-attempts/{id}/submit/` — submit an attempt; repeats are idempotent.
- `POST /api/v1/exam-attempts/{id}/events/` — report supported browser visibility, fullscreen, and reconnect events.

Exam-manager endpoints include `POST /api/v1/exams/` to schedule a paper,
`POST /api/v1/exams/{id}/publish/` and `/cancel/`, and scoped activity reports at
`GET /api/v1/exams/{id}/activity/`. Integrity flags are listed at
`GET /api/v1/integrity-flags/` and reviewed at
`POST /api/v1/integrity-flags/{id}/review/`. Swagger lists the request and response
schemas.

Attempt deadlines use server timestamps. Configure an external scheduler to run
`python manage.py process_exam_deadlines` periodically to auto-submit attempts that
have passed their deadline; no background scheduler is configured by this backend.
Browser events are stored as client-reported and are not proof of misconduct.

## 6. M7 Secure Paper Workflow & M8 Audit

Generated M6 papers retain immutable snapshots. New papers begin in `draft` workflow
state. The creator can submit a paper for review; an institute administrator or
authorized examination staff member other than the creator must approve or reject it.
Rejection requires a reason. Only approved papers can be scheduled for release, and
only released papers can be scheduled as M9 exams.

Paper workflow endpoints:

- `POST /api/v1/generated-papers/{id}/submit-review/`
- `POST /api/v1/generated-papers/{id}/approve/`
- `POST /api/v1/generated-papers/{id}/reject/` — requires `rejection_reason`
- `POST /api/v1/generated-papers/{id}/schedule-release/` — requires `release_at`
- `POST /api/v1/generated-papers/{id}/release/` — idempotent after release time
- `POST /api/v1/generated-papers/{id}/amend/` — creates a new linked draft version;
  released snapshots are not modified
- `POST /api/v1/generated-papers/{id}/archive/`

No scheduler is configured by this backend. An external scheduler must invoke
`python manage.py release_scheduled_papers` periodically to release due papers. Until
that command runs, scheduled papers remain unreleased. Existing attempt-deadline
processing remains separate as `python manage.py process_exam_deadlines`.

M8 records security-sensitive actions in an append-only audit-event model and exposes
read-only, institute-scoped events at `GET /api/v1/audit-events/`. Events intentionally
omit passwords, tokens, answer keys, and paper/question content. This is application-
level append-only behavior, not cryptographic tamper-proofing.

The new M7/M8 migration files are generated but must be reviewed and explicitly
applied in the intended database environment. They are not automatically applied by
the application. Automated tests use a local SQLite database by default; remote test
database use requires explicit `USE_REMOTE_DB_FOR_TESTS=true`.
