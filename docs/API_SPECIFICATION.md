# REST API Specification — ExamCraft AI Backend

**Base URL Prefix:** `/api/v1/`  
**Authentication Scheme:** Bearer JWT (`Authorization: Bearer <access_token>`)

---

## 1. Common Endpoints

- `GET /api/v1/health/` — Service operational health check.
- `GET /api/v1/health/database/` — Database connectivity status without credential leaks.
- `GET /api/v1/schema/` — OpenAPI 3.0 specification.
- `GET /api/v1/docs/` — Interactive Swagger UI.
- `GET /api/v1/redoc/` — ReDoc documentation.

---

## 2. Module M1 — Authentication & Account Lifecycle Endpoints

- `POST /api/v1/auth/login/` — Login returning access/refresh tokens and profile.
- `POST /api/v1/auth/token/refresh/` — Refresh access token.
- `POST /api/v1/auth/logout/` — Logout and blacklist refresh token.
- `GET /api/v1/auth/me/` — Get authenticated user details.
- `POST /api/v1/auth/password/change/` — Change password; clears `must_change_password`.
- `POST /api/v1/auth/password-reset/request/` — Request password reset.
- `POST /api/v1/auth/password-reset/confirm/` — Confirm password reset.
- `POST /api/v1/auth/activation/verify/` — Validate 6-digit OTP code.
- `POST /api/v1/auth/activation/complete/` — Complete account activation.
- `GET /api/v1/institutes/` & `POST /api/v1/institutes/` — Institute management.
- `GET/PATCH /api/v1/institutes/{id}/` — Institute detail.
- `POST /api/v1/institutes/{id}/provision-admin/` — Provision first Institute Admin.
- `GET/POST /api/v1/institutes/{id}/members/` — Member roster list and addition.
- `GET/PATCH /api/v1/institutes/{id}/members/{m_id}/` — Member detail.
- `POST /api/v1/institutes/{id}/members/{m_id}/deactivate/` — Deactivate member.
- `POST /api/v1/institutes/{id}/imports/` — Bulk roster upload (CSV / XLSX).
- `GET /api/v1/institutes/{id}/imports/{j_id}/preview/` — Preview valid candidates & errors.
- `POST /api/v1/institutes/{id}/imports/{j_id}/confirm/` — Commit valid candidates atomically.

---

## 3. Module M2 — Academic Structure & Syllabus Management Endpoints

All endpoints require standard Bearer JWT authentication. Write actions are strictly restricted to authorized Institute Administrators and Platform Administrators.

### 3.1 Departments
- `GET /api/v1/departments/` — List institute departments (filterable by `institute`, `status`).
- `POST /api/v1/departments/` — Create department.
- `GET /api/v1/departments/{id}/` — Retrieve department.
- `PATCH /api/v1/departments/{id}/` — Update department.
- `DELETE /api/v1/departments/{id}/` — Delete department.

### 3.2 Programs
- `GET /api/v1/programs/` — List academic programs (filterable by `institute`, `department`, `qualification_type`).
- `POST /api/v1/programs/` — Create program with duration and semester count.
- `GET /api/v1/programs/{id}/` — Retrieve program.
- `PATCH /api/v1/programs/{id}/` — Update program.
- `DELETE /api/v1/programs/{id}/` — Delete program.

### 3.3 Academic Years
- `GET /api/v1/academic-years/` — List academic year sessions (filterable by `institute`, `is_current`).
- `POST /api/v1/academic-years/` — Create academic year session with start and end dates.
- `GET/PATCH/DELETE /api/v1/academic-years/{id}/` — Manage session.

### 3.4 Semesters
- `GET /api/v1/semesters/` — List semesters (filterable by `program`).
- `POST /api/v1/semesters/` — Create semester under a program.
- `GET/PATCH/DELETE /api/v1/semesters/{id}/` — Manage semester.

### 3.5 Batches & Cohorts
- `GET /api/v1/batches/` — List student cohorts (filterable by `institute`, `program`, `admission_year`).
- `POST /api/v1/batches/` — Create batch.
- `GET/PATCH/DELETE /api/v1/batches/{id}/` — Manage batch.

### 3.6 Sections
- `GET /api/v1/sections/` — List sections within batches.
- `POST /api/v1/sections/` — Create section.
- `GET/PATCH/DELETE /api/v1/sections/{id}/` — Manage section.

### 3.7 Subjects
- `GET /api/v1/subjects/` — List subjects (filterable by `institute`, `department`, `status`).
- `POST /api/v1/subjects/` — Create subject with code, title, and credit weight.
- `GET/PATCH/DELETE /api/v1/subjects/{id}/` — Manage subject.

### 3.8 Program Semester Subjects
- `GET /api/v1/program-semester-subjects/` — List curriculum course mappings.
- `POST /api/v1/program-semester-subjects/` — Associate subject with program and semester.
- `GET/PATCH/DELETE /api/v1/program-semester-subjects/{id}/` — Manage curriculum mapping.

### 3.9 Curriculum Units & Topics
- `GET /api/v1/units/` & `POST /api/v1/units/` — Manage curriculum units within subjects.
- `GET/PATCH/DELETE /api/v1/units/{id}/` — Unit details.
- `GET /api/v1/topics/` & `POST /api/v1/topics/` — Manage topics within units.
- `GET/PATCH/DELETE /api/v1/topics/{id}/` — Topic details.

### 3.10 Learning Outcomes (COs)
- `GET /api/v1/learning-outcomes/` — List Course Outcomes (CO1, CO2, etc.).
- `POST /api/v1/learning-outcomes/` — Create course outcome with category (`cognitive`, `affective`, `psychomotor`).
- `GET/PATCH/DELETE /api/v1/learning-outcomes/{id}/` — Manage learning outcome.

### 3.11 Syllabus Mappings
- `GET /api/v1/syllabus-mappings/` — List textbook / chapter reference mappings.
- `POST /api/v1/syllabus-mappings/` — Map subject/topic to syllabus references for an academic year.
- `GET/PATCH/DELETE /api/v1/syllabus-mappings/{id}/` — Manage syllabus mapping.

### 3.12 Teacher Assignments
- `GET /api/v1/teacher-assignments/` — List teacher-subject assignments (Teachers see own assignments; Admins see institute).
- `POST /api/v1/teacher-assignments/` — Assign teacher to subject, academic year, and cohort/section.
- `GET/PATCH/DELETE /api/v1/teacher-assignments/{id}/` — Manage teacher assignment.

### 3.13 Student Academic Placements & Progression
- `GET /api/v1/student-placements/` — List student placements (Students see own; Admins see institute).
- `POST /api/v1/student-placements/` — Create student placement for program, batch, semester, and section.
- `GET/PATCH/DELETE /api/v1/student-placements/{id}/` — Placement detail.
- `POST /api/v1/student-placements/{id}/progress/` — **Student Term Progression**:
  - Request Body:
    ```json
    {
      "next_semester": "uuid-of-next-semester",
      "next_section": "uuid-of-next-section-optional",
      "effective_start_date": "2026-08-01"
    }
    ```
  - Behavior: Marks the prior placement record as `completed` with `effective_end_date` populated. Atomically creates a new active placement record for the new term. **Full historical progression is preserved.**

---

## 4. Module M3 — Question Bank Management Endpoints

All endpoints require standard Bearer JWT authentication and adhere to tenant isolation rules.
Students are strictly forbidden from viewing or authoring questions.

### 4.1 Questions
- `GET /api/v1/questions/` — List questions.
  - **Query Parameters / Filters:** `institute`, `subject`, `unit`, `topic`, `learning_outcome`, `question_type`, `difficulty`, `status`, `bloom_taxonomy`, `origin_type`, `search` (searches `question_text`), `ordering`.
  - **Permissions:** Platform Admin sees all; Institute Admin & Exam Staff see own institute; Teachers see questions within their institute/subjects.
- `POST /api/v1/questions/` — Create question.
  - Supports question types: `mcq`, `true_false`, `short_answer`, `long_answer`, `coding`.
  - Automatically assigns author (`created_by`), sets `status='draft'`, and initializes `current_version=1`.
  - Rejects attempts to directly create with `status='approved'`.
- `GET /api/v1/questions/{id}/` — Retrieve question detail including options, answer keys, rubrics, and source citations.
- `PUT /api/v1/questions/{id}/` & `PATCH /api/v1/questions/{id}/` — Update question.
  - Atomically takes an **immutable historical snapshot** into `QuestionVersion` before updating.
  - Increments `current_version`.
  - Teachers may only update their own draft or under-review questions.
- `DELETE /api/v1/questions/{id}/` — Delete question (allowed for authors on draft items or institute administrators).
- `GET /api/v1/questions/{id}/versions/` — Retrieve complete historical snapshot audit trail for a question.
- `GET /api/v1/questions/{id}/source-references/` — Retrieve source provenance citations.
- `POST /api/v1/questions/{id}/submit-for-review/` — Transition draft question to `under_review`.

### 4.2 Question Tags
- `GET /api/v1/question-tags/` — List institute question tags (filterable by `institute`, `search`).
- `POST /api/v1/question-tags/` — Create new categorization tag with slug generation.
- `GET/PATCH/DELETE /api/v1/question-tags/{id}/` — Manage question tag.

### 4.3 Question Reviews (Integration Hook for M5)
- `GET /api/v1/question-reviews/` — List question review records (filterable by `question`, `decision`).
- `POST /api/v1/question-reviews/` — Submit reviewer decision (`approved`, `rejected`, `needs_revision`) and critique.
- `GET/PATCH/DELETE /api/v1/question-reviews/{id}/` — Manage question review record.

---

## 5. Module M4 — AI Question Generation Engine Endpoints

All endpoints require standard Bearer JWT authentication and institute-level authorization.
Students are strictly forbidden from uploading source documents or requesting question generation.

### 5.1 Academic Source Materials
- `GET /api/v1/source-materials/` — List uploaded source materials.
  - **Filters:** `institute`, `subject`, `processing_status`, `file_type`, `search` (searches title and subject code/name).
  - **Permissions:** Teachers (within own institute), Institute Administrators, Exam Staff.
- `POST /api/v1/source-materials/` — Upload academic source document (`multipart/form-data`).
  - **Form Fields:** `institute`, `subject`, `unit` (optional), `topic` (optional), `title`, `file`.
  - **Supported Formats:** PDF (`.pdf`), Word (`.docx`), Plain Text (`.txt`). Max size: 15MB.
  - **Behavior:** Automatically extracts readable text, parses page numbers, and creates passage chunks.
- `GET /api/v1/source-materials/{id}/` — Retrieve document processing status, page count, and chunk metrics.
- `DELETE /api/v1/source-materials/{id}/` — Remove document and all associated chunks.
- `GET /api/v1/source-materials/{id}/chunks/` — List paginated extracted text passages with original page numbers and character counts.

### 5.2 Question Generation Jobs
- `GET /api/v1/question-generation-jobs/` — List generation jobs within the authenticated user's institute.
  - **Filters:** `institute`, `subject`, `status`.
- `POST /api/v1/question-generation-jobs/` — Request AI question generation grounded in source materials.
  - **Request Body:**
    ```json
    {
      "institute": "uuid-institute-id",
      "subject": "uuid-subject-id",
      "unit": "uuid-unit-id-optional",
      "topic": "uuid-topic-id-optional",
      "learning_outcome": "uuid-outcome-id-optional",
      "source_document_ids": ["uuid-doc-id-1"],
      "question_types": ["mcq", "true_false", "short_answer", "long_answer", "coding"],
      "num_questions": 5,
      "difficulty_distribution": {"easy": 2, "medium": 2, "hard": 1},
      "bloom_taxonomy_distribution": {"understand": 2, "apply": 2, "analyze": 1},
      "default_marks": "2.00",
      "default_negative_marks": "0.50",
      "language": "English"
    }
    ```
  - **Grounding & Validation Rules:**
    - Model is strictly commanded to generate questions using facts solely present in the provided source chunks.
    - Output is strictly validated against M3 schema, mark constraints, option counts, answer keys, rubrics, coding test cases, and provenance.
    - Valid candidates are saved directly into the **M3 Question Bank** in `draft` status, version 1, with `origin_type='ai_generated'` and linked `QuestionSourceReference`.
    - Generated questions are **NEVER automatically approved**.
    - If provider key is missing, returns safe error and fails job without sample substitutions.
- `GET /api/v1/question-generation-jobs/{id}/` — Retrieve generation job status, summary counters, and safe diagnostics.
- `GET /api/v1/question-generation-jobs/{id}/candidates/` — Retrieve complete candidate audit trail.
  - Returns every candidate generated by the model with its outcome: `saved` (with `persisted_question_id`), `validation_failed`, or `unsupported_content` (along with error reasons and provenance citations).

---

## 6. Module M5 — Question Verification & Review Endpoints

All review endpoints require Bearer JWT authentication and adhere to tenant isolation rules.
Students are strictly forbidden from viewing or participating in the review workflow.

### 6.1 Question Review Workflow (`/api/v1/review-workflows/`)
- `GET /api/v1/review-workflows/pending/` — List questions pending review within the authenticated user's institute (`status='under_review'`).
  - **Query Filters:** `subject`
  - **Permissions:** Teachers (assigned to institute), Institute Administrators, Exam Staff.
- `GET /api/v1/review-workflows/{id}/inspection/` — Retrieve comprehensive verification inspection package for a question.
  - Returns question text, options, answer key, test cases, rubrics, provenance references, version history, and full audit logs.
- `POST /api/v1/review-workflows/{id}/submit/` — Submit a question for verification.
  - **Allowed From:** `draft`, `rejected`
  - **Resulting Status:** `under_review`
  - Teachers may only submit questions they authored.
- `POST /api/v1/review-workflows/{id}/approve/` — Approve a question under review.
  - **Allowed From:** `under_review` only.
  - **Anti-Self-Approval:** The question's author cannot approve their own question. A peer teacher, institute administrator, or exam staff member must approve.
  - **Resulting Status:** `approved`
  - **Request Body (optional):**
    ```json
    {
      "notes": "Verified accuracy and academic alignment.",
      "rubric_scores": {"scientific_accuracy": 5, "clarity": 5}
    }
    ```
- `POST /api/v1/review-workflows/{id}/reject/` — Reject a question under review.
  - **Allowed From:** `under_review` only.
  - **Resulting Status:** `rejected`
  - **Request Body:**
    ```json
    {
      "rejection_reason": "Explanation of academic flaw or ambiguity",
      "notes": "Additional reviewer observations"
    }
    ```
- `POST /api/v1/review-workflows/{id}/request-revision/` — Request revisions from the author.
  - **Allowed From:** `under_review` only.
  - **Resulting Status:** `draft` (returned to draft status so the author can edit and resubmit).
  - **Request Body:**
    ```json
    {
      "revision_feedback": "Please add explanation for Option B and adjust marks to 2.00",
      "notes": "Actionable feedback"
    }
    ```
- `POST /api/v1/review-workflows/{id}/archive/` — Archive an approved or rejected question.
  - **Permissions:** Institute Administrators and Exam Staff only.
  - **Resulting Status:** `archived`

### 6.2 Review Audit Logs (`/api/v1/review-audit-logs/`)
- `GET /api/v1/review-audit-logs/` — List immutable review decision records across user's institute.
  - **Query Filters:** `question`, `reviewer`, `decision` (`approve`, `reject`, `request_revision`), `from_status`, `to_status`.
  - **Ordering:** `created_at`, `question_version`.
- `GET /api/v1/review-audit-logs/{id}/` — Retrieve audit record detail.

---

## 7. Module M6 — Blueprint Paper Generation Endpoints

All blueprint and paper generation endpoints require Bearer JWT authentication and institute-level authorization.
Students are strictly forbidden from viewing or generating blueprints and examination papers.

### 7.1 Paper Blueprints (`/api/v1/paper-blueprints/`)
- `GET /api/v1/paper-blueprints/` — List examination blueprints.
  - **Query Filters:** `institute`, `subject`, `status` (`draft`, `active`, `archived`), `academic_year`, `semester`, `program`, `department`.
  - **Permissions:** Teachers (assigned to subject), Institute Administrators, Exam Staff. Platform Admins have read-only access.
- `POST /api/v1/paper-blueprints/` — Create new blueprint.
  - Automatically captures author (`created_by`), sets `status='draft'`, and validates institute tenant boundaries.
  - Teachers may only create blueprints for subjects they are actively assigned to teach.
- `GET /api/v1/paper-blueprints/{id}/` — Retrieve blueprint details, including nested sections and selection rules.
- `PUT /api/v1/paper-blueprints/{id}/` & `PATCH /api/v1/paper-blueprints/{id}/` — Update blueprint metadata.
- `DELETE /api/v1/paper-blueprints/{id}/` — Delete blueprint (allowed for authors or institute administrators).
- `GET /api/v1/paper-blueprints/{id}/validate-structure/` — Validates structural integrity.
  - Verifies sum of rules matches each section target marks, and sum of section target marks equals blueprint total marks.
  - Fails cleanly with status `400` and detailed error differences if unbalanced.
- `GET /api/v1/paper-blueprints/{id}/check-availability/` — Availability and shortage audit against approved M3 questions.
  - Returns `can_generate` (`true`/`false`) and breakdown per rule showing `required_count`, `available_count`, and `shortage`.
- `POST /api/v1/paper-blueprints/{id}/generate-paper/` — Execute paper generation.
  - **Request Body (optional):**
    ```json
    {
      "title": "Custom Examination Set A"
    }
    ```
  - **Behavior:**
    1. Validates blueprint structure and reconciliation.
    2. Queries eligible questions from M3 (`status='approved'` only).
    3. Fails cleanly with HTTP 400 and full shortage report if questions are insufficient.
    4. Fair randomized question selection preventing duplicates.
    5. Atomically creates `GeneratedPaper` and sequential `GeneratedPaperQuestion` snapshots.
    6. Increments sequential `generation_version` (preserving historical sets).

### 7.2 Blueprint Sections (`/api/v1/blueprint-sections/`)
- `GET /api/v1/blueprint-sections/` — List sections (filterable by `blueprint`).
- `POST /api/v1/blueprint-sections/` — Create named section with `target_marks` and `instructions`.
- `GET/PATCH/DELETE /api/v1/blueprint-sections/{id}/` — Manage section.

### 7.3 Blueprint Rules (`/api/v1/blueprint-rules/`)
- `GET /api/v1/blueprint-rules/` — List rules (filterable by `section`, `question_type`, `difficulty`, `bloom_taxonomy`, `unit`, `topic`).
- `POST /api/v1/blueprint-rules/` — Add normalized selection rule with `question_type`, `question_count`, `marks_per_question`, and optional filters.
- `GET/PATCH/DELETE /api/v1/blueprint-rules/{id}/` — Manage rule.

### 7.4 Generated Papers (`/api/v1/generated-papers/`)
- `GET /api/v1/generated-papers/` — List generated examination papers within the user's institute.
  - **Filters:** `institute`, `blueprint`, `subject`, `status`.
- `GET /api/v1/generated-papers/{id}/` — Retrieve complete generated paper including blueprint snapshot, validation report, and ordered question snapshots (`paper_questions`).

## 8. Module M11 — Coding Examination Management

All coding-question content is taken from the immutable released-paper snapshot. Students receive only the coding configuration and public question statement; test cases, expected outputs, and grading results are not returned.

- `GET /api/v1/exams/{id}/questions/` — Delivers coding configuration (`language`, enabled languages, starter template, and bounded execution constraints) without test cases.
- `POST /api/v1/exam-attempts/{id}/coding-submissions/` — Submit `{ "question": "<paper-question-uuid>", "code": "...", "language": "..." }` during the owned active attempt. Repeating identical code/language returns the same submission.
- `GET /api/v1/coding-submissions/{id}/` — Retrieve only the authenticated student's submission status.
- `POST /api/v1/coding-submissions/{id}/execute/` — The student may request isolated external execution during the active attempt; an authorized exam manager may retry a queued/failed submission after submission. A missing provider returns `503`; a provider failure returns `502`.

The attempt deadline remains the earlier of the paper duration and exam end time. Per-question runtime limits come from the released question snapshot, default to 3 seconds / 128 MB, and are bounded to 1–15 seconds / 32–512 MB. The runner receives each public and hidden test input/expected output over HTTPS and must return exactly one boolean pass value per case. Django never runs submitted code or returns test inputs, expected outputs, stdout, or stderr.

Required environment variables: `CODE_EXECUTION_PROVIDER_URL` (HTTPS), `CODE_EXECUTION_PROVIDER_TOKEN`, and optional `CODE_EXECUTION_PROVIDER_TIMEOUT_SECONDS` (default 20). Provider request JSON is `{ "code", "language", "test_cases": [{"input", "expected_output"}], "limits": {"time_limit_seconds", "memory_limit_mb"} }`; response JSON is `{ "passed": [true, false, ...] }`.

## 9. Module M12 — Automated Evaluation

- Submission of an exam attempt grades every MCQ / true-false question from its released option snapshot. Correct answers receive question marks, incorrect answers receive configured negative marks, and unanswered questions receive zero. Grading is idempotent.
- If an older released snapshot lacks correctness data for its options, answered objective questions are held for human review instead of being guessed or penalized.
- Completed coding submissions receive proportional marks (`question marks × passed cases / all cases`) from the isolated runner. Detailed per-case results remain private.
- `GET /api/v1/exam-attempts/{id}/result/` — Returns marks and per-question status only after submission. Students can access only their own attempts; exam managers can access attempts in their authorized institute. Pending coding/human evaluation is marked non-final. Students cannot write or approve evaluations.

## 10. Module M13 — Handwritten Answer-Sheet Evaluation

- `POST /api/v1/handwritten-answer-sheets/` — A student uploads one PDF, PNG, or JPEG (maximum 20 MB) for their submitted attempt using multipart fields `attempt` and `file`.
- `GET /api/v1/handwritten-answer-sheets/` and `GET /api/v1/handwritten-answer-sheets/{id}/` — Students see their own sheet; exam managers see only sheets in their authorized institute. Extracted text and marks are withheld from students until human review.
- `GET /api/v1/handwritten-answer-sheets/{id}/download/` — Authenticated owner or institute exam manager downloads the scan; files are not exposed through a public URL.
- `POST /api/v1/handwritten-answer-sheets/{id}/extract/` — Exam-manager OCR request. Provider absence/failure is explicit; no OCR text is fabricated.
- `POST /api/v1/handwritten-answer-sheets/{id}/review/` — Exam-manager rubric review; each subjective paper question is scored once, rubric criteria must match the released snapshot, and awarded marks must equal rubric scores and remain within the question maximum.

Optional OCR environment variables: `OCR_PROVIDER_URL` (HTTPS), `OCR_PROVIDER_TOKEN`, and `OCR_PROVIDER_TIMEOUT_SECONDS` (default 30). `PRIVATE_MEDIA_ROOT` sets the private file-storage directory (default: `<project>/private_media`, outside `MEDIA_ROOT`). The provider accepts JSON `{ "filename", "content_type", "file_base64" }` and must return `{ "text": "..." }`. Without configuration, uploaded sheets remain available for authorized manual review and extraction returns `503`.

## 11. Modules M14–M16 — Revaluation, Analytics, and Outcomes

### 11.1 Revaluation
- Exam managers configure `revaluation_opens_at` and `revaluation_closes_at` on an exam schedule; both are required together.
- `POST /api/v1/grievances/` — The student files `{ "attempt", "reason" }` after a final result within the configured window. `GET /api/v1/grievances/` and `GET /api/v1/grievances/{id}/` are owner- or institute-manager-scoped; `POST /api/v1/grievances/{id}/decide/` records the authorized decision without directly changing marks.
- `POST /api/v1/revaluation-requests/` — The student submits `{ "attempt", "question", "reason" }` within the configured window after a final result. A single request is allowed per attempt/question.
- `GET /api/v1/revaluation-requests/` and `GET /api/v1/revaluation-requests/{id}/` — Students see their own requests; exam managers see requests for their institutes.
- `POST /api/v1/revaluation-requests/{id}/decide/` — Authorized exam manager submits `decision`, `comment`, and optional `corrected_marks` for approval. Decisions are recorded in history and audit; approved corrections are reflected in exam results.

### 11.2 Analytics
- `GET /api/v1/exam-analytics/?exam={uuid}` — Exam-level analytics.
- The same endpoint accepts `institute`, `subject`, or `batch` filters for the corresponding scoped reports. At least one scope is required; only exam managers may query authorized institutes.
- In-progress attempts and submitted results still awaiting grading are counted separately. Marks averages and item analysis include only final results.
- The existing schema has no separate result-publication state; this endpoint is manager-only and does not expose student-level result data.

### 11.3 CO/PO mappings and evidence
- `GET/POST /api/v1/program-outcomes/` — Manage program outcomes.
- `GET/POST /api/v1/outcome-alignments/` — Align an existing course outcome with a program outcome; the subject must be in the program curriculum.
- `GET/POST /api/v1/assessment-outcome-mappings/` — Map a released paper question to a course outcome from the same subject.
- `GET /api/v1/outcome-attainment/?program={uuid}` — Return course/program outcome mappings and mark evidence from final results. Optional `subject`, `semester`, and `batch` filters narrow the scope.
- The source specification defines no CO/PO attainment formula, weight/threshold, or aggregation rule. The endpoint therefore reports traceable earned/available mark totals and does not emit a fabricated attainment value.

## 12. Modules M17–M20 — Administration, Notifications, Learning Support, and Risk

### 12.1 Exam lifecycle (M17)
- `POST /api/v1/exams/{id}/publish/` and `POST /api/v1/exams/{id}/cancel/` are manager-only transitions. Published exams cannot be republished after attempts exist; an exam with an in-progress attempt cannot be cancelled.
- Schedule CRUD, publish, and cancel are institute-scoped and recorded in exam activity plus the central audit log. Scheduling validates released papers, institute, batch/program, and section scope.

### 12.2 Notifications (M18)
- `GET /api/v1/notifications/` and `GET /api/v1/notifications/{id}/` return only the authenticated recipient's notifications.
- `POST /api/v1/notifications/` is manager-only and accepts `{ "institute", "recipient", "exam"?, "subject", "message", "event_key"? }`. Recipients must be active institute members and, when an exam is supplied, eligible for its cohort. A repeated `event_key` for the same recipient is idempotent.
- `POST /api/v1/notifications/{id}/read/` and `/unread/` update the recipient's read status.
- Email status is `sent` only after the configured Django email backend accepts the message, `failed` on SMTP failure, or `not_configured` when SMTP host/from address is missing. Configure `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` or `EMAIL_USE_SSL`, and `DEFAULT_FROM_EMAIL`.

### 12.3 Learning support (M19)
- `GET /api/v1/learning-support/recommendations/` is student-only and may be narrowed by `institute` and `subject`.
- Recommendations use the student's final persisted exam marks, existing question-to-CO mappings, and completed source-document titles for that subject. No AI-generated learning history or result is fabricated. Documents are linked at subject level because source documents are not mapped directly to outcomes.

### 12.4 Risk indicators (M20)
- `GET /api/v1/risk-indicators/?institute={uuid}` is available only to an authorized exam manager; optional `batch` and `subject` filters narrow the institute scope.
- The response reports persisted completed/in-progress/pending-grading counts and finalized mark totals. Risk classification is not produced: the finalized project specification does not define a risk formula, feature weights, minimum-data rule, or thresholds.
