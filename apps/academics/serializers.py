from rest_framework import serializers
from django.utils import timezone
from apps.accounts.models import RoleChoices, MembershipStatus
from .models import (
    Department,
    Program,
    AcademicYear,
    Semester,
    Batch,
    Section,
    Subject,
    ProgramSemesterSubject,
    Unit,
    Topic,
    LearningOutcome,
    ProgramOutcome,
    OutcomeAlignment,
    AssessmentOutcomeMapping,
    ProgramSemesterSubject,
    SyllabusMapping,
    TeacherAssignment,
    StudentAcademicPlacement,
    PlacementStatus,
)


def validate_mapping_write_institute(serializer, institute_id):
    user = serializer.context['request'].user
    if not user.is_platform_admin and not user.memberships.filter(
        institute_id=institute_id,
        role=RoleChoices.INSTITUTE_ADMIN,
        status=MembershipStatus.ACTIVE,
    ).exists():
        raise serializers.ValidationError('Institute administrator permission is required.')


class DepartmentSerializer(serializers.ModelSerializer):
    institute_code = serializers.CharField(source='institute.code', read_only=True)

    class Meta:
        model = Department
        fields = ['id', 'institute', 'institute_code', 'code', 'name', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_code(self, value):
        return value.strip().upper()


class ProgramSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True)
    institute_code = serializers.CharField(source='institute.code', read_only=True)

    class Meta:
        model = Program
        fields = [
            'id', 'institute', 'institute_code', 'department', 'department_name',
            'code', 'name', 'qualification_type', 'duration_years',
            'total_semesters', 'status', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        dept = attrs.get('department')
        inst = attrs.get('institute')
        if dept and inst and dept.institute_id != inst.id:
            raise serializers.ValidationError({'department': 'Department must belong to the selected institute.'})
        return attrs


class AcademicYearSerializer(serializers.ModelSerializer):
    institute_code = serializers.CharField(source='institute.code', read_only=True)

    class Meta:
        model = AcademicYear
        fields = ['id', 'institute', 'institute_code', 'label', 'start_date', 'end_date', 'is_current', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        start = attrs.get('start_date')
        end = attrs.get('end_date')
        if start and end and start >= end:
            raise serializers.ValidationError({'end_date': 'End date must be after start date.'})
        return attrs


class SemesterSerializer(serializers.ModelSerializer):
    program_code = serializers.CharField(source='program.code', read_only=True)

    class Meta:
        model = Semester
        fields = ['id', 'program', 'program_code', 'semester_number', 'label', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        prog = attrs.get('program')
        sem_num = attrs.get('semester_number')
        if prog and sem_num and sem_num > prog.total_semesters:
            raise serializers.ValidationError({
                'semester_number': f"Semester number cannot exceed program's total semesters ({prog.total_semesters})."
            })
        return attrs


class BatchSerializer(serializers.ModelSerializer):
    program_code = serializers.CharField(source='program.code', read_only=True)
    institute_code = serializers.CharField(source='institute.code', read_only=True)

    class Meta:
        model = Batch
        fields = ['id', 'institute', 'institute_code', 'program', 'program_code', 'name', 'admission_year', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        prog = attrs.get('program')
        inst = attrs.get('institute')
        if prog and inst and prog.institute_id != inst.id:
            raise serializers.ValidationError({'program': 'Program must belong to the selected institute.'})
        return attrs


class SectionSerializer(serializers.ModelSerializer):
    batch_name = serializers.CharField(source='batch.name', read_only=True)

    class Meta:
        model = Section
        fields = ['id', 'batch', 'batch_name', 'name', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class SubjectSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True)
    institute_code = serializers.CharField(source='institute.code', read_only=True)

    class Meta:
        model = Subject
        fields = [
            'id', 'institute', 'institute_code', 'department', 'department_name',
            'code', 'name', 'description', 'credit_hours', 'status', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        dept = attrs.get('department')
        inst = attrs.get('institute')
        if dept and inst and dept.institute_id != inst.id:
            raise serializers.ValidationError({'department': 'Department must belong to the selected institute.'})
        return attrs


class ProgramSemesterSubjectSerializer(serializers.ModelSerializer):
    program_code = serializers.CharField(source='program.code', read_only=True)
    semester_label = serializers.CharField(source='semester.label', read_only=True)
    subject_code = serializers.CharField(source='subject.code', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True)

    class Meta:
        model = ProgramSemesterSubject
        fields = [
            'id', 'program', 'program_code', 'semester', 'semester_label',
            'subject', 'subject_code', 'subject_name', 'is_mandatory',
            'credits', 'syllabus_version', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        prog = attrs.get('program')
        sem = attrs.get('semester')
        subj = attrs.get('subject')

        if prog and sem and sem.program_id != prog.id:
            raise serializers.ValidationError({'semester': 'Semester must belong to the selected program.'})
        if prog and subj and subj.institute_id != prog.institute_id:
            raise serializers.ValidationError({'subject': 'Subject must belong to the same institute as the program.'})
        return attrs


class UnitSerializer(serializers.ModelSerializer):
    subject_code = serializers.CharField(source='subject.code', read_only=True)

    class Meta:
        model = Unit
        fields = ['id', 'subject', 'subject_code', 'unit_number', 'title', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class TopicSerializer(serializers.ModelSerializer):
    unit_title = serializers.CharField(source='unit.title', read_only=True)
    subject_code = serializers.CharField(source='unit.subject.code', read_only=True)

    class Meta:
        model = Topic
        fields = ['id', 'unit', 'unit_title', 'subject_code', 'title', 'description', 'order', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class LearningOutcomeSerializer(serializers.ModelSerializer):
    subject_code = serializers.CharField(source='subject.code', read_only=True)

    class Meta:
        model = LearningOutcome
        fields = ['id', 'subject', 'subject_code', 'code', 'description', 'category', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class ProgramOutcomeSerializer(serializers.ModelSerializer):
    program_code = serializers.CharField(source='program.code', read_only=True)

    class Meta:
        model = ProgramOutcome
        fields = ['id', 'program', 'program_code', 'code', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        program = attrs.get('program', getattr(self.instance, 'program', None))
        if program:
            validate_mapping_write_institute(self, program.institute_id)
        return attrs


class OutcomeAlignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = OutcomeAlignment
        fields = ['id', 'program_outcome', 'learning_outcome', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate(self, attrs):
        program_outcome = attrs.get(
            'program_outcome', getattr(self.instance, 'program_outcome', None)
        )
        learning_outcome = attrs.get(
            'learning_outcome', getattr(self.instance, 'learning_outcome', None)
        )
        if program_outcome and learning_outcome and not ProgramSemesterSubject.objects.filter(
            program_id=program_outcome.program_id,
            subject_id=learning_outcome.subject_id,
        ).exists():
            raise serializers.ValidationError({
                'learning_outcome': 'The course outcome subject must be included in the program curriculum.'
            })
        if program_outcome:
            validate_mapping_write_institute(
                self, program_outcome.program.institute_id
            )
        return attrs


class AssessmentOutcomeMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssessmentOutcomeMapping
        fields = ['id', 'paper_question', 'learning_outcome', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate(self, attrs):
        paper_question = attrs.get(
            'paper_question', getattr(self.instance, 'paper_question', None)
        )
        learning_outcome = attrs.get(
            'learning_outcome', getattr(self.instance, 'learning_outcome', None)
        )
        if (
            paper_question and learning_outcome
            and paper_question.paper.subject_id != learning_outcome.subject_id
        ):
            raise serializers.ValidationError({
                'learning_outcome': 'The course outcome must belong to the assessment paper subject.'
            })
        if paper_question:
            validate_mapping_write_institute(
                self, paper_question.paper.institute_id
            )
        return attrs


class SyllabusMappingSerializer(serializers.ModelSerializer):
    subject_code = serializers.CharField(source='subject.code', read_only=True)
    academic_year_label = serializers.CharField(source='academic_year.label', read_only=True)

    class Meta:
        model = SyllabusMapping
        fields = [
            'id', 'subject', 'subject_code', 'topic', 'academic_year',
            'academic_year_label', 'syllabus_version', 'syllabus_reference',
            'status', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        subj = attrs.get('subject')
        ay = attrs.get('academic_year')
        topic = attrs.get('topic')

        if subj and ay and subj.institute_id != ay.institute_id:
            raise serializers.ValidationError({'academic_year': 'Academic year must belong to the same institute as the subject.'})
        if subj and topic and topic.unit.subject_id != subj.id:
            raise serializers.ValidationError({'topic': 'Topic must belong to the selected subject.'})
        return attrs


class TeacherAssignmentSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source='teacher.user.full_name', read_only=True)
    teacher_email = serializers.CharField(source='teacher.user.email', read_only=True)
    subject_code = serializers.CharField(source='subject.code', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    academic_year_label = serializers.CharField(source='academic_year.label', read_only=True)

    class Meta:
        model = TeacherAssignment
        fields = [
            'id', 'teacher', 'teacher_name', 'teacher_email', 'subject',
            'subject_code', 'subject_name', 'academic_year', 'academic_year_label',
            'batch', 'section', 'status', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        teacher = attrs.get('teacher')
        subj = attrs.get('subject')
        ay = attrs.get('academic_year')
        batch = attrs.get('batch')
        section = attrs.get('section')

        if teacher:
            if teacher.role not in [RoleChoices.TEACHER, RoleChoices.EXAM_STAFF]:
                raise serializers.ValidationError({'teacher': 'Assigned member must have Teacher or Exam Staff role.'})
            if subj and teacher.institute_id != subj.institute_id:
                raise serializers.ValidationError({'subject': 'Teacher and Subject must belong to the same institute.'})
            if ay and teacher.institute_id != ay.institute_id:
                raise serializers.ValidationError({'academic_year': 'Teacher and Academic Year must belong to the same institute.'})
        if batch and subj and batch.institute_id != subj.institute_id:
            raise serializers.ValidationError({'batch': 'Batch must belong to the same institute as the subject.'})
        if section and batch and section.batch_id != batch.id:
            raise serializers.ValidationError({'section': 'Section must belong to the assigned batch.'})
        return attrs


class StudentAcademicPlacementSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.user.full_name', read_only=True)
    student_email = serializers.CharField(source='student.user.email', read_only=True)
    student_identifier = serializers.CharField(source='student.identifier', read_only=True)
    program_code = serializers.CharField(source='program.code', read_only=True)
    batch_name = serializers.CharField(source='batch.name', read_only=True)
    semester_label = serializers.CharField(source='semester.label', read_only=True)
    section_name = serializers.CharField(source='section.name', read_only=True)

    class Meta:
        model = StudentAcademicPlacement
        fields = [
            'id', 'student', 'student_name', 'student_email', 'student_identifier',
            'program', 'program_code', 'batch', 'batch_name', 'semester',
            'semester_label', 'section', 'section_name', 'effective_start_date',
            'effective_end_date', 'status', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        student = attrs.get('student')
        prog = attrs.get('program')
        batch = attrs.get('batch')
        sem = attrs.get('semester')
        section = attrs.get('section')

        if student:
            if student.role != RoleChoices.STUDENT:
                raise serializers.ValidationError({'student': 'Only members with Student role can have placements.'})
            if prog and student.institute_id != prog.institute_id:
                raise serializers.ValidationError({'program': 'Student and Program must belong to the same institute.'})
        if batch and prog and batch.program_id != prog.id:
            raise serializers.ValidationError({'batch': 'Batch must belong to the selected Program.'})
        if sem and prog and sem.program_id != prog.id:
            raise serializers.ValidationError({'semester': 'Semester must belong to the selected Program.'})
        if section and batch and section.batch_id != batch.id:
            raise serializers.ValidationError({'section': 'Section must belong to the selected Batch.'})
        return attrs


class StudentProgressionSerializer(serializers.Serializer):
    """
    Advances a student to a new semester/section.
    Preserves historical placement records by marking previous placement completed
    and creating a new active placement with effective dates.
    """
    next_semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.all())
    next_section = serializers.PrimaryKeyRelatedField(queryset=Section.objects.all(), required=False, allow_null=True)
    effective_start_date = serializers.DateField(required=False, default=timezone.localdate)

    def validate(self, attrs):
        placement = self.context['placement']
        next_sem = attrs['next_semester']
        next_sec = attrs.get('next_section')

        if next_sem.program_id != placement.program_id:
            raise serializers.ValidationError({'next_semester': 'Next semester must belong to the student’s program.'})
        if next_sem.semester_number <= placement.semester.semester_number:
            raise serializers.ValidationError({'next_semester': 'Next semester number must be greater than current semester.'})
        if next_sec and next_sec.batch_id != placement.batch_id:
            raise serializers.ValidationError({'next_section': 'Next section must belong to the student’s batch.'})
        return attrs

    def save(self):
        placement = self.context['placement']
        next_sem = self.validated_data['next_semester']
        next_sec = self.validated_data.get('next_section')
        start_date = self.validated_data.get('effective_start_date') or timezone.localdate()

        # 1. Close current placement record
        placement.status = PlacementStatus.COMPLETED
        placement.effective_end_date = start_date
        placement.save(update_fields=['status', 'effective_end_date', 'updated_at'])

        # 2. Create new active placement record
        new_placement = StudentAcademicPlacement.objects.create(
            student=placement.student,
            program=placement.program,
            batch=placement.batch,
            semester=next_sem,
            section=next_sec,
            effective_start_date=start_date,
            status=PlacementStatus.ACTIVE
        )
        return new_placement
