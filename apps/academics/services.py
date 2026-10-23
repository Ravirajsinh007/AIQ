from django.db import transaction
from django.utils import timezone

from apps.accounts.models import MembershipStatus, RoleChoices

from .models import (
    AcademicStatus,
    AssignmentStatus,
    Batch,
    Department,
    Program,
    StudentAcademicPlacement,
    StudentSubjectEnrollment,
    PlacementStatus,
    TeacherAssignment,
    UserInstituteMembership,
)


def system_program_for_department(department: Department) -> Program:
    program, _ = Program.objects.get_or_create(
        institute=department.institute,
        code=f'SYS-{department.code}'[:50],
        defaults={
            'department': department,
            'name': f'{department.name} course mapping',
            'qualification_type': '',
            'duration_years': None,
            'total_semesters': None,
            'is_department_mapping': True,
            'status': AcademicStatus.ACTIVE,
        },
    )
    if program.department_id != department.id or not program.is_department_mapping:
        raise ValueError('The department’s internal academic mapping is inconsistent.')
    return program


@transaction.atomic
def configure_student_courses(
    *,
    membership: UserInstituteMembership,
    department: Department,
    batch: Batch,
    subjects,
) -> StudentAcademicPlacement:
    if membership.role != RoleChoices.STUDENT:
        raise ValueError('Only student memberships can be assigned a course profile.')
    if membership.institute_id != department.institute_id or batch.institute_id != department.institute_id:
        raise ValueError('The student, department, and batch must belong to the same institute.')
    if batch.program.department_id != department.id:
        raise ValueError('The selected batch does not belong to the selected department.')
    subjects = list(subjects)
    if not subjects:
        raise ValueError('Select at least one subject for the student.')
    if any(
        subject.institute_id != department.institute_id or subject.department_id != department.id
        for subject in subjects
    ):
        raise ValueError('Every selected subject must belong to the student’s department and institute.')

    program = batch.program
    today = timezone.localdate()
    current = StudentAcademicPlacement.objects.filter(
        student=membership,
        status=PlacementStatus.ACTIVE,
        effective_end_date__isnull=True,
    ).order_by('-created_at').first()
    if current and current.batch_id == batch.id and current.program_id == program.id:
        placement = current
    else:
        if current:
            StudentSubjectEnrollment.objects.filter(
                student=membership,
                batch=current.batch,
                status=AcademicStatus.ACTIVE,
            ).update(status=AcademicStatus.INACTIVE)
            current.status = PlacementStatus.TRANSFERRED
            current.effective_end_date = today
            current.save(update_fields=['status', 'effective_end_date', 'updated_at'])
        placement = StudentAcademicPlacement.objects.create(
            student=membership,
            program=program,
            batch=batch,
            effective_start_date=today,
            status=PlacementStatus.ACTIVE,
        )

    selected_ids = {subject.id for subject in subjects}
    enrollments = StudentSubjectEnrollment.objects.filter(student=membership, batch=batch)
    enrollments.exclude(subject_id__in=selected_ids).filter(
        status=AcademicStatus.ACTIVE
    ).update(status=AcademicStatus.INACTIVE)
    for subject in subjects:
        StudentSubjectEnrollment.objects.update_or_create(
            student=membership,
            batch=batch,
            subject=subject,
            defaults={'status': AcademicStatus.ACTIVE},
        )
    return placement


@transaction.atomic
def sync_subject_teachers(*, subject, teachers):
    selected_ids = {teacher.id for teacher in teachers}
    assignments = TeacherAssignment.objects.filter(subject=subject, status=AssignmentStatus.ACTIVE)
    for assignment in assignments:
        if assignment.teacher_id not in selected_ids:
            assignment.status = AssignmentStatus.REVOKED
            assignment.save(update_fields=['status', 'updated_at'])

    for teacher in teachers:
        if (
            teacher.role != RoleChoices.TEACHER
            or teacher.status != MembershipStatus.ACTIVE
            or teacher.institute_id != subject.institute_id
        ):
            raise ValueError('Every assigned teacher must be active in the subject’s institute.')
        active = TeacherAssignment.objects.filter(
            teacher=teacher,
            subject=subject,
            status=AssignmentStatus.ACTIVE,
        ).first()
        if active is not None:
            continue
        revoked = TeacherAssignment.objects.filter(
            teacher=teacher,
            subject=subject,
            status=AssignmentStatus.REVOKED,
        ).first()
        if revoked:
            revoked.status = AssignmentStatus.ACTIVE
            revoked.save(update_fields=['status', 'updated_at'])
        else:
            TeacherAssignment.objects.create(
                teacher=teacher,
                subject=subject,
                status=AssignmentStatus.ACTIVE,
            )
