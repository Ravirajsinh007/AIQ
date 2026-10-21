# Database Schema Specification — ExamCraft AI

## 1. Design Principles

- **Primary Keys:** UUID version 4 (`UUIDField`) for all core business entities to prevent enumeration attacks and ensure multi-tenant security across institutes.
- **Audit Columns:** `created_at` (timestamp with timezone) and `updated_at` (auto-now timestamp with timezone).
- **Relational Integrity:** Explicit foreign keys with strict `on_delete` policies (`CASCADE` for child relation cleanups, `PROTECT` or `SET_NULL` for actors).
- **Tenant Isolation:** Every tenant-owned table references an `Institute` foreign key with indexed compound uniqueness constraints.
- **Normalization:** MCQ options, answer keys, rubrics, and source passages are stored in dedicated normalized relational tables, avoiding monolithic JSON blobs.

---

## 2. Implemented Schema: Module M1 (User & Access Management)

### 2.1 Table: `institutes_institute`
Tenant boundary for academic and user records.
- `id` (UUID, PK)
- `code` (VARCHAR(50), UNIQUE, Indexed)
- `name` (VARCHAR(255))
- `status` (VARCHAR(20), `active`/`inactive`/`suspended`)
- `contact_email`, `contact_phone`, `address`
- `created_at`, `updated_at`

### 2.2 Table: `accounts_user`
Custom authentication user entity.
- `id` (UUID, PK)
- `email` (VARCHAR(255), UNIQUE, Indexed)
- `password` (VARCHAR(128))
- `first_name`, `last_name`, `phone_number`
- `is_active`, `is_verified`, `must_change_password`, `is_staff`, `is_superuser`
- `last_login`, `date_joined`, `created_at`, `updated_at`

### 2.3 Table: `accounts_user_institute_membership`
User-to-institute binding with controlled roles.
- `id` (UUID, PK)
- `user_id` (FK &rarr; `accounts_user.id`)
- `institute_id` (FK &rarr; `institutes_institute.id`)
- `role` (VARCHAR(30), `platform_admin`/`institute_admin`/`teacher`/`student`/`exam_staff`)
- `exam_permissions` (JSONB, e.g. `["setter", "moderator"]`)
- `identifier` (VARCHAR(100), Roll number or faculty ID)
- `status` (`active`/`inactive`/`invited`/`suspended`), `is_verified`
- Constraints: UNIQUE `(user_id, institute_id)`
- Indexes: `(institute_id, role, status)`, `(institute_id, identifier)`

### 2.4 Table: `accounts_account_invitation`
Onboarding invitations with SHA-256 token hash.
- `id`, `email`, `institute_id`, `role`, `token_hash`, `status`, `invited_by_id`, `expires_at`, `accepted_at`

### 2.5 Table: `accounts_account_verification`
Time-limited 6-digit OTP verification codes (SHA-256 code hash).
- `id`, `user_id`, `code_hash`, `purpose`, `expires_at`, `used_at`, `attempts`

### 2.6 Table: `accounts_password_reset_request`
Single-use secure password reset token records (SHA-256 token hash).
- `id`, `user_id`, `token_hash`, `expires_at`, `used_at`, `ip_address`

### 2.7 Table: `accounts_bulk_import_job`
Tracks bulk user roster uploads (CSV / Excel).
- `id`, `institute_id`, `import_type`, `file_name`, `status`, `total_rows`, `valid_rows`, `error_rows`, `imported_rows`, `parsed_data`

### 2.8 Table: `accounts_bulk_import_row_error`
Row-level validation error details for batch imports.
- `id`, `import_job_id`, `row_number`, `field_name`, `error_code`, `error_message`, `raw_data`

---

## 3. Implemented Schema: Module M2 (Academic Structure & Syllabus Management)

### 3.1 Table: `academics_department`
Academic department within an institute (e.g. Computer Science).

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `institute_id` | `UUID` | FK &rarr; `institutes_institute.id` (ON DELETE CASCADE) |
| `code` | `VARCHAR(50)` | Department code (e.g. `CSE`, `ECE`) |
| `name` | `VARCHAR(255)` | Full department name |
| `status` | `VARCHAR(20)` | `active`, `inactive`, `archived` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Constraints & Indexes:**
- UNIQUE `(institute_id, code)`
- Index `(institute_id, status)`

---

### 3.2 Table: `academics_program`
Degree or academic program (e.g. B.Tech Computer Science).

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `institute_id` | `UUID` | FK &rarr; `institutes_institute.id` (ON DELETE CASCADE) |
| `department_id` | `UUID` | FK &rarr; `academics_department.id` (ON DELETE CASCADE) |
| `code` | `VARCHAR(50)` | Program code (e.g. `BTECH-CSE`) |
| `name` | `VARCHAR(255)` | Full program title |
| `qualification_type` | `VARCHAR(50)` | `undergraduate`, `postgraduate`, `diploma`, `doctorate` |
| `duration_years` | `INTEGER` | Duration in years (e.g. 4) |
| `total_semesters` | `INTEGER` | Total terms/semesters (e.g. 8) |
| `status` | `VARCHAR(20)` | `active`, `inactive`, `archived` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Constraints & Validation:**
- UNIQUE `(institute_id, code)`
- Model validation: `department.institute_id == institute_id`

---

### 3.3 Table: `academics_academic_year`
Academic year session for an institute (e.g. 2025-2026).

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `institute_id` | `UUID` | FK &rarr; `institutes_institute.id` (ON DELETE CASCADE) |
| `label` | `VARCHAR(50)` | Session label (e.g. `2025-2026`) |
| `start_date` | `DATE` | Term start date |
| `end_date` | `DATE` | Term end date (`end_date > start_date`) |
| `is_current` | `BOOLEAN` | Default `False`. Indicates active session |
| `status` | `VARCHAR(20)` | `active`, `inactive`, `archived` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Constraints:**
- UNIQUE `(institute_id, label)`

---

### 3.4 Table: `academics_semester`
Individual term/semester within a program (e.g. Semester 1).

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `program_id` | `UUID` | FK &rarr; `academics_program.id` (ON DELETE CASCADE) |
| `semester_number` | `INTEGER` | Term number (1 to `program.total_semesters`) |
| `label` | `VARCHAR(50)` | Term label (e.g. `Semester 1`) |
| `status` | `VARCHAR(20)` | `active`, `inactive`, `archived` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Constraints:**
- UNIQUE `(program_id, semester_number)`

---

### 3.5 Table: `academics_batch`
Student cohort / admission batch (e.g. Batch 2025-2029).

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `institute_id` | `UUID` | FK &rarr; `institutes_institute.id` (ON DELETE CASCADE) |
| `program_id` | `UUID` | FK &rarr; `academics_program.id` (ON DELETE CASCADE) |
| `name` | `VARCHAR(100)` | Batch name (e.g. `Batch 2025-2029`) |
| `admission_year` | `INTEGER` | Year of enrollment (e.g. `2025`) |
| `status` | `VARCHAR(20)` | `active`, `inactive`, `archived` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Constraints:**
- UNIQUE `(program_id, name)`
- Model validation: `program.institute_id == institute_id`

---

### 3.6 Table: `academics_section`
Division or section within a cohort batch (e.g. Section A).

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `batch_id` | `UUID` | FK &rarr; `academics_batch.id` (ON DELETE CASCADE) |
| `name` | `VARCHAR(50)` | Section designation (e.g. `Section A`) |
| `status` | `VARCHAR(20)` | `active`, `inactive`, `archived` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Constraints:**
- UNIQUE `(batch_id, name)`

---

### 3.7 Table: `academics_subject`
Academic course or subject (e.g. CS101: Data Structures and Algorithms).

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `institute_id` | `UUID` | FK &rarr; `institutes_institute.id` (ON DELETE CASCADE) |
| `department_id` | `UUID` | FK &rarr; `academics_department.id` (Nullable, ON DELETE SET_NULL) |
| `code` | `VARCHAR(50)` | Subject code (e.g. `CS101`, Indexed) |
| `name` | `VARCHAR(255)` | Subject title |
| `description` | `TEXT` | Syllabus summary / overview |
| `credit_hours` | `NUMERIC(4, 1)`| Credit weight (e.g. `4.0`) |
| `status` | `VARCHAR(20)` | `active`, `inactive`, `archived` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Constraints:**
- UNIQUE `(institute_id, code)`

---

### 3.8 Table: `academics_program_semester_subject`
Associates subjects with programs and specific semester terms.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `program_id` | `UUID` | FK &rarr; `academics_program.id` (ON DELETE CASCADE) |
| `semester_id` | `UUID` | FK &rarr; `academics_semester.id` (ON DELETE CASCADE) |
| `subject_id` | `UUID` | FK &rarr; `academics_subject.id` (ON DELETE CASCADE) |
| `is_mandatory` | `BOOLEAN` | Default `True` (Core vs Elective) |
| `credits` | `NUMERIC(4, 1)`| Term credit allocation |
| `syllabus_version` | `VARCHAR(50)`| Syllabus version tag (e.g. `v1.0`) |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Constraints & Validation:**
- UNIQUE `(program_id, semester_id, subject_id)`
- Model validation: `semester.program_id == program_id`, `subject.institute_id == program.institute_id`

---

### 3.9 Table: `academics_unit`
Syllabus unit / module within a subject.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `subject_id` | `UUID` | FK &rarr; `academics_subject.id` (ON DELETE CASCADE) |
| `unit_number` | `INTEGER` | Unit index (1, 2, 3...) |
| `title` | `VARCHAR(255)` | Unit title |
| `description` | `TEXT` | Unit overview |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Constraints:**
- UNIQUE `(subject_id, unit_number)`

---

### 3.10 Table: `academics_topic`
Individual topic within a curriculum unit.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `unit_id` | `UUID` | FK &rarr; `academics_unit.id` (ON DELETE CASCADE) |
| `title` | `VARCHAR(255)` | Topic title |
| `description` | `TEXT` | Topic summary |
| `order` | `INTEGER` | Display order sequence |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Constraints:**
- UNIQUE `(unit_id, title)`

---

### 3.11 Table: `academics_learning_outcome`
Course Learning Outcome (CO) mapped to a Subject.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `subject_id` | `UUID` | FK &rarr; `academics_subject.id` (ON DELETE CASCADE) |
| `code` | `VARCHAR(50)` | Outcome code (e.g. `CO1`, `CO2`) |
| `description` | `TEXT` | Measurable outcome description |
| `category` | `VARCHAR(50)` | `cognitive`, `affective`, `psychomotor` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Constraints:**
- UNIQUE `(subject_id, code)`

---

### 3.12 Table: `academics_syllabus_mapping`
Maps topics or subjects to academic years and textbook reference materials.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `subject_id` | `UUID` | FK &rarr; `academics_subject.id` (ON DELETE CASCADE) |
| `topic_id` | `UUID` | FK &rarr; `academics_topic.id` (Nullable, ON DELETE SET_NULL) |
| `academic_year_id` | `UUID` | FK &rarr; `academics_academic_year.id` (ON DELETE CASCADE) |
| `syllabus_version` | `VARCHAR(50)`| Version label (default `v1.0`) |
| `syllabus_reference`| `TEXT` | Chapter, book, or curriculum reference |
| `status` | `VARCHAR(20)` | `active`, `inactive`, `archived` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

---

### 3.13 Table: `academics_teacher_assignment`
Assigns an authorized teacher to a subject, academic year, and cohort/section.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `teacher_id` | `UUID` | FK &rarr; `accounts_user_institute_membership.id` (ON DELETE CASCADE) |
| `subject_id` | `UUID` | FK &rarr; `academics_subject.id` (ON DELETE CASCADE) |
| `academic_year_id`| `UUID` | FK &rarr; `academics_academic_year.id` (ON DELETE CASCADE) |
| `batch_id` | `UUID` | FK &rarr; `academics_batch.id` (Nullable, ON DELETE SET_NULL) |
| `section_id` | `UUID` | FK &rarr; `academics_section.id` (Nullable, ON DELETE SET_NULL) |
| `status` | `VARCHAR(20)` | `active`, `completed`, `revoked` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Indexes & Validation:**
- Indexes: `(teacher_id, status)`, `(subject_id, academic_year_id)`
- Model validation: `teacher.role in ['teacher', 'exam_staff']`, `teacher.institute_id == subject.institute_id == academic_year.institute_id`

---

### 3.14 Table: `academics_student_academic_placement`
Tracks student academic progression while maintaining complete historical term records.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `student_id` | `UUID` | FK &rarr; `accounts_user_institute_membership.id` (ON DELETE CASCADE) |
| `program_id` | `UUID` | FK &rarr; `academics_program.id` (ON DELETE CASCADE) |
| `batch_id` | `UUID` | FK &rarr; `academics_batch.id` (ON DELETE CASCADE) |
| `semester_id` | `UUID` | FK &rarr; `academics_semester.id` (ON DELETE CASCADE) |
| `section_id` | `UUID` | FK &rarr; `academics_section.id` (Nullable, ON DELETE SET_NULL) |
| `effective_start_date` | `DATE` | Start date of placement |
| `effective_end_date` | `DATE` | Nullable end date (set upon progression) |
| `status` | `VARCHAR(20)` | `active`, `completed`, `transferred`, `withdrawn` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Indexes & Progression Rules:**
- Indexes: `(student_id, status)`, `(program_id, semester_id, status)`, `(batch_id, status)`
- Historical Retention: On term progression, prior record is transitioned to `completed` with `effective_end_date` populated. A new record is created with `status='active'`. Past term records are **never overwritten or deleted**.

---

## 4. Implemented Schema: Module M3 (Question Bank Management)

### 4.1 Table: `questions_question_tag`
Categorization tags for questions scoped to an institute.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `institute_id` | `UUID` | FK &rarr; `institutes_institute.id` (ON DELETE CASCADE) |
| `name` | `VARCHAR(100)` | Tag name (e.g. `Algorithms`, `Mechanics`) |
| `slug` | `VARCHAR(100)` | Auto-generated URL slug |
| `created_at` | `TIMESTAMPTZ` | Timestamp |

**Constraints & Indexes:**
- UNIQUE `(institute_id, name)`

---

### 4.2 Table: `questions_question`
Central multi-tenant question bank repository entity.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `institute_id` | `UUID` | FK &rarr; `institutes_institute.id` (ON DELETE CASCADE) |
| `subject_id` | `UUID` | FK &rarr; `academics_subject.id` (ON DELETE CASCADE) |
| `unit_id` | `UUID` | FK &rarr; `academics_unit.id` (Nullable, ON DELETE SET_NULL) |
| `topic_id` | `UUID` | FK &rarr; `academics_topic.id` (Nullable, ON DELETE SET_NULL) |
| `learning_outcome_id` | `UUID` | FK &rarr; `academics_learning_outcome.id` (Nullable, ON DELETE SET_NULL) |
| `question_type` | `VARCHAR(30)` | `mcq`, `true_false`, `short_answer`, `long_answer`, `coding` |
| `question_text` | `TEXT` | Full question stem/prompt |
| `difficulty` | `VARCHAR(20)` | `easy`, `medium`, `hard` |
| `marks` | `DECIMAL(5,2)` | Strictly positive marks (default `1.00`) |
| `negative_marks` | `DECIMAL(5,2)` | Non-negative penalty marks, cannot exceed positive marks |
| `bloom_taxonomy` | `VARCHAR(30)` | `remember`, `understand`, `apply`, `analyze`, `evaluate`, `create` |
| `origin_type` | `VARCHAR(20)` | `manual`, `ai_generated` |
| `status` | `VARCHAR(20)` | `draft`, `under_review`, `approved`, `rejected`, `archived` |
| `current_version` | `POSITIVEINT` | Current revision number (default `1`) |
| `created_by_id` | `UUID` | FK &rarr; `accounts_user.id` (Nullable, ON DELETE SET_NULL) |
| `code_metadata` | `JSONB` | Programming language, starter code, execution limits for coding questions |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Constraints, Indexes & Business Invariants:**
- Indexes: `(institute_id, status)`, `(subject_id, question_type, difficulty)`, `(subject_id, status)`
- Clean Invariants:
  - `marks > 0` and `0 <= negative_marks <= marks`.
  - Subject, Unit, Topic, and Learning Outcome must strictly belong to the same institute as the question.
  - Creation/updating status cannot be set to `approved` directly (must pass through review workflow).

---

### 4.3 Table: `questions_question_option`
Normalized individual options for Multiple Choice and True/False questions.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `question_id` | `UUID` | FK &rarr; `questions_question.id` (ON DELETE CASCADE) |
| `option_key` | `VARCHAR(10)` | Option label (e.g. `A`, `B`, `C`, `D`) |
| `option_text` | `TEXT` | Option content |
| `is_correct` | `BOOLEAN` | Correct answer flag (MCQ &ge; 1 correct; True/False == exactly 1) |
| `explanation` | `TEXT` | Per-option distractor/justification explanation |
| `order` | `POSITIVEINT` | Display order (1, 2, 3...) |

**Constraints:**
- UNIQUE `(question_id, option_key)`

---

### 4.4 Table: `questions_answer_key`
Canonical expected answer, sample solution, keywords, or automated test cases.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `question_id` | `UUID` | One-to-One FK &rarr; `questions_question.id` (ON DELETE CASCADE) |
| `expected_answer` | `TEXT` | Canonical answer text |
| `sample_solution` | `TEXT` | Detailed step-by-step worked solution |
| `test_cases` | `JSONB` | List of test cases for coding questions (`[{input, expected_output, is_hidden}]`) |
| `explanation` | `TEXT` | Rationale/explanation |
| `keywords` | `JSONB` | List of mandatory grading keywords/concepts |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

---

### 4.5 Table: `questions_question_rubric`
Grading criteria for subjective short and long answer questions.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `question_id` | `UUID` | FK &rarr; `questions_question.id` (ON DELETE CASCADE) |
| `criterion` | `VARCHAR(255)` | Grading dimension (e.g. `Correct Formula`, `Derivation Steps`) |
| `description` | `TEXT` | Scoring guidance |
| `max_marks` | `DECIMAL(5,2)` | Maximum marks allocatable for this criterion |
| `order` | `POSITIVEINT` | Sequential order |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

---

### 4.6 Table: `questions_question_source_reference`
Provenance tracking linking questions to textbooks, syllabi, and authoring documents.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `question_id` | `UUID` | FK &rarr; `questions_question.id` (ON DELETE CASCADE) |
| `source_title` | `VARCHAR(255)` | Source material title (e.g. `CLRS Algorithms 4th Ed`) |
| `page_or_section` | `VARCHAR(100)` | Section or page reference |
| `excerpt` | `TEXT` | Verbatim text or context evidence passage |
| `relevance_note` | `TEXT` | Description of relevance |
| `created_at` | `TIMESTAMPTZ` | Timestamp |

---

### 4.7 Table: `questions_question_version`
Immutable historical snapshot preserving question state across revisions.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `question_id` | `UUID` | FK &rarr; `questions_question.id` (ON DELETE CASCADE) |
| `version_number` | `POSITIVEINT` | Snapshot revision number |
| `snapshot_data` | `JSONB` | Immutable snapshot of text, options, answer key, rubrics, and marks |
| `changed_by_id` | `UUID` | FK &rarr; `accounts_user.id` (Nullable, ON DELETE SET_NULL) |
| `change_reason` | `TEXT` | Audit trail justification for change |
| `created_at` | `TIMESTAMPTZ` | Timestamp |

**Constraints:**
- UNIQUE `(question_id, version_number)`

---

### 4.8 Table: `questions_question_review`
Reviewer decisions, comments, and timestamps (M5 verification integration point).

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `question_id` | `UUID` | FK &rarr; `questions_question.id` (ON DELETE CASCADE) |
| `reviewer_id` | `UUID` | FK &rarr; `accounts_user.id` (Nullable, ON DELETE SET_NULL) |
| `decision` | `VARCHAR(20)` | `approved`, `rejected`, `needs_revision` |
| `comment` | `TEXT` | Reviewer notes |
| `created_at` | `TIMESTAMPTZ` | Timestamp |

---

## 5. Implemented Schema: Module M4 (AI Question Generation Engine)

### 5.1 Table: `ai_source_document`
Authorized academic source material uploaded by teachers or administrators.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `institute_id` | `UUID` | FK &rarr; `institutes_institute.id` (ON DELETE CASCADE) |
| `subject_id` | `UUID` | FK &rarr; `academics_subject.id` (ON DELETE CASCADE) |
| `unit_id` | `UUID` | FK &rarr; `academics_unit.id` (Nullable, ON DELETE SET_NULL) |
| `topic_id` | `UUID` | FK &rarr; `academics_topic.id` (Nullable, ON DELETE SET_NULL) |
| `title` | `VARCHAR(255)` | Document title |
| `file` | `VARCHAR(500)` | Stored file path (`source_materials/%Y/%m/`) |
| `file_type` | `VARCHAR(20)` | `pdf`, `docx`, `txt` |
| `file_size` | `POSITIVEINT` | Document size in bytes (max 15MB) |
| `processing_status` | `VARCHAR(30)` | `pending`, `processing`, `completed`, `failed` |
| `error_message` | `TEXT` | Sanitized extraction error details |
| `extracted_text` | `TEXT` | Full extracted text from document |
| `total_pages` | `POSITIVEINT` | Document page count |
| `uploaded_by_id` | `UUID` | FK &rarr; `accounts_user.id` (Nullable, ON DELETE SET_NULL) |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Constraints & Indexes:**
- Index: `(institute_id, subject_id, processing_status)`
- Multi-tenant validation: `subject.institute_id == institute_id`, `unit.subject_id == subject_id`, `topic.unit_id == unit_id`

---

### 5.2 Table: `ai_source_document_chunk`
Structured text passages extracted from source documents with page numbers.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `document_id` | `UUID` | FK &rarr; `ai_source_document.id` (ON DELETE CASCADE) |
| `chunk_index` | `POSITIVEINT` | Sequential chunk ordering |
| `section_title` | `VARCHAR(255)` | Section label or page reference |
| `page_number` | `POSITIVEINT` | Original document page number (Nullable) |
| `content` | `TEXT` | Passage text content |
| `char_count` | `POSITIVEINT` | Character length |
| `created_at` | `TIMESTAMPTZ` | Timestamp |

**Constraints:**
- UNIQUE `(document_id, chunk_index)`

---

### 5.3 Table: `ai_question_generation_job`
Audit and execution entity tracking AI generation requests, distributions, and results.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `institute_id` | `UUID` | FK &rarr; `institutes_institute.id` (ON DELETE CASCADE) |
| `subject_id` | `UUID` | FK &rarr; `academics_subject.id` (ON DELETE CASCADE) |
| `unit_id` | `UUID` | FK &rarr; `academics_unit.id` (Nullable, ON DELETE SET_NULL) |
| `topic_id` | `UUID` | FK &rarr; `academics_topic.id` (Nullable, ON DELETE SET_NULL) |
| `learning_outcome_id` | `UUID` | FK &rarr; `academics_learning_outcome.id` (Nullable, ON DELETE SET_NULL) |
| `requested_by_id` | `UUID` | FK &rarr; `accounts_user.id` (Nullable, ON DELETE SET_NULL) |
| `status` | `VARCHAR(30)` | `pending`, `processing`, `completed`, `partially_completed`, `failed` |
| `question_types` | `JSONB` | List of requested types (`mcq`, `true_false`, `short_answer`, etc.) |
| `num_questions_requested`| `POSITIVEINT` | Questions requested (1 &le; N &le; 20) |
| `num_questions_generated`| `POSITIVEINT` | Valid questions persisted into M3 Question Bank |
| `num_questions_failed_validation` | `POSITIVEINT` | Candidates rejected by schema/grounding rules |
| `difficulty_distribution`| `JSONB` | Target breakdown by difficulty |
| `bloom_taxonomy_distribution` | `JSONB` | Target breakdown by Bloom's cognitive level |
| `default_marks` | `DECIMAL(5,2)` | Default marks allocation |
| `default_negative_marks`| `DECIMAL(5,2)` | Default penalty allocation |
| `language` | `VARCHAR(50)` | Generation language (default `English`) |
| `safe_diagnostics` | `JSONB` | Provider, model name, tokens, passages supplied |
| `error_message` | `TEXT` | Safe error message |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Constraints & Indexes:**
- Index: `(institute_id, status, created_at)`
- Many-to-Many: `source_documents` &rarr; `ai_source_document`

---

### 5.4 Table: `ai_generated_candidate_record`
Diagnostics and outcome log for each candidate question generated by the LLM.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `job_id` | `UUID` | FK &rarr; `ai_question_generation_job.id` (ON DELETE CASCADE) |
| `persisted_question_id` | `UUID` | FK &rarr; `questions_question.id` (Nullable, ON DELETE SET_NULL) |
| `candidate_number` | `POSITIVEINT` | Candidate sequence number |
| `question_type` | `VARCHAR(30)` | `mcq`, `true_false`, `short_answer`, `long_answer`, `coding` |
| `status` | `VARCHAR(30)` | `saved`, `validation_failed`, `unsupported_content` |
| `candidate_data` | `JSONB` | Sanitized candidate content |
| `validation_errors` | `JSONB` | Detailed validation errors if rejected |
| `provenance_info` | `JSONB` | Cited document title, page, and verbatim excerpt |
| `created_at` | `TIMESTAMPTZ` | Timestamp |

---

## 6. Implemented Schema: Module M5 (Question Verification & Review)

### 6.1 Table: `reviews_question_review_record`
Immutable audit log of all question verification and review decisions, comments, and state transitions.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `question_id` | `UUID` | FK &rarr; `questions_question.id` (ON DELETE CASCADE) |
| `reviewer_id` | `UUID` | FK &rarr; `accounts_user.id` (Nullable, ON DELETE SET_NULL) |
| `decision` | `VARCHAR(30)` | `approve`, `reject`, `request_revision` |
| `from_status` | `VARCHAR(30)` | Status prior to decision (`draft`, `under_review`, `rejected`, etc.) |
| `to_status` | `VARCHAR(30)` | Status resulting from decision (`under_review`, `approved`, `rejected`, `draft`, `archived`) |
| `rejection_reason` | `TEXT` | Mandatory reason when decision is `reject` |
| `revision_feedback` | `TEXT` | Specific feedback for author when decision is `request_revision` |
| `general_notes` | `TEXT` | Reviewer notes or justification |
| `rubric_scores` | `JSONB` | Optional objective rubric scoring breakdown |
| `question_version` | `POSITIVEINT` | Question snapshot revision number when review occurred |
| `created_at` | `TIMESTAMPTZ` | Timestamp, indexed |

**Indexes & Rules:**
- Indexes: `(question_id, -created_at)`, `(reviewer_id, -created_at)`, `(decision, -created_at)`
- Review Decisions: Authors cannot approve their own questions (`anti_self_approval`).
- Review State Transitions: Questions cannot jump directly from `draft` to `approved`.

---

## 7. Implemented Schema: Module M6 (Blueprint Paper Generation)

### 7.1 Table: `blueprints_paper_blueprint`
Examination blueprint specifying paper title, subject, total marks, duration, and section architecture.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `institute_id` | `UUID` | FK &rarr; `accounts_institute.id` (ON DELETE CASCADE) |
| `title` | `VARCHAR(255)` | Blueprint title |
| `subject_id` | `UUID` | FK &rarr; `academics_subject.id` (ON DELETE CASCADE) |
| `academic_year_id` | `UUID` | FK &rarr; `academics_academic_year.id` (Nullable, ON DELETE SET_NULL) |
| `semester_id` | `UUID` | FK &rarr; `academics_semester.id` (Nullable, ON DELETE SET_NULL) |
| `program_id` | `UUID` | FK &rarr; `academics_program.id` (Nullable, ON DELETE SET_NULL) |
| `department_id` | `UUID` | FK &rarr; `academics_department.id` (Nullable, ON DELETE SET_NULL) |
| `total_marks` | `DECIMAL(6,2)` | Blueprint overall marks (must equal sum of section marks) |
| `duration_minutes` | `POSITIVEINT` | Examination duration (minutes) |
| `status` | `VARCHAR(20)` | `draft`, `active`, `archived` |
| `allow_question_reuse` | `BOOLEAN` | If `false`, prevents duplicate question selection in a paper |
| `general_instructions`| `TEXT` | Exam rubric instructions |
| `created_by_id` | `UUID` | FK &rarr; `accounts_user.id` (Nullable, ON DELETE SET_NULL) |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Indexes & Rules:**
- Indexes: `(institute_id, status)`, `(subject_id, status)`
- Isolation: Subject, Department, and Program must belong to the same institute.

---

### 7.2 Table: `blueprints_blueprint_section`
Named section within a blueprint (e.g. Section A: Multiple Choice Questions).

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `blueprint_id` | `UUID` | FK &rarr; `blueprints_paper_blueprint.id` (ON DELETE CASCADE) |
| `name` | `VARCHAR(100)` | Section label |
| `order` | `POSITIVEINT` | Sequence order (1, 2, 3...) |
| `instructions` | `TEXT` | Section-specific instructions |
| `target_marks` | `DECIMAL(6,2)` | Target marks allocated to section (must equal sum of rules) |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Constraints:**
- UNIQUE `(blueprint_id, name)`

---

### 7.3 Table: `blueprints_blueprint_rule`
Normalized selection criteria defining exact question types, counts, and marks per question.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `section_id` | `UUID` | FK &rarr; `blueprints_blueprint_section.id` (ON DELETE CASCADE) |
| `order` | `POSITIVEINT` | Sequence order |
| `question_type` | `VARCHAR(30)` | `mcq`, `true_false`, `short_answer`, `long_answer`, `coding` |
| `question_count` | `POSITIVEINT` | Exact number of questions required |
| `marks_per_question`| `DECIMAL(5,2)` | Marks allocated per question |
| `unit_id` | `UUID` | FK &rarr; `academics_unit.id` (Nullable, ON DELETE SET_NULL) |
| `topic_id` | `UUID` | FK &rarr; `academics_topic.id` (Nullable, ON DELETE SET_NULL) |
| `learning_outcome_id`| `UUID` | FK &rarr; `academics_learningoutcome.id` (Nullable, ON DELETE SET_NULL) |
| `difficulty` | `VARCHAR(20)` | Optional exact difficulty: `easy`, `medium`, `hard` |
| `bloom_taxonomy` | `VARCHAR(30)` | Optional exact Bloom level |
| `difficulty_distribution` | `JSONB` | Optional distribution specification |
| `bloom_taxonomy_distribution`| `JSONB` | Optional distribution specification |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

---

### 7.4 Table: `blueprints_generated_paper`
Generated paper generated from an approved blueprint and approved M3 questions.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `institute_id` | `UUID` | FK &rarr; `accounts_institute.id` (ON DELETE CASCADE) |
| `blueprint_id` | `UUID` | FK &rarr; `blueprints_paper_blueprint.id` (ON DELETE CASCADE) |
| `title` | `VARCHAR(255)` | Paper title |
| `subject_id` | `UUID` | FK &rarr; `academics_subject.id` (ON DELETE CASCADE) |
| `total_marks` | `DECIMAL(6,2)` | Total marks |
| `duration_minutes` | `POSITIVEINT` | Duration in minutes |
| `status` | `VARCHAR(20)` | `generating`, `completed`, `failed` |
| `generation_version`| `POSITIVEINT` | Incremental paper version (1, 2, 3...) for regeneration history |
| `blueprint_snapshot`| `JSONB` | Immutable snapshot of blueprint structure, sections, and rules |
| `validation_report` | `JSONB` | Reconciliation summary, question counts, and shortage logs |
| `created_by_id` | `UUID` | FK &rarr; `accounts_user.id` (Nullable, ON DELETE SET_NULL) |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Standard timestamps |

**Indexes:**
- Indexes: `(institute_id, status)`, `(blueprint_id, -generation_version)`, `(subject_id, -created_at)`

---

### 7.5 Table: `blueprints_generated_paper_question`
Ordered snapshot of each question placed into a generated paper.

| Column | Type | Constraints / Details |
|:---|:---|:---|
| `id` | `UUID` | Primary Key, `default=uuid.uuid4` |
| `paper_id` | `UUID` | FK &rarr; `blueprints_generated_paper.id` (ON DELETE CASCADE) |
| `section_name` | `VARCHAR(100)` | Section heading |
| `section_order` | `POSITIVEINT` | Section sequence order |
| `question_number` | `POSITIVEINT` | Sequential question number in paper (1, 2, 3...) |
| `question_id` | `UUID` | FK &rarr; `questions_question.id` (Nullable, ON DELETE SET_NULL) |
| `question_version` | `POSITIVEINT` | Snapshot version of source question when generated |
| `question_type` | `VARCHAR(30)` | Question type |
| `question_text` | `TEXT` | Snapshot question text |
| `marks` | `DECIMAL(5,2)` | Allocated marks |
| `negative_marks` | `DECIMAL(5,2)` | Penalty marks |
| `difficulty` | `VARCHAR(20)` | Difficulty |
| `bloom_taxonomy` | `VARCHAR(30)` | Bloom taxonomy level |
| `options_snapshot` | `JSONB` | Options snapshot without disclosing correct answers in student contexts |
| `rubric_snapshot` | `JSONB` | Scoring rubric criteria |
| `provenance_snapshot`| `JSONB` | Source citations and reference excerpts |
| `created_at` | `TIMESTAMPTZ` | Timestamp |

**Constraints:**
- UNIQUE `(paper_id, question_number)`

---

## 8. Module M11 — Coding Examination Snapshots and Submissions

### 8.1 `blueprints_generated_paper_question` coding additions
- `test_cases_snapshot` (`JSONB`, default `[]`): immutable cases copied from the reviewed answer key, including hidden-case flags and expected outputs.
- `code_metadata_snapshot` (`JSONB`, default `{}`): immutable language, starter template, and execution constraints.

These fields are server-side grading material and are never serialized to students. Paper amendments copy both fields from their source snapshot.
The migration backfills coding cases, code metadata, and objective correctness only from the matching immutable `questions_question_version` snapshot. It does not copy current mutable answer keys into old papers; deleted questions or missing versions remain unavailable for automated evaluation.

### 8.2 `exams_coding_submission`
- `id` UUID primary key; `answer_id` FK to `exams_exam_answer`.
- `code` and `language` preserve the submitted version; `source_hash` makes identical submissions idempotent.
- `status`: `queued`, `running`, `completed`, or `failed`.
- `test_results`, `passed_count`, `total_count`, `marks_awarded`, `error_code`, `submitted_at`, and `completed_at` store private provider outcomes and lifecycle.
- UNIQUE `(answer_id, source_hash)`.

Submitted code is sent only to a configured isolated HTTPS execution provider; no subprocess execution occurs in Django.

## 9. Module M12 — Exam Answer Evaluations

### 9.1 `exams_exam_answer_evaluation`
- One-to-one `answer_id` FK to an attempt answer.
- `status`: `pending`, `graded`, or `human_review`.
- `marks_awarded` is nullable until graded; `max_marks` comes from the released paper snapshot.
- `feedback`, restricted `details`, `grading_method`, optional `evaluated_by`, `evaluated_at`, and timestamps.

Objective marks are calculated from private correctness data in the immutable paper snapshot. Student result access is filtered to the student's own attempt; manager result access is institute-scoped.

## 10. Module M13 — Handwritten Answer-Sheet Evaluation

### 10.1 `exams_handwritten_answer_sheet`
- One-to-one `attempt_id` FK; `file` stored under a tenant/attempt-specific path and served only through an authorized download endpoint.
- `uploaded_by`, `status` (`uploaded`, `extracted`, `human_review`, `reviewed`, `extraction_failed`), private `extracted_text`, bounded `extraction_error`, and upload/extraction timestamps.

### 10.2 `exams_handwritten_answer_evaluation`
- FK to the sheet and released `paper_question`; UNIQUE `(sheet_id, paper_question_id)`.
- `marks_awarded`, `max_marks`, criterion-keyed `rubric_scores`, `feedback`, `reviewed_by`, and `reviewed_at`.
- Scores are validated against the released paper question and rubric, and only institute exam managers may create reviews.

## 11. Modules M14–M16 — Revaluation, Analytics, and Outcomes

### 11.1 Revaluation records
- `exams_exam_schedule` stores the optional paired `revaluation_opens_at` / `revaluation_closes_at` window.
- `exams_revaluation_request` links an attempt and released-paper question to its student reason and current decision. UNIQUE `(attempt_id, paper_question_id)` prevents duplicate processing. Approved `corrected_marks` override the original result without mutating the grading record.
- `exams_revaluation_decision` is append-only decision history with reviewer, comment, prior marks, corrected marks, and timestamp. Significant decisions and mark corrections also use the central audit log.
- `exams_exam_grievance` records one non-mark grievance per submitted attempt; `exams_exam_grievance_decision` retains immutable reviewer decisions. Grievance decisions never modify marks.

### 11.2 Course/program outcome records
- `academics_program_outcome` stores institute-scoped outcomes by program/code.
- `academics_outcome_alignment` maps existing course outcomes to program outcomes; only subjects in the program curriculum are accepted.
- `academics_assessment_outcome_mapping` maps a released paper question to a course outcome from the same subject.
- Outcome reports expose only final-result mark evidence and preserve assessment/question traceability. No attainment score is calculated because the source specification does not define its formula, thresholds, or weighting.

## 12. Modules M17–M20 — Exam Lifecycle and Student Support

### 12.1 `notifications_notification`
- Institute-scoped record addressed to one user, with optional exam context, sender, subject/body, nullable idempotency key, email delivery state/error, creation time, and recipient read timestamp.
- UNIQUE `(recipient_id, event_key)` protects repeated event delivery when an idempotency key is supplied. In-app notifications are retained when SMTP is not configured.

Exam lifecycle transitions reuse `exams_exam_schedule` and are recorded in both exam activity events and the central audit log. Learning-support and early-warning outputs are computed from persisted assessments and do not store invented AI predictions or risk scores.
