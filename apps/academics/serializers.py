from rest_framework import serializers
from django.utils import timezone
from apps.accounts.models import RoleChoices, MembershipStatus, UserInstituteMembership
from .services import sync_subject_teachers, system_program_for_department
from .models import (
    AcademicStatus,
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


class BatchDepartmentField(serializers.PrimaryKeyRelatedField):
    def get_attribute(self, instance):
        return instance.program.department


class DepartmentSerializer(serializers.ModelSerializer):
    institute_code = serializers.CharField(source='institute.code', read_only=True)

    class Meta:
        model = Department
        fields = ['id', 'institute', 'institute_code', 'code', 'name', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_code(self, value):
        return value.strip().upper()

    def validate(self, attrs):
        institute = attrs.get('institute', getattr(self.instance, 'institute', None))
        if institute:
            validate_mapping_write_institute(self, institute.id)
        return attrs


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
        dept = attrs.get('department', getattr(self.instance, 'department', None))
        inst = attrs.get('institute', getattr(self.instance, 'institute', None))
        if inst:
            validate_mapping_write_institute(self, inst.id)
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
        institute = attrs.get('institute', getattr(self.instance, 'institute', None))
        start = attrs.get('start_date', getattr(self.instance, 'start_date', None))
        end = attrs.get('end_date', getattr(self.instance, 'end_date', None))
        if institute:
            validate_mapping_write_institute(self, institute.id)
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
        prog = attrs.get('program', getattr(self.instance, 'program', None))
        sem_num = attrs.get('semester_number', getattr(self.instance, 'semester_number', None))
        if prog:
            validate_mapping_write_institute(self, prog.institute_id)
        if (
            prog
            and sem_num
            and prog.total_semesters is not None
            and sem_num > prog.total_semesters
        ):
            raise serializers.ValidationError({
                'semester_number': f"Semester number cannot exceed program's total semesters ({prog.total_semesters})."
            })
        return attrs


class BatchSerializer(serializers.ModelSerializer):
    program_code = serializers.CharField(source='program.code', read_only=True)
    institute_code = serializers.CharField(source='institute.code', read_only=True)
    department = BatchDepartmentField(
        queryset=Department.objects.all(),
        required=False,
    )
    department_name = serializers.CharField(source='program.department.name', read_only=True)
    program = serializers.PrimaryKeyRelatedField(
        queryset=Program.objects.all(),
        required=False,
    )

    class Meta:
        model = Batch
        fields = [
            'id', 'institute', 'institute_code', 'program', 'program_code',
            'department', 'department_name', 'name', 'admission_year', 'status',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        validators = []

    def validate(self, attrs):
        department = attrs.get('department')
        prog = attrs.get('program', getattr(self.instance, 'program', None))
        inst = attrs.get('institute', getattr(self.instance, 'institute', None))
        if department:
            validate_mapping_write_institute(self, department.institute_id)
            if inst and department.institute_id != inst.id:
                raise serializers.ValidationError({
                    'department': 'Department must belong to the selected institute.'
                })
            if prog and prog.department_id != department.id:
                raise serializers.ValidationError({
                    'program': 'Program must belong to the selected department.'
                })
            attrs['_department'] = department
        elif prog:
            attrs['_department'] = prog.department
        elif self.instance:
            attrs['_department'] = self.instance.program.department
        else:
            raise serializers.ValidationError({
                'department': 'Select the department for this batch.'
            })
        if inst:
            validate_mapping_write_institute(self, inst.id)
        if prog and inst and prog.institute_id != inst.id:
            raise serializers.ValidationError({'program': 'Program must belong to the selected institute.'})
        name = attrs.get('name', getattr(self.instance, 'name', ''))
        uniqueness_program = prog
        if uniqueness_program is None and department:
            uniqueness_program = Program.objects.filter(
                institute=department.institute,
                code=f"SYS-{department.code}"[:50],
            ).first()
        if name and uniqueness_program:
            existing = Batch.objects.filter(program=uniqueness_program, name=name)
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError({
                    'name': 'A batch with this name already exists in the selected department.'
                })
        return attrs

    def create(self, validated_data):
        department = validated_data.pop('_department')
        validated_data.pop('department', None)
        program = validated_data.get('program')
        if program is None:
            validated_data['program'] = system_program_for_department(department)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        department = validated_data.pop('_department', None)
        validated_data.pop('department', None)
        if department is not None and 'program' not in validated_data:
            validated_data['program'] = system_program_for_department(department)
        return super().update(instance, validated_data)


class SectionSerializer(serializers.ModelSerializer):
    batch_name = serializers.CharField(source='batch.name', read_only=True)

    class Meta:
        model = Section
        fields = ['id', 'batch', 'batch_name', 'name', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        batch = attrs.get('batch', getattr(self.instance, 'batch', None))
        if batch:
            validate_mapping_write_institute(self, batch.institute_id)
        return attrs


class SubjectSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True)
    institute_code = serializers.CharField(source='institute.code', read_only=True)
    teacher_ids = serializers.PrimaryKeyRelatedField(
        queryset=UserInstituteMembership.objects.filter(
            role=RoleChoices.TEACHER,
            status=MembershipStatus.ACTIVE,
        ),
        many=True,
        required=False,
        write_only=True,
    )
    assigned_teacher_ids = serializers.SerializerMethodField()
    assigned_teacher_names = serializers.SerializerMethodField()

    class Meta:
        model = Subject
        fields = [
            'id', 'institute', 'institute_code', 'department', 'department_name',
            'code', 'name', 'description', 'credit_hours', 'status', 'created_at', 'updated_at',
            'teacher_ids', 'assigned_teacher_ids', 'assigned_teacher_names',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_assigned_teacher_ids(self, subject):
        return list(
            subject.teacher_assignments.filter(status='active')
            .values_list('teacher_id', flat=True)
            .distinct()
        )

    def get_assigned_teacher_names(self, subject):
        memberships = subject.teacher_assignments.filter(
            status='active'
        ).select_related('teacher__user')
        return list(dict.fromkeys(assignment.teacher.user.full_name for assignment in memberships))

    def validate(self, attrs):
        dept = attrs.get('department', getattr(self.instance, 'department', None))
        inst = attrs.get('institute', getattr(self.instance, 'institute', None))
        if inst:
            validate_mapping_write_institute(self, inst.id)
        if dept and inst and dept.institute_id != inst.id:
            raise serializers.ValidationError({'department': 'Department must belong to the selected institute.'})
        teachers = attrs.get('teacher_ids', [])
        target_institute = inst or (dept.institute if dept else getattr(self.instance, 'institute', None))
        if target_institute and any(
            teacher.institute_id != target_institute.id for teacher in teachers
        ):
            raise serializers.ValidationError({
                'teacher_ids': 'Every assigned teacher must have an active Teacher membership in this institute.'
            })
        return attrs

    def create(self, validated_data):
        teachers = validated_data.pop('teacher_ids', None)
        subject = super().create(validated_data)
        if teachers is not None:
            sync_subject_teachers(subject=subject, teachers=teachers)
        return subject

    def update(self, instance, validated_data):
        teachers = validated_data.pop('teacher_ids', None)
        subject = super().update(instance, validated_data)
        if teachers is not None:
            sync_subject_teachers(subject=subject, teachers=teachers)
        return subject


class ProgramSemesterSubjectSerializer(serializers.ModelSerializer):
    program_code = serializers.CharField(source='program.code', read_only=True)
    semester_label = serializers.CharField(source='semester.label', read_only=True, allow_null=True)
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
        prog = attrs.get('program', getattr(self.instance, 'program', None))
        sem = attrs.get('semester', getattr(self.instance, 'semester', None))
        subj = attrs.get('subject', getattr(self.instance, 'subject', None))

        if prog:
            validate_mapping_write_institute(self, prog.institute_id)
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

    def validate(self, attrs):
        subject = attrs.get('subject', getattr(self.instance, 'subject', None))
        if subject:
            validate_mapping_write_institute(self, subject.institute_id)
        return attrs


class TopicSerializer(serializers.ModelSerializer):
    unit_title = serializers.CharField(source='unit.title', read_only=True)
    subject_code = serializers.CharField(source='unit.subject.code', read_only=True)

    class Meta:
        model = Topic
        fields = ['id', 'unit', 'unit_title', 'subject_code', 'title', 'description', 'order', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        unit = attrs.get('unit', getattr(self.instance, 'unit', None))
        if unit:
            validate_mapping_write_institute(self, unit.subject.institute_id)
        return attrs


class LearningOutcomeSerializer(serializers.ModelSerializer):
    subject_code = serializers.CharField(source='subject.code', read_only=True)

    class Meta:
        model = LearningOutcome
        fields = ['id', 'subject', 'subject_code', 'code', 'description', 'category', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        subject = attrs.get('subject', getattr(self.instance, 'subject', None))
        if subject:
            validate_mapping_write_institute(self, subject.institute_id)
        return attrs


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
        subj = attrs.get('subject', getattr(self.instance, 'subject', None))
        ay = attrs.get('academic_year', getattr(self.instance, 'academic_year', None))
        topic = attrs.get('topic', getattr(self.instance, 'topic', None))

        if subj:
            validate_mapping_write_institute(self, subj.institute_id)
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
    academic_year_label = serializers.CharField(
        source='academic_year.label',
        read_only=True,
        allow_null=True,
    )
    batch_name = serializers.CharField(source='batch.name', read_only=True, allow_null=True)
    section_name = serializers.CharField(source='section.name', read_only=True, allow_null=True)

    class Meta:
        model = TeacherAssignment
        fields = [
            'id', 'teacher', 'teacher_name', 'teacher_email', 'subject',
            'subject_code', 'subject_name', 'academic_year', 'academic_year_label',
            'batch', 'batch_name', 'section', 'section_name', 'status', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        teacher = attrs.get('teacher', getattr(self.instance, 'teacher', None))
        subj = attrs.get('subject', getattr(self.instance, 'subject', None))
        ay = attrs.get('academic_year', getattr(self.instance, 'academic_year', None))
        batch = attrs.get('batch', getattr(self.instance, 'batch', None))
        section = attrs.get('section', getattr(self.instance, 'section', None))

        if teacher:
            validate_mapping_write_institute(self, teacher.institute_id)
            if teacher.role not in [RoleChoices.TEACHER, RoleChoices.EXAM_STAFF]:
                raise serializers.ValidationError({'teacher': 'Assigned member must have Teacher or Exam Staff role.'})
            if teacher.status != MembershipStatus.ACTIVE:
                raise serializers.ValidationError({'teacher': 'Assigned member must have an active institute membership.'})
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
    department_name = serializers.CharField(source='program.department.name', read_only=True)
    batch_name = serializers.CharField(source='batch.name', read_only=True)
    semester_label = serializers.CharField(source='semester.label', read_only=True, allow_null=True)
    section_name = serializers.CharField(source='section.name', read_only=True)
    enrolled_subject_codes = serializers.SerializerMethodField()

    class Meta:
        model = StudentAcademicPlacement
        fields = [
            'id', 'student', 'student_name', 'student_email', 'student_identifier',
            'program', 'program_code', 'department_name', 'batch', 'batch_name',
            'enrolled_subject_codes', 'semester', 'semester_label', 'section',
            'section_name', 'effective_start_date',
            'effective_end_date', 'status', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_enrolled_subject_codes(self, obj):
        return list(
            obj.student.subject_enrollments.filter(
                batch=obj.batch,
                status=AcademicStatus.ACTIVE,
            ).values_list('subject__code', flat=True)
        )

    def validate(self, attrs):
        student = attrs.get('student', getattr(self.instance, 'student', None))
        prog = attrs.get('program', getattr(self.instance, 'program', None))
        batch = attrs.get('batch', getattr(self.instance, 'batch', None))
        sem = attrs.get('semester', getattr(self.instance, 'semester', None))
        section = attrs.get('section', getattr(self.instance, 'section', None))

        if student:
            validate_mapping_write_institute(self, student.institute_id)
            if student.role != RoleChoices.STUDENT:
                raise serializers.ValidationError({'student': 'Only members with Student role can have placements.'})
            if student.status != MembershipStatus.ACTIVE:
                raise serializers.ValidationError({'student': 'Student must have an active institute membership.'})
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
