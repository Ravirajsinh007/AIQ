from datetime import date
from types import SimpleNamespace
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase
from apps.accounts.models import (
    User,
    Institute,
    UserInstituteMembership,
    RoleChoices,
    MembershipStatus,
)
from apps.academics.models import (
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
    SyllabusMapping,
    TeacherAssignment,
    StudentAcademicPlacement,
    StudentSubjectEnrollment,
    PlacementStatus,
)
from apps.exams.services import eligible_placements


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_HOST='smtp.example.test',
    DEFAULT_FROM_EMAIL='noreply@example.test',
)
class M2AcademicStructureTests(APITestCase):

    def setUp(self):
        # 1. Platform Admin
        self.platform_admin = User.objects.create_superuser(
            email='super@examcraft.org',
            password='AdminPassword123!'
        )

        # 2. Institutes: Alpha and Beta
        self.institute_alpha = Institute.objects.create(code='ALPHA', name='Alpha Engineering Institute')
        self.institute_beta = Institute.objects.create(code='BETA', name='Beta University')

        # 3. Alpha Admin
        self.alpha_admin = User.objects.create_user(
            email='admin@alpha.edu',
            password='Password123!',
            first_name='Alpha',
            last_name='Admin',
            is_verified=True
        )
        UserInstituteMembership.objects.create(
            user=self.alpha_admin,
            institute=self.institute_alpha,
            role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE
        )

        # 4. Beta Admin
        self.beta_admin = User.objects.create_user(
            email='admin@beta.edu',
            password='Password123!',
            first_name='Beta',
            last_name='Admin',
            is_verified=True
        )
        UserInstituteMembership.objects.create(
            user=self.beta_admin,
            institute=self.institute_beta,
            role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE
        )

        # 5. Teacher in Alpha
        self.teacher_alpha = User.objects.create_user(
            email='teacher@alpha.edu',
            password='Password123!',
            first_name='Grace',
            last_name='Hopper',
            is_verified=True
        )
        self.teacher_alpha_membership = UserInstituteMembership.objects.create(
            user=self.teacher_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.TEACHER,
            status=MembershipStatus.ACTIVE
        )

        # 6. Student in Alpha
        self.student_alpha = User.objects.create_user(
            email='student@alpha.edu',
            password='Password123!',
            first_name='Ada',
            last_name='Lovelace',
            is_verified=True
        )
        self.student_alpha_membership = UserInstituteMembership.objects.create(
            user=self.student_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.STUDENT,
            identifier='ROLL001',
            status=MembershipStatus.ACTIVE
        )

        # 7. Base Academic Structure for Alpha
        self.dept_cs = Department.objects.create(
            institute=self.institute_alpha,
            code='CSE',
            name='Computer Science and Engineering'
        )
        self.prog_btech = Program.objects.create(
            institute=self.institute_alpha,
            department=self.dept_cs,
            code='BTECH-CSE',
            name='Bachelor of Technology in Computer Science',
            duration_years=4,
            total_semesters=8
        )
        self.ay_2025 = AcademicYear.objects.create(
            institute=self.institute_alpha,
            label='2025-2026',
            start_date=date(2025, 8, 1),
            end_date=date(2026, 5, 31),
            is_current=True
        )
        self.sem1 = Semester.objects.create(program=self.prog_btech, semester_number=1, label='Semester 1')
        self.sem2 = Semester.objects.create(program=self.prog_btech, semester_number=2, label='Semester 2')
        self.batch_2025 = Batch.objects.create(
            institute=self.institute_alpha,
            program=self.prog_btech,
            name='Batch 2025-2029',
            admission_year=2025
        )
        self.sec_a = Section.objects.create(batch=self.batch_2025, name='Section A')
        self.subj_dsa = Subject.objects.create(
            institute=self.institute_alpha,
            department=self.dept_cs,
            code='CS101',
            name='Data Structures and Algorithms',
            credit_hours=4.0
        )

    # --------------------------------------------------------------------------
    # Model Constraints & Integrity Tests
    # --------------------------------------------------------------------------

    def test_duplicate_department_code_in_same_institute_fails(self):
        with self.assertRaises(Exception):
            Department.objects.create(
                institute=self.institute_alpha,
                code='CSE',  # Already exists in Alpha
                name='Duplicate CSE'
            )

    def test_same_department_code_in_different_institute_succeeds(self):
        dept_beta = Department.objects.create(
            institute=self.institute_beta,
            code='CSE',  # Same code in Beta is allowed
            name='Computer Science at Beta'
        )
        self.assertEqual(dept_beta.code, 'CSE')
        self.assertEqual(dept_beta.institute, self.institute_beta)

    def test_cross_institute_program_department_relationship_fails(self):
        dept_beta = Department.objects.create(
            institute=self.institute_beta,
            code='IT',
            name='Information Technology'
        )
        prog = Program(
            institute=self.institute_alpha,
            department=dept_beta,  # Belongs to Beta!
            code='CROSS-PROG',
            name='Cross Program'
        )
        with self.assertRaises(ValidationError):
            prog.clean()

    def test_academic_year_date_validation(self):
        ay = AcademicYear(
            institute=self.institute_alpha,
            label='2027-2026',
            start_date=date(2027, 8, 1),
            end_date=date(2026, 5, 31)  # End date before start date!
        )
        with self.assertRaises(ValidationError):
            ay.clean()

    # --------------------------------------------------------------------------
    # Curriculum, Units, Topics & Outcomes Tests
    # --------------------------------------------------------------------------

    def test_units_topics_outcomes_and_syllabus_mappings(self):
        unit1 = Unit.objects.create(
            subject=self.subj_dsa,
            unit_number=1,
            title='Arrays and Linked Lists'
        )
        topic1 = Topic.objects.create(
            unit=unit1,
            title='Singly Linked Lists',
            order=1
        )
        outcome1 = LearningOutcome.objects.create(
            subject=self.subj_dsa,
            code='CO1',
            description='Analyze time and space complexity of fundamental data structures.',
            category='cognitive'
        )
        mapping = SyllabusMapping.objects.create(
            subject=self.subj_dsa,
            topic=topic1,
            academic_year=self.ay_2025,
            syllabus_reference='Textbook Chapter 3, Section 3.1-3.4'
        )
        self.assertEqual(unit1.unit_number, 1)
        self.assertEqual(topic1.unit, unit1)
        self.assertEqual(outcome1.code, 'CO1')
        self.assertEqual(mapping.subject, self.subj_dsa)

    def test_cross_institute_syllabus_mapping_rejected(self):
        ay_beta = AcademicYear.objects.create(
            institute=self.institute_beta,
            label='2025-2026',
            start_date=date(2025, 8, 1),
            end_date=date(2026, 5, 31)
        )
        mapping = SyllabusMapping(
            subject=self.subj_dsa,  # Alpha
            academic_year=ay_beta,   # Beta
            syllabus_reference='Ref'
        )
        with self.assertRaises(ValidationError):
            mapping.clean()

    # --------------------------------------------------------------------------
    # Teacher Assignment Tests
    # --------------------------------------------------------------------------

    def test_teacher_assignment_creation(self):
        assignment = TeacherAssignment.objects.create(
            teacher=self.teacher_alpha_membership,
            subject=self.subj_dsa,
            academic_year=self.ay_2025,
            batch=self.batch_2025,
            section=self.sec_a,
            status='active'
        )
        self.assertEqual(assignment.teacher, self.teacher_alpha_membership)
        self.assertEqual(assignment.subject, self.subj_dsa)

    def test_teacher_assignment_rejects_student_membership(self):
        assignment = TeacherAssignment(
            teacher=self.student_alpha_membership,  # Student, not teacher!
            subject=self.subj_dsa,
            academic_year=self.ay_2025
        )
        with self.assertRaises(ValidationError):
            assignment.clean()

    def test_teacher_assignment_rejects_cross_institute_subject(self):
        subj_beta = Subject.objects.create(
            institute=self.institute_beta,
            code='BETA101',
            name='Beta Physics'
        )
        assignment = TeacherAssignment(
            teacher=self.teacher_alpha_membership,  # Alpha
            subject=subj_beta,                      # Beta!
            academic_year=self.ay_2025
        )
        with self.assertRaises(ValidationError):
            assignment.clean()

    # --------------------------------------------------------------------------
    # Multi-Tenant REST API & IDOR Isolation Tests
    # --------------------------------------------------------------------------

    def test_alpha_admin_can_create_department_in_alpha(self):
        self.client.force_authenticate(user=self.alpha_admin)
        url = reverse('department-list')
        response = self.client.post(url, {
            'institute': str(self.institute_alpha.id),
            'code': 'MECH',
            'name': 'Mechanical Engineering'
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['code'], 'MECH')

    def test_alpha_admin_cannot_access_or_create_in_beta(self):
        """
        Alpha admin attempts to create a department inside Beta Institute (IDOR).
        Must be strictly rejected with HTTP 403 Forbidden.
        """
        self.client.force_authenticate(user=self.alpha_admin)
        url = reverse('department-list')
        response = self.client.post(url, {
            'institute': str(self.institute_beta.id),
            'code': 'CIVIL',
            'name': 'Civil Engineering'
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_alpha_admin_cannot_create_section_using_beta_batch(self):
        department = Department.objects.create(
            institute=self.institute_beta,
            code='BIO',
            name='Biology',
        )
        program = Program.objects.create(
            institute=self.institute_beta,
            department=department,
            code='BSC-BIO',
            name='Biology',
            duration_years=3,
            total_semesters=6,
        )
        batch = Batch.objects.create(
            institute=self.institute_beta,
            program=program,
            name='Beta 2025',
            admission_year=2025,
        )
        self.client.force_authenticate(user=self.alpha_admin)
        response = self.client.post(reverse('section-list'), {
            'batch': str(batch.id),
            'name': 'Cross-tenant section',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Section.objects.filter(name='Cross-tenant section').exists())

    def test_department_list_is_scoped_to_active_admin_memberships(self):
        Department.objects.create(
            institute=self.institute_beta,
            code='BIO',
            name='Biology',
        )
        self.client.force_authenticate(user=self.alpha_admin)
        response = self.client.get(reverse('department-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {row['code'] for row in response.data['results']},
            {'CSE'},
        )

    def test_institute_admin_dashboard_returns_only_authorized_institute(self):
        self.client.force_authenticate(user=self.alpha_admin)
        response = self.client.get(
            reverse('institute-admin-dashboard'),
            {'institute': str(self.institute_alpha.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['institute']['id'], str(self.institute_alpha.id))
        self.assertEqual(response.data['metrics']['departments'], 1)
        self.assertEqual(response.data['metrics']['students'], 1)
        self.assertEqual(response.data['metrics']['teachers'], 1)
        self.assertEqual(
            response.data['metrics']['batches'],
            Batch.objects.filter(institute=self.institute_alpha).count(),
        )

    def test_batch_can_be_created_from_department_without_exposing_program_setup(self):
        self.client.force_authenticate(user=self.alpha_admin)
        response = self.client.post(reverse('batch-list'), {
            'institute': str(self.institute_alpha.id),
            'department': str(self.dept_cs.id),
            'name': 'CSE 2026',
            'admission_year': 2026,
            'status': 'active',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        batch = Batch.objects.get(id=response.data['id'])
        self.assertEqual(batch.program.department_id, self.dept_cs.id)
        self.assertTrue(batch.program.is_department_mapping)
        self.assertEqual(batch.program.qualification_type, '')
        self.assertIsNone(batch.program.duration_years)
        self.assertIsNone(batch.program.total_semesters)
        self.assertEqual(str(response.data['department']), str(self.dept_cs.id))
        self.assertEqual(response.data['department_name'], self.dept_cs.name)

    def test_batch_create_rejects_department_from_another_institute(self):
        beta_department = Department.objects.create(
            institute=self.institute_beta,
            code='BIO',
            name='Biology',
        )
        self.client.force_authenticate(user=self.alpha_admin)
        response = self.client.post(reverse('batch-list'), {
            'institute': str(self.institute_alpha.id),
            'department': str(beta_department.id),
            'name': 'Invalid batch',
            'admission_year': 2026,
        })
        self.assertNotEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(Batch.objects.filter(name='Invalid batch').exists())

    def test_student_creation_assigns_department_batch_and_subjects(self):
        self.client.force_authenticate(user=self.alpha_admin)
        response = self.client.post(
            reverse('institute-members-list-create', kwargs={'institute_id': self.institute_alpha.id}),
            {
                'email': 'newstudent@alpha.edu',
                'first_name': 'New',
                'last_name': 'Student',
                'role': RoleChoices.STUDENT,
                'identifier': 'roll-2026-01',
                'department': str(self.dept_cs.id),
                'batch': str(self.batch_2025.id),
                'subject_ids': [str(self.subj_dsa.id)],
                'initial_password': 'StudentCreation!42',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        membership = UserInstituteMembership.objects.get(user__email='newstudent@alpha.edu')
        placement = StudentAcademicPlacement.objects.get(student=membership, status=PlacementStatus.ACTIVE)
        enrollment = StudentSubjectEnrollment.objects.get(
            student=membership,
            batch=self.batch_2025,
            subject=self.subj_dsa,
            status=AcademicStatus.ACTIVE,
        )
        self.assertEqual(membership.identifier, 'ROLL-2026-01')
        self.assertEqual(placement.program_id, self.batch_2025.program_id)
        self.assertIsNone(placement.semester_id)
        self.assertEqual(enrollment.subject_id, self.subj_dsa.id)
        self.assertEqual(response.data['department_name'], self.dept_cs.name)
        self.assertEqual(response.data['batch_name'], self.batch_2025.name)
        self.assertEqual(response.data['enrolled_subject_codes'], [self.subj_dsa.code])
        self.assertFalse(ProgramSemesterSubject.objects.filter(
            program=self.batch_2025.program,
            subject=self.subj_dsa,
        ).exists())

    def test_student_creation_rejects_cross_institute_subjects(self):
        beta_department = Department.objects.create(
            institute=self.institute_beta,
            code='BIO',
            name='Biology',
        )
        beta_subject = Subject.objects.create(
            institute=self.institute_beta,
            department=beta_department,
            code='BIO101',
            name='Biology',
        )
        self.client.force_authenticate(user=self.alpha_admin)
        response = self.client.post(
            reverse('institute-members-list-create', kwargs={'institute_id': self.institute_alpha.id}),
            {
                'email': 'crossinstitute@alpha.edu',
                'first_name': 'Cross',
                'last_name': 'Institute',
                'role': RoleChoices.STUDENT,
                'identifier': 'ROLL-CROSS',
                'department': str(self.dept_cs.id),
                'batch': str(self.batch_2025.id),
                'subject_ids': [str(beta_subject.id)],
                'initial_password': 'CrossInstitute!42',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(UserInstituteMembership.objects.filter(user__email='crossinstitute@alpha.edu').exists())

    def test_student_membership_update_changes_subject_enrollment(self):
        self.client.force_authenticate(user=self.alpha_admin)
        create_response = self.client.post(
            reverse('institute-members-list-create', kwargs={'institute_id': self.institute_alpha.id}),
            {
                'email': 'editable@alpha.edu',
                'first_name': 'Editable',
                'last_name': 'Student',
                'role': RoleChoices.STUDENT,
                'identifier': 'ROLL-EDIT',
                'department': str(self.dept_cs.id),
                'batch': str(self.batch_2025.id),
                'subject_ids': [str(self.subj_dsa.id)],
                'initial_password': 'EditableStudent!42',
            },
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED, create_response.data)
        membership = UserInstituteMembership.objects.get(user__email='editable@alpha.edu')
        second_subject = Subject.objects.create(
            institute=self.institute_alpha,
            department=self.dept_cs,
            code='CS102',
            name='Algorithms',
        )
        update_response = self.client.patch(
            reverse('institute-member-detail', kwargs={
                'institute_id': self.institute_alpha.id,
                'membership_id': membership.id,
            }),
            {
                'identifier': 'ROLL-EDIT-2',
                'department': str(self.dept_cs.id),
                'batch': str(self.batch_2025.id),
                'subject_ids': [str(second_subject.id)],
            },
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK, update_response.data)
        self.assertEqual(update_response.data['enrolled_subject_codes'], [second_subject.code])
        self.assertTrue(StudentSubjectEnrollment.objects.filter(
            student=membership,
            subject=self.subj_dsa,
            status=AcademicStatus.INACTIVE,
        ).exists())
        self.assertTrue(StudentSubjectEnrollment.objects.filter(
            student=membership,
            subject=second_subject,
            status=AcademicStatus.ACTIVE,
        ).exists())

    def test_exam_eligibility_uses_explicit_enrollment_and_legacy_fallback(self):
        placement = StudentAcademicPlacement.objects.create(
            student=self.student_alpha_membership,
            program=self.prog_btech,
            batch=self.batch_2025,
            semester=self.sem1,
            section=self.sec_a,
        )
        ProgramSemesterSubject.objects.create(
            program=self.prog_btech,
            semester=self.sem1,
            subject=self.subj_dsa,
        )
        exam = SimpleNamespace(
            institute_id=self.institute_alpha.id,
            batch_id=self.batch_2025.id,
            section_id=self.sec_a.id,
            paper=SimpleNamespace(
                subject_id=self.subj_dsa.id,
                blueprint=SimpleNamespace(
                    program_id=self.prog_btech.id,
                    semester_id=self.sem1.id,
                ),
            ),
        )
        self.assertTrue(eligible_placements(exam, self.student_alpha).filter(pk=placement.pk).exists())
        enrollment = StudentSubjectEnrollment.objects.create(
            student=self.student_alpha_membership,
            batch=self.batch_2025,
            subject=self.subj_dsa,
            status=AcademicStatus.INACTIVE,
        )
        self.assertFalse(eligible_placements(exam, self.student_alpha).filter(pk=placement.pk).exists())
        enrollment.status = AcademicStatus.ACTIVE
        enrollment.save(update_fields=['status'])
        self.assertTrue(eligible_placements(exam, self.student_alpha).filter(pk=placement.pk).exists())

        other_program = Program.objects.create(
            institute=self.institute_alpha,
            department=self.dept_cs,
            code='MISMATCH',
            name='Unrelated Program',
            duration_years=3,
            total_semesters=6,
        )
        other_semester = Semester.objects.create(
            program=other_program,
            semester_number=2,
            label='Unrelated Semester',
        )
        exam.paper.blueprint = SimpleNamespace(
            program_id=other_program.id,
            semester_id=other_semester.id,
        )
        self.assertTrue(
            eligible_placements(exam, self.student_alpha).filter(pk=placement.pk).exists(),
            'An explicit subject enrollment must not be blocked by legacy program/semester filters.',
        )

        enrollment.delete()
        self.assertFalse(
            eligible_placements(exam, self.student_alpha).filter(pk=placement.pk).exists(),
            'Legacy curriculum access must still match the blueprint program and semester.',
        )

    def test_student_course_list_returns_active_subject_enrollments(self):
        placement = StudentAcademicPlacement.objects.create(
            student=self.student_alpha_membership,
            program=self.prog_btech,
            batch=self.batch_2025,
            semester=None,
        )
        other_subject = Subject.objects.create(
            institute=self.institute_alpha,
            department=self.dept_cs,
            code='CS102',
            name='Algorithms',
        )
        StudentSubjectEnrollment.objects.create(
            student=self.student_alpha_membership,
            batch=self.batch_2025,
            subject=self.subj_dsa,
            status=AcademicStatus.ACTIVE,
        )
        StudentSubjectEnrollment.objects.create(
            student=self.student_alpha_membership,
            batch=self.batch_2025,
            subject=other_subject,
            status=AcademicStatus.INACTIVE,
        )
        self.client.force_authenticate(user=self.student_alpha)

        response = self.client.get(reverse('student-placement-list'), {'status': 'active'})

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['results'][0]['id'], str(placement.id))
        self.assertEqual(response.data['results'][0]['department_name'], self.dept_cs.name)
        self.assertEqual(response.data['results'][0]['enrolled_subject_codes'], [self.subj_dsa.code])
        self.assertIsNone(response.data['results'][0]['semester_label'])

    def test_subject_creation_assigns_teacher_without_academic_year_input(self):
        self.client.force_authenticate(user=self.alpha_admin)
        response = self.client.post(reverse('subject-list'), {
            'institute': str(self.institute_alpha.id),
            'department': str(self.dept_cs.id),
            'code': 'CS205',
            'name': 'Algorithms',
            'credit_hours': '3.0',
            'teacher_ids': [str(self.teacher_alpha_membership.id)],
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        subject = Subject.objects.get(id=response.data['id'])
        assignment = TeacherAssignment.objects.get(
            teacher=self.teacher_alpha_membership,
            subject=subject,
            status='active',
        )
        self.assertIsNone(assignment.academic_year_id)
        self.assertEqual(
            [str(value) for value in response.data['assigned_teacher_ids']],
            [str(self.teacher_alpha_membership.id)],
        )

    def test_subject_assignment_rejects_teacher_from_another_institute(self):
        beta_teacher = User.objects.create_user(
            email='teacher@beta.edu',
            password='Password123!',
            first_name='Beta',
            last_name='Teacher',
        )
        beta_membership = UserInstituteMembership.objects.create(
            user=beta_teacher,
            institute=self.institute_beta,
            role=RoleChoices.TEACHER,
            status=MembershipStatus.ACTIVE,
        )
        self.client.force_authenticate(user=self.alpha_admin)
        response = self.client.post(reverse('subject-list'), {
            'institute': str(self.institute_alpha.id),
            'department': str(self.dept_cs.id),
            'code': 'CS206',
            'name': 'Data Science',
            'credit_hours': '3.0',
            'teacher_ids': [str(beta_membership.id)],
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(Subject.objects.filter(code='CS206').exists())

    def test_institute_admin_dashboard_rejects_another_institute(self):
        self.client.force_authenticate(user=self.alpha_admin)
        response = self.client.get(
            reverse('institute-admin-dashboard'),
            {'institute': str(self.institute_beta.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_institute_admin_dashboard_returns_real_zero_counts_for_empty_institute(self):
        self.client.force_authenticate(user=self.beta_admin)
        response = self.client.get(
            reverse('institute-admin-dashboard'),
            {'institute': str(self.institute_beta.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['metrics']['departments'], 0)
        self.assertEqual(response.data['metrics']['students'], 0)
        self.assertEqual(response.data['upcoming_exams'], [])
        self.assertEqual(response.data['recent_activity'], [])

    def test_institute_admin_can_update_only_institute_contact_fields(self):
        self.client.force_authenticate(user=self.alpha_admin)
        response = self.client.patch(
            reverse('institute-detail', kwargs={'institute_id': self.institute_alpha.id}),
            {
                'contact_email': 'office@alpha.edu',
                'contact_phone': '+1 555 0100',
                'address': 'Updated campus address',
                'name': 'Unauthorized rename',
                'status': 'suspended',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.institute_alpha.refresh_from_db()
        self.assertEqual(self.institute_alpha.contact_email, 'office@alpha.edu')
        self.assertEqual(self.institute_alpha.contact_phone, '+1 555 0100')
        self.assertEqual(self.institute_alpha.address, 'Updated campus address')
        self.assertEqual(self.institute_alpha.name, 'Alpha Engineering Institute')
        self.assertEqual(self.institute_alpha.status, 'active')

    def test_teacher_cannot_create_subjects(self):
        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('subject-list')
        response = self.client.post(url, {
            'institute': str(self.institute_alpha.id),
            'code': 'CS201',
            'name': 'Operating Systems'
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_teacher_can_view_assigned_subjects(self):
        TeacherAssignment.objects.create(
            teacher=self.teacher_alpha_membership,
            subject=self.subj_dsa,
            academic_year=self.ay_2025
        )
        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('teacher-assignment-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['subject_code'], 'CS101')

    def test_teacher_can_read_academic_structure_in_an_active_member_institute(self):
        self.client.force_authenticate(user=self.teacher_alpha)
        response = self.client.get(reverse('department-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row['code'] for row in response.data['results']], ['CSE'])

    # --------------------------------------------------------------------------
    # Student Academic Placement & Historical Progression Tests
    # --------------------------------------------------------------------------

    def test_student_academic_placement_and_progression_history_preserved(self):
        # 1. Create initial Term 1 placement
        placement_sem1 = StudentAcademicPlacement.objects.create(
            student=self.student_alpha_membership,
            program=self.prog_btech,
            batch=self.batch_2025,
            semester=self.sem1,
            section=self.sec_a,
            status=PlacementStatus.ACTIVE
        )
        self.assertEqual(placement_sem1.status, PlacementStatus.ACTIVE)

        # 2. Progress student to Semester 2 via API
        self.client.force_authenticate(user=self.alpha_admin)
        progress_url = reverse('student-placement-progress', kwargs={'placement_id': placement_sem1.id})
        response = self.client.post(progress_url, {
            'next_semester': str(self.sem2.id),
            'next_section': str(self.sec_a.id)
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['semester_label'], 'Semester 2')
        self.assertEqual(response.data['status'], PlacementStatus.ACTIVE)

        # 3. Verify prior placement record is COMPLETED and NOT deleted/overwritten!
        placement_sem1.refresh_from_db()
        self.assertEqual(placement_sem1.status, PlacementStatus.COMPLETED)
        self.assertIsNotNone(placement_sem1.effective_end_date)

        # 4. Total placements for this student is now 2 (full history retained)
        total_placements = StudentAcademicPlacement.objects.filter(student=self.student_alpha_membership).count()
        self.assertEqual(total_placements, 2)
