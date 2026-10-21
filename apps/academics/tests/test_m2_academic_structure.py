from datetime import date
from django.urls import reverse
from django.core.exceptions import ValidationError
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
    PlacementStatus,
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
