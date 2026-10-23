import uuid
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.accounts.models import Institute, UserInstituteMembership, RoleChoices


class AcademicStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    INACTIVE = 'inactive', 'Inactive'
    ARCHIVED = 'archived', 'Archived'


class PlacementStatus(models.TextChoices):
    ACTIVE = 'active', 'Active Current Placement'
    COMPLETED = 'completed', 'Completed Term'
    TRANSFERRED = 'transferred', 'Transferred / Promoted'
    WITHDRAWN = 'withdrawn', 'Withdrawn'


class QualificationType(models.TextChoices):
    UNDERGRADUATE = 'undergraduate', 'Undergraduate'
    POSTGRADUATE = 'postgraduate', 'Postgraduate'
    DIPLOMA = 'diploma', 'Diploma'
    DOCTORATE = 'doctorate', 'Doctorate'


class OutcomeCategory(models.TextChoices):
    COGNITIVE = 'cognitive', 'Cognitive'
    AFFECTIVE = 'affective', 'Affective'
    PSYCHOMOTOR = 'psychomotor', 'Psychomotor'


class AssignmentStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    COMPLETED = 'completed', 'Completed'
    REVOKED = 'revoked', 'Revoked'


class Department(models.Model):
    """
    Department within an Institute (e.g. Computer Science, Electrical Engineering).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='departments')
    code = models.CharField(max_length=50, db_index=True)
    name = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=AcademicStatus.choices, default=AcademicStatus.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_department'
        unique_together = ('institute', 'code')
        ordering = ['name']
        verbose_name = 'Department'
        verbose_name_plural = 'Departments'

    def __str__(self):
        return f"{self.name} ({self.code}) - {self.institute.code}"


class Program(models.Model):
    """
    Degree / Academic Program (e.g. B.Tech Computer Science, M.Sc Data Science).
    Belongs to an institute and department.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='programs')
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='programs')
    code = models.CharField(max_length=50, db_index=True)
    name = models.CharField(max_length=255)
    qualification_type = models.CharField(max_length=50, choices=QualificationType.choices, default=QualificationType.UNDERGRADUATE, blank=True)
    duration_years = models.PositiveIntegerField(default=4, null=True, blank=True)
    total_semesters = models.PositiveIntegerField(default=8, null=True, blank=True)
    is_department_mapping = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=AcademicStatus.choices, default=AcademicStatus.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_program'
        unique_together = ('institute', 'code')
        ordering = ['name']
        verbose_name = 'Program'
        verbose_name_plural = 'Programs'

    def clean(self):
        if self.department_id and self.department.institute_id != self.institute_id:
            raise ValidationError("Department must belong to the same institute as the program.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"


class AcademicYear(models.Model):
    """
    Academic Year session for an institute (e.g. '2025-2026').
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='academic_years')
    label = models.CharField(max_length=50)
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=AcademicStatus.choices, default=AcademicStatus.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_academic_year'
        unique_together = ('institute', 'label')
        ordering = ['-start_date']
        verbose_name = 'Academic Year'
        verbose_name_plural = 'Academic Years'

    def clean(self):
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValidationError("Academic year start date must precede end date.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.label} ({self.institute.code})"


class Semester(models.Model):
    """
    Semester within a Program (e.g. Semester 1 to Semester 8).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='semesters')
    semester_number = models.PositiveIntegerField()
    label = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=AcademicStatus.choices, default=AcademicStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_semester'
        unique_together = ('program', 'semester_number')
        ordering = ['program', 'semester_number']
        verbose_name = 'Semester'
        verbose_name_plural = 'Semesters'

    def clean(self):
        if (
            self.program_id
            and self.program.total_semesters is not None
            and self.semester_number > self.program.total_semesters
        ):
            raise ValidationError(f"Semester number {self.semester_number} exceeds program's total semesters ({self.program.total_semesters}).")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.program.code} - {self.label}"


class Batch(models.Model):
    """
    Student admission cohort / batch (e.g. 'Batch 2024-2028' admitted in 2024).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='batches')
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='batches')
    name = models.CharField(max_length=100)
    admission_year = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=AcademicStatus.choices, default=AcademicStatus.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_batch'
        unique_together = ('program', 'name')
        ordering = ['-admission_year', 'name']
        verbose_name = 'Batch'
        verbose_name_plural = 'Batches'

    def clean(self):
        if self.program_id and self.program.institute_id != self.institute_id:
            raise ValidationError("Program must belong to the same institute as the batch.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} - {self.program.code}"


class Section(models.Model):
    """
    Section / Division within a Batch (e.g. 'Section A', 'Section B').
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='sections')
    name = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=AcademicStatus.choices, default=AcademicStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_section'
        unique_together = ('batch', 'name')
        ordering = ['name']
        verbose_name = 'Section'
        verbose_name_plural = 'Sections'

    def __str__(self):
        return f"{self.batch.name} - {self.name}"


class Subject(models.Model):
    """
    Academic Subject / Course (e.g. 'CS101: Data Structures and Algorithms').
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='subjects')
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='subjects')
    code = models.CharField(max_length=50, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    credit_hours = models.DecimalField(max_digits=4, decimal_places=1, default=3.0)
    status = models.CharField(max_length=20, choices=AcademicStatus.choices, default=AcademicStatus.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_subject'
        unique_together = ('institute', 'code')
        ordering = ['code']
        verbose_name = 'Subject'
        verbose_name_plural = 'Subjects'

    def clean(self):
        if self.department_id and self.department.institute_id != self.institute_id:
            raise ValidationError("Department must belong to the same institute as the subject.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code}: {self.name}"


class ProgramSemesterSubject(models.Model):
    """
    Associates subjects with programs and semester placement,
    specifying credit hours and syllabus metadata.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='semester_subjects')
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, related_name='program_subjects')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='program_semesters')
    is_mandatory = models.BooleanField(default=True)
    credits = models.DecimalField(max_digits=4, decimal_places=1, default=3.0)
    syllabus_version = models.CharField(max_length=50, blank=True, default='v1.0')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_program_semester_subject'
        unique_together = ('program', 'semester', 'subject')
        verbose_name = 'Program Semester Subject'
        verbose_name_plural = 'Program Semester Subjects'

    def clean(self):
        if self.semester_id and self.program_id and self.semester.program_id != self.program_id:
            raise ValidationError("Semester must belong to the selected program.")
        if self.subject_id and self.program_id and self.subject.institute_id != self.program.institute_id:
            raise ValidationError("Subject and Program must belong to the same institute.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.program.code} - {self.semester.label} - {self.subject.code}"


class Unit(models.Model):
    """
    Curriculum unit within a Subject (e.g. Unit 1: Introduction to Trees).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='units')
    unit_number = models.PositiveIntegerField()
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_unit'
        unique_together = ('subject', 'unit_number')
        ordering = ['unit_number']
        verbose_name = 'Unit'
        verbose_name_plural = 'Units'

    def __str__(self):
        return f"{self.subject.code} - Unit {self.unit_number}: {self.title}"


class Topic(models.Model):
    """
    Topic within a Unit (e.g. Binary Search Trees, AVL Trees).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='topics')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    order = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_topic'
        unique_together = ('unit', 'title')
        ordering = ['order', 'title']
        verbose_name = 'Topic'
        verbose_name_plural = 'Topics'

    def __str__(self):
        return f"{self.unit.title} - {self.title}"


class LearningOutcome(models.Model):
    """
    Course Learning Outcome (CO) mapped to a Subject (e.g. CO1, CO2).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='learning_outcomes')
    code = models.CharField(max_length=50)
    description = models.TextField()
    category = models.CharField(max_length=50, choices=OutcomeCategory.choices, default=OutcomeCategory.COGNITIVE)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_learning_outcome'
        unique_together = ('subject', 'code')
        ordering = ['code']
        verbose_name = 'Learning Outcome'
        verbose_name_plural = 'Learning Outcomes'

    def __str__(self):
        return f"{self.subject.code} - {self.code}"


class ProgramOutcome(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='program_outcomes')
    code = models.CharField(max_length=50)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_program_outcome'
        unique_together = ('program', 'code')
        ordering = ['code']

    def __str__(self):
        return f"{self.program.code} - {self.code}"


class OutcomeAlignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    program_outcome = models.ForeignKey(
        ProgramOutcome, on_delete=models.CASCADE, related_name='course_alignments'
    )
    learning_outcome = models.ForeignKey(
        LearningOutcome, on_delete=models.CASCADE, related_name='program_alignments'
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'academics_outcome_alignment'
        unique_together = ('program_outcome', 'learning_outcome')
        ordering = ['program_outcome__code', 'learning_outcome__code']

    def clean(self):
        if self.program_outcome_id and self.learning_outcome_id:
            if not ProgramSemesterSubject.objects.filter(
                program_id=self.program_outcome.program_id,
                subject_id=self.learning_outcome.subject_id,
            ).exists():
                raise ValidationError(
                    'The course outcome subject must be included in the program curriculum.'
                )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class AssessmentOutcomeMapping(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    paper_question = models.ForeignKey(
        'blueprints.GeneratedPaperQuestion', on_delete=models.CASCADE,
        related_name='outcome_mappings',
    )
    learning_outcome = models.ForeignKey(
        LearningOutcome, on_delete=models.CASCADE, related_name='assessment_mappings'
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'academics_assessment_outcome_mapping'
        unique_together = ('paper_question', 'learning_outcome')
        ordering = ['paper_question__paper_id', 'paper_question__question_number']

    def clean(self):
        if self.paper_question_id and self.learning_outcome_id:
            if self.paper_question.paper.subject_id != self.learning_outcome.subject_id:
                raise ValidationError(
                    'The course outcome must belong to the assessment paper subject.'
                )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class SyllabusMapping(models.Model):
    """
    Associates topics/subjects with syllabus references and textbook sections.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='syllabus_mappings')
    topic = models.ForeignKey(Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name='syllabus_mappings')
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name='syllabus_mappings')
    syllabus_version = models.CharField(max_length=50, default='v1.0')
    syllabus_reference = models.TextField()
    status = models.CharField(max_length=20, choices=AcademicStatus.choices, default=AcademicStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_syllabus_mapping'
        verbose_name = 'Syllabus Mapping'
        verbose_name_plural = 'Syllabus Mappings'

    def clean(self):
        if self.subject_id and self.academic_year_id and self.subject.institute_id != self.academic_year.institute_id:
            raise ValidationError("Subject and Academic Year must belong to the same institute.")
        if self.topic_id and self.topic.unit.subject_id != self.subject_id:
            raise ValidationError("Topic must belong to the selected subject.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.subject.code} ({self.syllabus_version}) - {self.academic_year.label}"


class TeacherAssignment(models.Model):
    """
    Assigns an authorized teacher to a subject, academic year, and cohort/section.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    teacher = models.ForeignKey(UserInstituteMembership, on_delete=models.CASCADE, related_name='teaching_assignments')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='teacher_assignments')
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='teacher_assignments',
    )
    batch = models.ForeignKey(Batch, on_delete=models.SET_NULL, null=True, blank=True, related_name='teacher_assignments')
    section = models.ForeignKey(Section, on_delete=models.SET_NULL, null=True, blank=True, related_name='teacher_assignments')
    status = models.CharField(max_length=20, choices=AssignmentStatus.choices, default=AssignmentStatus.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_teacher_assignment'
        ordering = ['-created_at']
        verbose_name = 'Teacher Assignment'
        verbose_name_plural = 'Teacher Assignments'
        indexes = [
            models.Index(fields=['teacher', 'status']),
            models.Index(fields=['subject', 'academic_year']),
        ]

    def clean(self):
        if self.teacher_id:
            if self.teacher.role not in [RoleChoices.TEACHER, RoleChoices.EXAM_STAFF]:
                raise ValidationError("Only users with Teacher or Exam Staff roles can be assigned to teach subjects.")
            if self.subject_id and self.teacher.institute_id != self.subject.institute_id:
                raise ValidationError("Teacher and Subject must belong to the same institute.")
            if self.academic_year_id and self.teacher.institute_id != self.academic_year.institute_id:
                raise ValidationError("Teacher and Academic Year must belong to the same institute.")
        if self.batch_id and self.subject_id and self.batch.institute_id != self.subject.institute_id:
            raise ValidationError("Batch must belong to the same institute as the subject.")
        if self.section_id and self.batch_id and self.section.batch_id != self.batch_id:
            raise ValidationError("Section must belong to the assigned batch.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        academic_year = self.academic_year.label if self.academic_year_id else 'all academic years'
        return f"{self.teacher.user.email} -> {self.subject.code} ({academic_year})"


class StudentAcademicPlacement(models.Model):
    """
    Student academic placement record.
    Tracks program, batch, semester, and section.
    Preserves full historical progression as students advance without destroying past terms.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(UserInstituteMembership, on_delete=models.CASCADE, related_name='academic_placements')
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='student_placements')
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='student_placements')
    semester = models.ForeignKey(
        Semester,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='student_placements',
    )
    section = models.ForeignKey(Section, on_delete=models.SET_NULL, null=True, blank=True, related_name='student_placements')
    effective_start_date = models.DateField(default=timezone.localdate)
    effective_end_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=PlacementStatus.choices,
        default=PlacementStatus.ACTIVE,
        db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_student_academic_placement'
        ordering = ['-created_at']
        verbose_name = 'Student Academic Placement'
        verbose_name_plural = 'Student Academic Placements'
        indexes = [
            models.Index(fields=['student', 'status']),
            models.Index(fields=['program', 'semester', 'status']),
            models.Index(fields=['batch', 'status']),
        ]

    def clean(self):
        if self.student_id:
            if self.student.role != RoleChoices.STUDENT:
                raise ValidationError("Only students can have student academic placement records.")
            if self.program_id and self.student.institute_id != self.program.institute_id:
                raise ValidationError("Student and Program must belong to the same institute.")
        if self.semester_id and self.program_id and self.semester.program_id != self.program_id:
            raise ValidationError("Semester must belong to the selected Program.")
        if self.batch_id and self.program_id and self.batch.program_id != self.program_id:
            raise ValidationError("Batch must belong to the selected Program.")
        if self.section_id and self.batch_id and self.section.batch_id != self.batch_id:
            raise ValidationError("Section must belong to the selected Batch.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        semester = self.semester.label if self.semester_id else 'no term specified'
        return f"{self.student.user.email} - {self.program.code} - {semester} ({self.status})"


class StudentSubjectEnrollment(models.Model):
    """
    Explicit subject enrollment for a student within their assigned batch.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(
        UserInstituteMembership,
        on_delete=models.CASCADE,
        related_name='subject_enrollments',
    )
    batch = models.ForeignKey(
        Batch,
        on_delete=models.CASCADE,
        related_name='student_subject_enrollments',
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name='student_enrollments',
    )
    status = models.CharField(
        max_length=20,
        choices=[
            (AcademicStatus.ACTIVE, 'Active'),
            (AcademicStatus.INACTIVE, 'Inactive'),
        ],
        default=AcademicStatus.ACTIVE,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academics_student_subject_enrollment'
        unique_together = ('student', 'batch', 'subject')
        ordering = ['subject__code']
        indexes = [
            models.Index(fields=['student', 'batch', 'status']),
            models.Index(fields=['subject', 'status']),
        ]

    def clean(self):
        if self.student_id:
            if self.student.role != RoleChoices.STUDENT:
                raise ValidationError('Only student memberships can enroll in subjects.')
            if self.student.institute_id != self.batch.institute_id:
                raise ValidationError('Student and batch must belong to the same institute.')
            if self.student.institute_id != self.subject.institute_id:
                raise ValidationError('Student and subject must belong to the same institute.')
        if self.batch_id and self.subject_id:
            department_id = self.batch.program.department_id
            if self.subject.department_id != department_id:
                raise ValidationError('Subject must belong to the batch’s department.')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.student.identifier} - {self.batch.name} - {self.subject.code}'
