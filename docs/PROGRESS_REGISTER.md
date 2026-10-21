# Project Progress Register — ExamCraft AI Backend

**Project Name:** ExamCraft AI Backend  
**Specification:** Modules and System Requirements (M1 – M20)  
**Implementation Phase:** Phase 2 (M11 – M13 backend workflows)  
**Technology Stack:** Python 3.11+, Django 5.2.18 LTS, Django REST Framework 3.18.3, Supabase PostgreSQL, Simple JWT 5.5.1, django-filter 26.2, drf-spectacular 0.30.0, openpyxl 3.1.5, Google Gemini API (`google-genai`), pytest 9.1.1  
**Last Updated:** October 21, 2026  
**Current Milestone:** M11 – M13 implementation; external execution/OCR providers remain configuration dependencies

---

## 1. Executive Summary & Progress Metrics

- **Total Documented Modules:** 20 Modules
- **Phase 1 Modules:** 6 Modules (M1 – M6) + Foundation (Stage A)
- **Phase 2 Implemented or Active Modules:** 7 Modules (M7 – M13)
- **Phase 2 Deferred Modules:** 7 Modules (M14 – M20)

### Overall Progress Metrics (Denominator: 20 Documented Modules)
- **Overall Module Implementation Percentage:** **50.0%** (M1 – M10 implemented in source; M11 – M13 are provider-dependent or partial)
- **Overall Module Verification Percentage:** **40.0%** (8 of 20 modules: M1 – M6, M9, M10)
- **Phase 1 Implementation Percentage:** **100%** (6 of 6 Phase 1 modules implemented)
- **Phase 1 Verification Percentage:** **100%** (6 of 6 Phase 1 modules verified in the recorded test summary)
- **Foundation Status:** **100% Verified** (Stage A: Custom User model, Django config, OpenAPI schema, health endpoints, safe host header validation)

---

## 2. Module-by-Module Progress Register (M1 – M20)

### M1. User & Access Management
- **Status:** **Verified**
- **Implemented Functionality:**
  - Controlled roles: Platform Admin, Institute Admin, Teacher, Student, Exam Staff (with scoped `exam_permissions`).
  - Multi-tenant isolation via `Institute` entity and `UserInstituteMembership` with compound uniqueness constraints.
  - Platform Admin creation of institutes and provisioning of first Institute Administrator.
  - Institute Administrator onboarding of teachers and students.
  - Password management: PBKDF2/Argon2 hashing, `must_change_password` first-login enforcement, password change API, secure single-use time-limited password reset tokens (SHA-256 hashed).
  - Account onboarding/activation: 6-digit numeric verification OTPs with attempt limiting (max 5) and expiration.
  - Bulk CSV and Excel (XLSX) user roster import service: header normalization, format validation, in-file duplicate detection, institute membership duplicate detection, row-level error reporting, preview endpoint, and atomic database confirmation.
- **Verified Functionality:** Verified via 24 automated tests covering authentication, tokens, password enforcement, multi-tenant boundaries, IDOR defenses, and roster imports.
- **Database Tables:** `institutes_institute`, `accounts_user`, `accounts_user_institute_membership`, `accounts_account_invitation`, `accounts_account_verification`, `accounts_password_reset_request`, `accounts_bulk_import_job`, `accounts_bulk_import_row_error`.
- **API Endpoints:** 23 endpoints implemented under `/api/v1/auth/` and `/api/v1/institutes/`.
- **Tests Executed:** 24 tests passed (100% pass rate).

---

### M2. Academic Structure & Syllabus Management
- **Status:** **Verified**
- **Implemented Functionality:**
  - Relational hierarchy: Institute &rarr; Department &rarr; Program &rarr; Academic Year &rarr; Semester &rarr; Batch &rarr; Section &rarr; Subject &rarr; Unit &rarr; Topic &rarr; Learning Outcome (CO).
  - Curriculum course mapping via `ProgramSemesterSubject` with mandatory/elective flags, credits, and syllabus versions.
  - Syllabus mapping linking topics/subjects to academic year sessions and reference material.
  - Teacher subject assignment (`TeacherAssignment`) validating that teachers belong to the same institute as the assigned subject, cohort, and academic year.
  - Student academic placement (`StudentAcademicPlacement`) tracking program, batch, semester, and section.
  - Historical student term progression (`StudentProgressionView` at `/api/v1/student-placements/{id}/progress/`): closes prior placement with `effective_end_date` and transitions status to `completed`, creating a new active term placement record. **Historical placement records are never overwritten or deleted.**
  - Strict tenant isolation and cross-institute reference validation across all 14 models.
- **Verified Functionality:** Verified via 14 automated tests covering hierarchy, unique constraints, cross-institute relationship rejection, teacher role validation, historical student progression, and teacher access scoping.
- **Database Tables:**
  - `academics_department`
  - `academics_program`
  - `academics_academic_year`
  - `academics_semester`
  - `academics_batch`
  - `academics_section`
  - `academics_subject`
  - `academics_program_semester_subject`
  - `academics_unit`
  - `academics_topic`
  - `academics_learning_outcome`
  - `academics_syllabus_mapping`
  - `academics_teacher_assignment`
  - `academics_student_academic_placement`
- **API Endpoints:**
  - `/api/v1/departments/` (CRUD)
  - `/api/v1/programs/` (CRUD)
  - `/api/v1/academic-years/` (CRUD)
  - `/api/v1/semesters/` (CRUD)
  - `/api/v1/batches/` (CRUD)
  - `/api/v1/sections/` (CRUD)
  - `/api/v1/subjects/` (CRUD)
  - `/api/v1/program-semester-subjects/` (CRUD)
  - `/api/v1/units/` (CRUD)
  - `/api/v1/topics/` (CRUD)
  - `/api/v1/learning-outcomes/` (CRUD)
  - `/api/v1/syllabus-mappings/` (CRUD)
  - `/api/v1/teacher-assignments/` (CRUD)
  - `/api/v1/student-placements/` (CRUD)
  - `POST /api/v1/student-placements/{id}/progress/` (Historical term progression)
- **Tests Executed:** 14 dedicated automated tests passed (100% pass rate).
- **Completed Requirements:** FR-02 (Institute and academic management), NFR-02 (Data integrity and consistency).
- **Blockers / Unresolved Issues:** None.

---

### M3. Question Bank Management
- **Status:** **Verified**
- **Implemented Functionality:**
  - Relational question repository supporting MCQ, True/False, Short Answer, Long Answer, and Coding question types.
  - Normalized MCQ/True-False options (`QuestionOption`) with per-option distractor explanations, ordering, and validation rules (MCQ &ge; 2 options, True/False exactly 2 options).
  - Canonical answer key entity (`AnswerKey`) storing expected answers, sample solutions, keywords, and automated test cases (`test_cases`) for coding questions.
  - Objective marking rubrics (`QuestionRubric`) with criterion breakdown and maximum mark allocations for descriptive questions.
  - Provenance source references (`QuestionSourceReference`) linking questions to textbooks, syllabi, section citations, and context excerpts.
  - Immutable revision history snapshotting (`QuestionVersion`): every modification to an existing question automatically preserves a full state snapshot of options, answer keys, rubrics, and marks before updating `current_version`.
  - Question taxonomy tags (`QuestionTag`) scoped to institutes with auto-slug generation.
  - Review decision integration model (`QuestionReview`) for M5 hook (decisions: `approved`, `rejected`, `needs_revision`).
  - Strict tenant isolation and cross-institute reference validation across Subject, Unit, Topic, and Learning Outcome mappings.
  - Workflow safeguards: Questions cannot be created or updated directly to `approved` status; must start in `draft` and follow the review submission endpoint (`/submit-for-review/`).
  - Role-based access control: Students are denied authoring/browsing question banks; teachers can view questions in their institute and edit their authored drafts; institute admins and exam staff have full operational management.
- **Verified Functionality:** Verified via 20 automated tests covering question type creation, options normalization, answer keys, rubrics, coding test cases, immutable version snapshots, provenance tracking, cross-institute rejection, negative marks validation, and role permissions.
- **Database Tables:**
  - `questions_question_tag`
  - `questions_question`
  - `questions_question_option`
  - `questions_answer_key`
  - `questions_question_rubric`
  - `questions_question_source_reference`
  - `questions_question_version`
  - `questions_question_review`
- **API Endpoints:**
  - `/api/v1/questions/` (CRUD, list with filters & pagination)
  - `GET /api/v1/questions/{id}/versions/` (Immutable version history)
  - `GET /api/v1/questions/{id}/source-references/` (Provenance citations)
  - `POST /api/v1/questions/{id}/submit-for-review/` (Review submission workflow)
  - `/api/v1/question-tags/` (CRUD)
  - `/api/v1/question-reviews/` (CRUD)
- **Tests Executed:** 20 dedicated automated tests passed (100% pass rate).
- **Completed Requirements:** FR-03 (Question Bank Management), NFR-02 (Data integrity, versioning, and provenance).
- **Blockers / Unresolved Issues:** None.

---

### M4. AI Question Generation Engine
- **Status:** **Verified**
- **Implemented Functionality:**
  - Multi-tenant academic source document upload and management (`SourceDocument`) supporting PDF, DOCX, and TXT formats with 15MB file size limits and content validation.
  - Multi-format text extraction pipeline (`extract_document_content`):
    - PDF text extraction via `pypdf` with page tracking and OCR-less scan detection.
    - DOCX text extraction via `python-docx` capturing headings, paragraphs, and tables.
    - Plain text (`.txt`) decoding with UTF-8 and Latin-1 fallback.
  - Context passage chunking engine (`SourceDocumentChunk`) preserving document title, original page numbers, and character counts.
  - Dedicated Google Gemini AI provider integration (`GoogleGeminiProvider`):
    - Strict configuration enforcement: missing `GEMINI_API_KEY` fails cleanly with `AIConfigurationError` without generating fake/sample questions.
    - Grounding system prompt forcing the model to generate questions solely using provided source passages as verifiable evidence.
    - Structured JSON array output enforcing schema for all 5 question types (MCQ, True/False, Short Answer, Long Answer with rubrics, Coding with test cases).
    - Rate-limit (`429`), timeout, and network failure mapping to clean, safe exceptions.
  - Candidate validation engine (`validate_ai_candidate`):
    - Validates positive marks, non-negative penalty marks, MCQ &ge; 2 options with correct option, True/False exactly 2 options with 1 correct option, subjective expected answers and rubrics, and coding test cases.
    - Verifies provenance citations (`source_title`, `page_or_section`, `excerpt`). Candidates flagged as unsupported (`supported_by_source: false`) or lacking evidence are rejected and NOT persisted to the question bank.
  - Draft-only integration with M3 Question Bank:
    - Atomically creates `Question` in `status='draft'`, `origin_type='ai_generated'`, `current_version=1`, linking `QuestionOption`, `AnswerKey`, `QuestionRubric`, and `QuestionSourceReference`.
    - Generated questions are **NEVER automatically approved**.
    - Atomic transaction ensures partial persistence failures do not leave orphan question records.
  - Diagnostics tracking (`QuestionGenerationJob`, `GeneratedCandidateRecord`):
    - Detailed candidate audit trail capturing validation errors, raw data, and persisted question IDs.
- **Verified Functionality:** Verified via 15 dedicated automated tests covering missing API key errors, PDF/DOCX/TXT text extraction, student authorization blocks, tenant boundary enforcement, question count limits, grounded generation of all 5 types, malformed response handling, unsupported candidate rejection, mark/option constraint rejection, quota/timeout handling, and transaction rollback.
- **Database Tables:**
  - `ai_source_document`
  - `ai_source_document_chunk`
  - `ai_question_generation_job`
  - `ai_generated_candidate_record`
- **API Endpoints:**
  - `/api/v1/source-materials/` (CRUD, multipart upload)
  - `GET /api/v1/source-materials/{id}/chunks/` (List document chunks)
  - `/api/v1/question-generation-jobs/` (List jobs, request generation)
  - `GET /api/v1/question-generation-jobs/{id}/candidates/` (List candidate diagnostics and results)
- **Tests Executed:** 15 dedicated automated tests passed (100% pass rate).
- **Completed Requirements:** FR-04 (AI Question Generation Engine), NFR-02 (Data integrity, provenance, and grounding), NFR-03 (Security and tenant isolation).
- **Blockers / Unresolved Issues:** None.

---

### M5. Question Verification & Review
- **Status:** **Verified**
- **Implemented Functionality:**
  - Multi-stage, controlled question review lifecycle enforcing status progression: `draft` &rarr; `under_review` &rarr; `approved` / `rejected` / returned to `draft` for revisions, plus `archived`.
  - Anti-self-approval enforcement: Teachers who authored a question cannot approve their own question. A peer reviewer, institute administrator, or examination moderator must perform verification.
  - Review decisions:
    - **Approve**: Only permitted when the question is `under_review`, meets complete academic criteria (options, answer key, rubrics), and is verified by an authorized reviewer who is not the author. Questions are **never automatically approved**.
    - **Reject**: Only permitted on `under_review` items. Requires a mandatory explanatory reason (`rejection_reason`).
    - **Request Revision**: Returns question to `draft` with actionable reviewer feedback (`revision_feedback`), allowing the author to edit and increment version history before resubmitting.
    - **Archive**: Restricted to Institute Administrators and Examination Staff. Cannot archive questions actively under review.
  - Inspection & audit trail (`QuestionReviewRecord`):
    - Dedicated inspection endpoint returns complete question package (options, answer key, rubrics, provenance, version history, review decisions).
    - Immutable audit logs capture every review action, timestamp, reviewer, old status, new status, rejection feedback, and snapshot version.
  - Multi-tenant institute boundary isolation: Reviewers can only inspect and act upon questions belonging to their active institute membership. Platform administrators have read-only audit inspection and cannot make institutional review decisions.
  - Direct status edit block: Teachers cannot bypass the review process by setting questions directly to `approved`.
- **Verified Functionality:** Verified via 16 dedicated automated tests covering submission by authors, blocking submission of peer drafts, blocking duplicate review submissions, strict anti-self-approval enforcement, peer review approval, admin approval, mandatory rejection reasons, revision return and author edit/resubmit cycles, tenant isolation, student access blocks, platform admin restriction, inspection payload completeness, review audit logs filtering, and archiving rules.
- **Database Tables:**
  - `reviews_question_review_record`
- **API Endpoints:**
  - `GET /api/v1/review-workflows/pending/` (List questions awaiting review in institute)
  - `GET /api/v1/review-workflows/{id}/inspection/` (Complete review inspection package)
  - `POST /api/v1/review-workflows/{id}/submit/` (Submit question for review)
  - `POST /api/v1/review-workflows/{id}/approve/` (Approve question under review)
  - `POST /api/v1/review-workflows/{id}/reject/` (Reject question under review with reason)
  - `POST /api/v1/review-workflows/{id}/request-revision/` (Request revisions on question)
  - `POST /api/v1/review-workflows/{id}/archive/` (Archive question)
  - `GET /api/v1/review-audit-logs/` (List and filter review audit history records)
  - `GET /api/v1/review-audit-logs/{id}/` (Retrieve review audit record details)
- **Tests Executed:** 16 dedicated automated tests passed (100% pass rate).
- **Completed Requirements:** FR-05 (Question Verification and Review), NFR-02 (Data integrity, versioning, and provenance), NFR-03 (Role-based security and tenant isolation).
- **Blockers / Unresolved Issues:** None.

---

### M6. Blueprint Paper Generation
- **Status:** **Verified**
- **Implemented Functionality:**
  - Relational blueprint management models (`PaperBlueprint`, `BlueprintSection`, `BlueprintRule`).
  - Section mark reconciliation and structural validation: verifies rules sum to section target marks, and section target marks sum to paper total marks.
  - Multi-tenant institute boundary isolation and teacher assignment enforcement: teachers can only create blueprints for subjects they are assigned to teach.
  - Approved question selection algorithm:
    - Filters strictly on `status='approved'` from M3 Question Bank (draft, under_review, rejected, and archived questions are strictly excluded).
    - Matches subject, question type, marks per question, and optional unit, topic, learning outcome, difficulty, and Bloom's cognitive level.
    - Prevents question reuse within the same paper unless explicitly permitted.
    - Employs a fair randomized selection strategy among eligible candidates to avoid deterministic repetition.
  - Transparent shortage reporting: if approved questions are insufficient, generation halts and returns a detailed shortage report pinpointing the deficit rule, required count, and available count without creating incomplete or invalid papers.
  - Immutable generated paper persistence (`GeneratedPaper`, `GeneratedPaperQuestion`):
    - Atomically snapshots question text, normalized options, rubrics, and source references to preserve exam integrity even if source questions are subsequently updated or deleted.
    - Incremental paper regeneration (`generation_version=1, 2...`) preserving previous paper iterations rather than silently overwriting them.
    - Rollback protection: database failures during generation guarantee zero partial records.
  - Role-based authorization: Students are completely forbidden from blueprint and paper generation endpoints; platform administrators have read-only audit inspection.
- **Verified Functionality:** Verified via 11 dedicated automated tests covering assigned teacher creation, unassigned teacher blocks, cross-institute isolation, student access blocks, section and paper mark reconciliation failure, rule shortage reporting, successful paper generation with ordered snapshots, sequential regeneration versioning, exclusion of non-approved questions, and atomic rollback on persistence failure.
- **Database Tables:**
  - `blueprints_paper_blueprint`
  - `blueprints_blueprint_section`
  - `blueprints_blueprint_rule`
  - `blueprints_generated_paper`
  - `blueprints_generated_paper_question`
- **API Endpoints:**
  - `/api/v1/paper-blueprints/` (CRUD, list with filters)
  - `GET /api/v1/paper-blueprints/{id}/validate-structure/` (Structural and marks reconciliation)
  - `GET /api/v1/paper-blueprints/{id}/check-availability/` (Question bank availability & shortage report)
  - `POST /api/v1/paper-blueprints/{id}/generate-paper/` (Execute paper generation)
  - `/api/v1/blueprint-sections/` (CRUD)
  - `/api/v1/blueprint-rules/` (CRUD)
  - `/api/v1/generated-papers/` (List and detail generated papers with snapshots)
- **Tests Executed:** 11 dedicated automated tests passed (100% pass rate).
- **Completed Requirements:** FR-06 (Blueprint Paper Generation), NFR-02 (Data integrity, versioning, and provenance), NFR-03 (Role-based security and tenant isolation).
- **Blockers / Unresolved Issues:** None.

---

### M7 – M20 (Phase 2 Modules)
- **M7. Secure Paper Workflow:** Implemented in source.
- **M8. Audit & Traceability:** Implemented in source.
- **M9. Online Exam Delivery:** Implemented; focused tests run with this update.
- **M10. Anti-Collusion & Integrity Monitoring:** Implemented; focused tests run with this update.
- **M11. Coding Exam Module:** Implemented with an isolated-provider interface; awaiting provider configuration.
- **M12. Automated Evaluation:** Objective grading implemented and verified; coding grading depends on the configured execution provider.
- **M13. Handwritten Answer Sheet Evaluation:** Private upload and human rubric review implemented; OCR awaits provider configuration.
- **M14. Revaluation & Grievance:** Implemented and focused-tested; mark changes require authorized, audited revaluation decisions.
- **M15. Analytics & Item Analysis:** Implemented and focused-tested; aggregates only finalized results and reports incomplete attempts separately.
- **M16. Outcome Attainment Reporting (CO/PO):** Outcome models, mappings, and final-mark evidence implemented and tested; numerical attainment awaits a documented formula and thresholds.
- **M17. Exam Administration:** Existing schedule, publish/cancel, eligibility, and lifecycle behaviors verified; central audit events added for schedule changes and transitions.
- **M18. Notification Service:** Private in-app notifications, read state, event idempotency, cohort validation, and SMTP delivery status implemented; SMTP configuration is environment-dependent.
- **M19. Student Learning Support:** Student-scoped recommendations to existing subject materials based on final marks and CO mappings implemented; no AI-generated predictions or outcome-level material mapping.
- **M20. Early-Warning Analytics:** Institute-manager evidence endpoint implemented; risk formula, weights, minimum-data rule, and thresholds remain undefined by the available specification, so no risk classification is emitted.

---

## 3. Prior Test Execution Summary (M1 – M6)

| Test Suite | Files | Tests Executed | Tests Passed | Tests Failed | Execution Time |
|:---|:---|:---:|:---:|:---:|:---:|
| **Common & Health Checks** | `apps/common/tests/test_health.py` | 3 | 3 | 0 | 0.05s |
| **Settings Security (No Wildcards)** | `apps/common/tests/test_security_settings.py` | 3 | 3 | 0 | 0.01s |
| **Accounts / Custom User** | `apps/accounts/tests/test_user_model.py` | 4 | 4 | 0 | 0.04s |
| **M1 Auth & Management** | `apps/accounts/tests/test_m1_auth_and_management.py` | 20 | 20 | 0 | 1.19s |
| **M2 Academic Structure** | `apps/academics/tests/test_m2_academic_structure.py` | 14 | 14 | 0 | 0.37s |
| **M3 Question Bank** | `apps/questions/tests/test_m3_question_bank.py` | 20 | 20 | 0 | 1.20s |
| **M4 AI Question Generation** | `apps/ai_generation/tests/test_m4_ai_generation.py` | 15 | 15 | 0 | 1.48s |
| **M5 Question Verification & Review** | `apps/reviews/tests/test_m5_question_review.py` | 16 | 16 | 0 | 2.07s |
| **M6 Blueprint Paper Generation** | `apps/blueprints/tests/test_m6_paper_blueprints.py` | 11 | 11 | 0 | 2.17s |
| **Total** | **9 Test Files** | **106 Tests** | **106 Passed** | **0 Failed** | **5.93s** |

**October 21, 2026 focused verification:** 25 tests passed across the M6 paper-generation and M9/M10 exam workflow files, covering the added M11 – M13 integrations. This was not a full-suite run.
