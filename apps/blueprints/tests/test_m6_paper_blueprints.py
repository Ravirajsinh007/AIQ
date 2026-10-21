import random
from decimal import Decimal
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import (
    User,
    Institute,
    RoleChoices,
    UserInstituteMembership,
    MembershipStatus,
)
from apps.academics.models import (
    Department,
    Program,
    AcademicYear,
    Semester,
    Subject,
    Unit,
    Topic,
    LearningOutcome,
    TeacherAssignment,
    AssignmentStatus,
)
from apps.questions.models import (
    Question,
    QuestionOption,
    AnswerKey,
    QuestionRubric,
    QuestionSourceReference,
    QuestionType,
    QuestionStatus,
    DifficultyLevel,
    BloomTaxonomy,
    QuestionOrigin,
)
from apps.blueprints.models import (
    PaperBlueprint,
    BlueprintSection,
    BlueprintRule,
    GeneratedPaper,
    GeneratedPaperQuestion,
    BlueprintStatus,
    GeneratedPaperStatus,
)


@pytest.mark.django_db
class M6BlueprintPaperGenerationTests(APITestCase):
    """
    Test suite for Module M6: Blueprint Paper Generation.
    Validates:
    - Blueprint creation, editing, and listing with institute isolation.
    - Role permissions and teacher teaching-assignment enforcement.
    - Contradictory rules and section/paper mark reconciliation.
    - Question availability and shortage reporting.
    - Selection of approved questions only (excluding draft, under-review, rejected, archived).
    - Preservation of constraints (types, marks, difficulty, Bloom levels, units).
    - Prevention of duplicate questions within a paper.
    - Immutable question snapshots in GeneratedPaperQuestion.
    - Regeneration with version incrementing (v1, v2) without overwriting.
    - Atomic transaction rollback on persistence failure.
    - Blocking student access to blueprint and generation APIs.
    """

    def setUp(self):
        # 1. Institutes
        self.institute_alpha = Institute.objects.create(code='INST-ALPHA', name='Alpha Engineering Institute')
        self.institute_beta = Institute.objects.create(code='INST-BETA', name='Beta Polytechnic Institute')

        # 2. Users
        self.admin_alpha = User.objects.create_user(
            email='admin@alpha.edu',
            password='Password123!',
            first_name='Admin',
            last_name='Alpha',
            is_active=True,
            must_change_password=False
        )
        self.admin_alpha_mem = UserInstituteMembership.objects.create(
            user=self.admin_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE
        )

        self.teacher_assigned_alpha = User.objects.create_user(
            email='assigned@alpha.edu',
            password='Password123!',
            first_name='Assigned',
            last_name='Teacher',
            is_active=True,
            must_change_password=False
        )
        self.teacher_assigned_mem = UserInstituteMembership.objects.create(
            user=self.teacher_assigned_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.TEACHER,
            status=MembershipStatus.ACTIVE
        )

        self.teacher_unassigned_alpha = User.objects.create_user(
            email='unassigned@alpha.edu',
            password='Password123!',
            first_name='Unassigned',
            last_name='Teacher',
            is_active=True,
            must_change_password=False
        )
        self.teacher_unassigned_mem = UserInstituteMembership.objects.create(
            user=self.teacher_unassigned_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.TEACHER,
            status=MembershipStatus.ACTIVE
        )

        self.student_alpha = User.objects.create_user(
            email='student@alpha.edu',
            password='Password123!',
            first_name='Student',
            last_name='Learner',
            is_active=True,
            must_change_password=False
        )
        UserInstituteMembership.objects.create(
            user=self.student_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.STUDENT,
            status=MembershipStatus.ACTIVE
        )

        self.admin_beta = User.objects.create_user(
            email='admin@beta.edu',
            password='Password123!',
            first_name='Admin',
            last_name='Beta',
            is_active=True,
            must_change_password=False
        )
        UserInstituteMembership.objects.create(
            user=self.admin_beta,
            institute=self.institute_beta,
            role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE
        )

        self.platform_admin = User.objects.create_superuser(
            email='super@examcraft.io',
            password='Password123!',
            first_name='Super',
            last_name='Admin'
        )
        self.platform_admin.must_change_password = False
        self.platform_admin.save()

        # 3. Academic Structure
        self.dept_cs = Department.objects.create(
            institute=self.institute_alpha,
            code='CS',
            name='Computer Science'
        )
        self.prog_btech = Program.objects.create(
            institute=self.institute_alpha,
            department=self.dept_cs,
            code='BTECH-CS',
            name='B.Tech CSE'
        )
        self.acad_year = AcademicYear.objects.create(
            institute=self.institute_alpha,
            label='2026-2027',
            start_date='2026-07-01',
            end_date='2027-06-30'
        )
        self.semester_3 = Semester.objects.create(
            program=self.prog_btech,
            label='Semester 3',
            semester_number=3
        )
        self.subj_dsa = Subject.objects.create(
            institute=self.institute_alpha,
            department=self.dept_cs,
            code='CS301',
            name='Data Structures and Algorithms'
        )
        self.unit_trees = Unit.objects.create(
            subject=self.subj_dsa,
            unit_number=1,
            title='Tree Structures'
        )
        self.topic_bst = Topic.objects.create(
            unit=self.unit_trees,
            title='Binary Search Trees',
            order=1
        )
        self.lo_analyze = LearningOutcome.objects.create(
            subject=self.subj_dsa,
            code='CO1',
            description='Analyze time complexity of tree operations.',
            category='cognitive'
        )

        # Teacher assignment for assigned teacher
        TeacherAssignment.objects.create(
            teacher=self.teacher_assigned_mem,
            subject=self.subj_dsa,
            academic_year=self.acad_year,
            status=AssignmentStatus.ACTIVE
        )

    def _create_approved_question(
        self,
        question_text='Sample Approved Question',
        q_type=QuestionType.MCQ,
        marks=Decimal('2.00'),
        difficulty=DifficultyLevel.MEDIUM,
        bloom=BloomTaxonomy.UNDERSTAND,
        status=QuestionStatus.APPROVED,
        institute=None,
        subject=None
    ):
        inst = institute or self.institute_alpha
        subj = subject or self.subj_dsa
        q = Question.objects.create(
            institute=inst,
            subject=subj,
            unit=self.unit_trees if inst == self.institute_alpha else None,
            topic=self.topic_bst if inst == self.institute_alpha else None,
            learning_outcome=self.lo_analyze if inst == self.institute_alpha else None,
            question_type=q_type,
            question_text=question_text,
            difficulty=difficulty,
            marks=marks,
            negative_marks=Decimal('0.50') if q_type == QuestionType.MCQ else Decimal('0.00'),
            bloom_taxonomy=bloom,
            origin_type=QuestionOrigin.MANUAL,
            status=status,
            current_version=1,
            created_by=self.teacher_assigned_alpha,
            code_metadata=(
                {
                    'language': 'python',
                    'supported_languages': ['python'],
                    'execution_constraints': {'time_limit_seconds': 4, 'memory_limit_mb': 256},
                    'starter_template': 'def solve():\n    pass',
                }
                if q_type == QuestionType.CODING else {}
            ),
        )
        if q_type == QuestionType.MCQ:
            QuestionOption.objects.create(question=q, option_key='A', option_text='Option A', is_correct=False, order=1)
            QuestionOption.objects.create(question=q, option_key='B', option_text='Option B', is_correct=True, order=2)
            QuestionOption.objects.create(question=q, option_key='C', option_text='Option C', is_correct=False, order=3)
            QuestionOption.objects.create(question=q, option_key='D', option_text='Option D', is_correct=False, order=4)
        elif q_type == QuestionType.SHORT_ANSWER:
            AnswerKey.objects.create(question=q, expected_answer='A binary tree with ordered keys.')
            QuestionRubric.objects.create(question=q, criterion='Definition', max_marks=marks, order=1)
        elif q_type == QuestionType.CODING:
            AnswerKey.objects.create(
                question=q,
                expected_answer='Return the provided input.',
                test_cases=[
                    {'input': 'public', 'expected_output': 'public', 'is_hidden': False},
                    {'input': 'private', 'expected_output': 'private', 'is_hidden': True},
                ],
            )
        
        QuestionSourceReference.objects.create(
            question=q,
            source_title='Core Syllabus Textbook',
            page_or_section='Page 42',
            excerpt='BST properties.'
        )
        return q

    # -------------------------------------------------------------------------
    # 1. Blueprint Creation and Permissions
    # -------------------------------------------------------------------------
    def test_assigned_teacher_can_create_blueprint_for_subject(self):
        self.client.force_authenticate(user=self.teacher_assigned_alpha)
        url = reverse('paper-blueprint-list')
        payload = {
            'institute': str(self.institute_alpha.id),
            'title': 'Mid-Term DSA Exam 2026',
            'subject': str(self.subj_dsa.id),
            'total_marks': '50.00',
            'duration_minutes': 90,
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['title'], 'Mid-Term DSA Exam 2026')
        self.assertEqual(response.data['total_marks'], '50.00')

    def test_unassigned_teacher_cannot_create_blueprint_for_unassigned_subject(self):
        self.client.force_authenticate(user=self.teacher_unassigned_alpha)
        url = reverse('paper-blueprint-list')
        payload = {
            'institute': str(self.institute_alpha.id),
            'title': 'Unauthorized Blueprint Attempt',
            'subject': str(self.subj_dsa.id),
            'total_marks': '50.00',
            'duration_minutes': 90,
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_institute_access_isolated(self):
        bp = PaperBlueprint.objects.create(
            institute=self.institute_alpha,
            title='Alpha Mid-Term',
            subject=self.subj_dsa,
            total_marks=Decimal('50.00'),
            duration_minutes=90,
            created_by=self.admin_alpha
        )
        self.client.force_authenticate(user=self.admin_beta)
        url = reverse('paper-blueprint-detail', kwargs={'pk': bp.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_student_forbidden_from_blueprint_and_paper_endpoints(self):
        self.client.force_authenticate(user=self.student_alpha)
        url = reverse('paper-blueprint-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        gen_url = reverse('generated-paper-list')
        gen_resp = self.client.get(gen_url)
        self.assertEqual(gen_resp.status_code, status.HTTP_403_FORBIDDEN)

    # -------------------------------------------------------------------------
    # 2. Structural Validation and Mark Reconciliation
    # -------------------------------------------------------------------------
    def test_validate_structure_fails_when_section_marks_do_not_equal_blueprint_total(self):
        self.client.force_authenticate(user=self.admin_alpha)
        # Blueprint with 50.00 total marks
        bp = PaperBlueprint.objects.create(
            institute=self.institute_alpha,
            title='Unbalanced Blueprint',
            subject=self.subj_dsa,
            total_marks=Decimal('50.00'),
            duration_minutes=90,
            created_by=self.admin_alpha
        )
        # Section with target 30.00 (not 50.00)
        sec = BlueprintSection.objects.create(
            blueprint=bp,
            name='Section A',
            order=1,
            target_marks=Decimal('30.00')
        )
        # Rule with 15 questions x 2.00M = 30.00M (matches section, but section != blueprint)
        BlueprintRule.objects.create(
            section=sec,
            order=1,
            question_type=QuestionType.MCQ,
            question_count=15,
            marks_per_question=Decimal('2.00')
        )

        url = reverse('paper-blueprint-validate-structure', kwargs={'pk': bp.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Sum of section marks (30.00) does not reconcile with blueprint total marks (50.00)', response.data['error']['message'])

    def test_validate_structure_fails_when_rule_sum_does_not_equal_section_target(self):
        self.client.force_authenticate(user=self.admin_alpha)
        bp = PaperBlueprint.objects.create(
            institute=self.institute_alpha,
            title='Section Rule Mismatch',
            subject=self.subj_dsa,
            total_marks=Decimal('50.00'),
            duration_minutes=90,
            created_by=self.admin_alpha
        )
        sec = BlueprintSection.objects.create(
            blueprint=bp,
            name='Section A',
            order=1,
            target_marks=Decimal('50.00')
        )
        # Rule total = 10 x 2.00 = 20.00M != 50.00M
        BlueprintRule.objects.create(
            section=sec,
            order=1,
            question_type=QuestionType.MCQ,
            question_count=10,
            marks_per_question=Decimal('2.00')
        )

        url = reverse('paper-blueprint-validate-structure', kwargs={'pk': bp.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("target marks (50.00) does not match sum of its rules (20.00)", response.data['error']['message'])

    # -------------------------------------------------------------------------
    # 3. Question Shortage Reporting
    # -------------------------------------------------------------------------
    def test_availability_and_shortage_reporting_when_approved_questions_insufficient(self):
        self.client.force_authenticate(user=self.admin_alpha)
        bp = PaperBlueprint.objects.create(
            institute=self.institute_alpha,
            title='Shortage Test Blueprint',
            subject=self.subj_dsa,
            total_marks=Decimal('10.00'),
            duration_minutes=30,
            created_by=self.admin_alpha
        )
        sec = BlueprintSection.objects.create(
            blueprint=bp,
            name='Section A',
            order=1,
            target_marks=Decimal('10.00')
        )
        # Requires 5 questions of 2 marks
        rule = BlueprintRule.objects.create(
            section=sec,
            order=1,
            question_type=QuestionType.MCQ,
            question_count=5,
            marks_per_question=Decimal('2.00')
        )

        # Seed only 2 approved questions
        self._create_approved_question(question_text='Approved Q1', marks=Decimal('2.00'))
        self._create_approved_question(question_text='Approved Q2', marks=Decimal('2.00'))
        # Seed 3 draft questions (must be ignored)
        self._create_approved_question(question_text='Draft Q3', marks=Decimal('2.00'), status=QuestionStatus.DRAFT)
        self._create_approved_question(question_text='Rejected Q4', marks=Decimal('2.00'), status=QuestionStatus.REJECTED)

        # Check availability report endpoint
        avail_url = reverse('paper-blueprint-check-availability', kwargs={'pk': bp.id})
        response = self.client.get(avail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['can_generate'])
        self.assertEqual(response.data['rules'][0]['required_count'], 5)
        self.assertEqual(response.data['rules'][0]['available_count'], 2)
        self.assertEqual(response.data['rules'][0]['shortage'], 3)

        # Attempt to generate paper -> must fail with PaperGenerationError and detailed shortage
        gen_url = reverse('paper-blueprint-generate-paper', kwargs={'pk': bp.id})
        gen_resp = self.client.post(gen_url, {'title': 'Failed Generation'})
        self.assertEqual(gen_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Insufficient approved questions available", gen_resp.data['error']['message'])
        shortage_details = gen_resp.data['error']['details']['shortages']
        self.assertEqual(len(shortage_details), 1)
        self.assertEqual(shortage_details[0]['shortage'], 3)
        self.assertEqual(shortage_details[0]['available_count'], 2)

    # -------------------------------------------------------------------------
    # 4. Successful Paper Generation and Question Selection
    # -------------------------------------------------------------------------
    def test_successful_paper_generation_and_immutable_question_snapshots(self):
        self.client.force_authenticate(user=self.admin_alpha)
        bp = PaperBlueprint.objects.create(
            institute=self.institute_alpha,
            title='DSA Final Exam 2026',
            subject=self.subj_dsa,
            total_marks=Decimal('20.00'),
            duration_minutes=60,
            created_by=self.admin_alpha
        )
        sec_a = BlueprintSection.objects.create(
            blueprint=bp,
            name='Section A: Objective',
            order=1,
            target_marks=Decimal('10.00')
        )
        sec_b = BlueprintSection.objects.create(
            blueprint=bp,
            name='Section B: Subjective',
            order=2,
            target_marks=Decimal('10.00')
        )
        # Sec A: 5 MCQs x 2.00M = 10.00M
        BlueprintRule.objects.create(
            section=sec_a,
            order=1,
            question_type=QuestionType.MCQ,
            question_count=5,
            marks_per_question=Decimal('2.00')
        )
        # Sec B: 2 Short Answers x 5.00M = 10.00M
        BlueprintRule.objects.create(
            section=sec_b,
            order=1,
            question_type=QuestionType.SHORT_ANSWER,
            question_count=2,
            marks_per_question=Decimal('5.00')
        )

        # Seed pool of approved questions
        for i in range(6):
            self._create_approved_question(
                question_text=f"MCQ Question #{i+1}",
                q_type=QuestionType.MCQ,
                marks=Decimal('2.00')
            )
        for j in range(3):
            self._create_approved_question(
                question_text=f"Short Answer Problem #{j+1}",
                q_type=QuestionType.SHORT_ANSWER,
                marks=Decimal('5.00')
            )

        gen_url = reverse('paper-blueprint-generate-paper', kwargs={'pk': bp.id})
        response = self.client.post(gen_url, {'title': 'DSA Final Exam Set 1'})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.data
        self.assertEqual(data['total_marks'], '20.00')
        self.assertEqual(data['status'], GeneratedPaperStatus.COMPLETED)
        self.assertEqual(data['generation_version'], 1)
        self.assertEqual(len(data['paper_questions']), 7)

        # Verify sequential numbering and immutable snapshots
        question_numbers = [pq['question_number'] for pq in data['paper_questions']]
        self.assertEqual(question_numbers, [1, 2, 3, 4, 5, 6, 7])

        # Verify no duplicate questions in the paper
        placed_q_ids = [pq['question'] for pq in data['paper_questions']]
        self.assertEqual(len(placed_q_ids), len(set(placed_q_ids)))

        # Verify first question has snapshot data
        first_q = data['paper_questions'][0]
        self.assertEqual(first_q['section_name'], 'Section A: Objective')
        self.assertEqual(len(first_q['options_snapshot']), 4)
        self.assertEqual(len(first_q['provenance_snapshot']), 1)

    def test_coding_paper_generation_snapshots_hidden_cases_and_execution_config(self):
        self.client.force_authenticate(user=self.admin_alpha)
        blueprint = PaperBlueprint.objects.create(
            institute=self.institute_alpha,
            title='Coding Exam',
            subject=self.subj_dsa,
            total_marks=Decimal('2.00'),
            duration_minutes=30,
            created_by=self.admin_alpha,
        )
        section = BlueprintSection.objects.create(
            blueprint=blueprint,
            name='Coding',
            order=1,
            target_marks=Decimal('2.00'),
        )
        BlueprintRule.objects.create(
            section=section,
            order=1,
            question_type=QuestionType.CODING,
            question_count=1,
            marks_per_question=Decimal('2.00'),
        )
        self._create_approved_question(
            question_text='Return the input.',
            q_type=QuestionType.CODING,
            marks=Decimal('2.00'),
        )

        response = self.client.post(
            reverse('paper-blueprint-generate-paper', kwargs={'pk': blueprint.id}),
            {},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        question_snapshot = GeneratedPaperQuestion.objects.get(paper_id=response.data['id'])
        self.assertEqual(
            question_snapshot.test_cases_snapshot[1],
            {'input': 'private', 'expected_output': 'private', 'is_hidden': True},
        )
        self.assertEqual(question_snapshot.code_metadata_snapshot['supported_languages'], ['python'])

    # -------------------------------------------------------------------------
    # 5. Paper Regeneration and Version Incrementing
    # -------------------------------------------------------------------------
    def test_regeneration_increments_version_and_preserves_previous_paper(self):
        self.client.force_authenticate(user=self.admin_alpha)
        bp = PaperBlueprint.objects.create(
            institute=self.institute_alpha,
            title='DSA Midterm Set',
            subject=self.subj_dsa,
            total_marks=Decimal('4.00'),
            duration_minutes=20,
            created_by=self.admin_alpha
        )
        sec = BlueprintSection.objects.create(
            blueprint=bp,
            name='Section A',
            order=1,
            target_marks=Decimal('4.00')
        )
        BlueprintRule.objects.create(
            section=sec,
            order=1,
            question_type=QuestionType.MCQ,
            question_count=2,
            marks_per_question=Decimal('2.00')
        )

        for i in range(4):
            self._create_approved_question(question_text=f"Approved Q #{i+1}", marks=Decimal('2.00'))

        gen_url = reverse('paper-blueprint-generate-paper', kwargs={'pk': bp.id})
        
        # Generation 1
        resp1 = self.client.post(gen_url, {'title': 'Paper Version 1'})
        self.assertEqual(resp1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp1.data['generation_version'], 1)
        paper1_id = resp1.data['id']

        # Generation 2 (regeneration)
        resp2 = self.client.post(gen_url, {'title': 'Paper Version 2'})
        self.assertEqual(resp2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp2.data['generation_version'], 2)
        paper2_id = resp2.data['id']

        self.assertNotEqual(paper1_id, paper2_id)
        # Previous paper still exists intact
        p1 = GeneratedPaper.objects.get(id=paper1_id)
        self.assertEqual(p1.generation_version, 1)
        self.assertEqual(p1.paper_questions.count(), 2)

    # -------------------------------------------------------------------------
    # 6. Exclude Non-Approved and Cross-Institute Questions
    # -------------------------------------------------------------------------
    def test_strict_exclusion_of_non_approved_and_cross_institute_questions(self):
        self.client.force_authenticate(user=self.admin_alpha)
        bp = PaperBlueprint.objects.create(
            institute=self.institute_alpha,
            title='Filter Strictness Blueprint',
            subject=self.subj_dsa,
            total_marks=Decimal('2.00'),
            duration_minutes=10,
            created_by=self.admin_alpha
        )
        sec = BlueprintSection.objects.create(blueprint=bp, name='Sec', order=1, target_marks=Decimal('2.00'))
        BlueprintRule.objects.create(
            section=sec,
            order=1,
            question_type=QuestionType.MCQ,
            question_count=1,
            marks_per_question=Decimal('2.00')
        )

        # 1. Draft question (should be excluded)
        self._create_approved_question(question_text='Draft Q', marks=Decimal('2.00'), status=QuestionStatus.DRAFT)
        # 2. Under Review question (should be excluded)
        self._create_approved_question(question_text='Review Q', marks=Decimal('2.00'), status=QuestionStatus.UNDER_REVIEW)
        # 3. Rejected question (should be excluded)
        self._create_approved_question(question_text='Rejected Q', marks=Decimal('2.00'), status=QuestionStatus.REJECTED)
        # 4. Archived question (should be excluded)
        self._create_approved_question(question_text='Archived Q', marks=Decimal('2.00'), status=QuestionStatus.ARCHIVED)
        # 5. Approved question from Beta institute (should be excluded)
        dept_beta = Department.objects.create(institute=self.institute_beta, code='BETA-CS', name='Beta CS')
        subj_beta = Subject.objects.create(institute=self.institute_beta, department=dept_beta, code='BETA301', name='Beta DSA')
        self._create_approved_question(
            question_text='Beta Approved Q',
            marks=Decimal('2.00'),
            status=QuestionStatus.APPROVED,
            institute=self.institute_beta,
            subject=subj_beta
        )

        gen_url = reverse('paper-blueprint-generate-paper', kwargs={'pk': bp.id})
        response = self.client.post(gen_url)
        # Must fail because none of the above questions are eligible
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Insufficient approved questions available", response.data['error']['message'])
        self.assertEqual(response.data['error']['details']['shortages'][0]['available_count'], 0)

    # -------------------------------------------------------------------------
    # 7. Atomic Rollback on Persistence Error
    # -------------------------------------------------------------------------
    def test_atomic_rollback_on_persistence_error(self):
        from unittest.mock import patch
        self.client.force_authenticate(user=self.admin_alpha)
        bp = PaperBlueprint.objects.create(
            institute=self.institute_alpha,
            title='Rollback Test Blueprint',
            subject=self.subj_dsa,
            total_marks=Decimal('2.00'),
            duration_minutes=15,
            created_by=self.admin_alpha
        )
        sec = BlueprintSection.objects.create(blueprint=bp, name='Sec', order=1, target_marks=Decimal('2.00'))
        BlueprintRule.objects.create(
            section=sec,
            order=1,
            question_type=QuestionType.MCQ,
            question_count=1,
            marks_per_question=Decimal('2.00')
        )
        self._create_approved_question(question_text='Approved Q', marks=Decimal('2.00'))

        initial_paper_count = GeneratedPaper.objects.count()

        # Simulate database failure during question snapshot creation
        with patch('apps.blueprints.services.GeneratedPaperQuestion.objects.create', side_effect=RuntimeError("Disk failure")):
            gen_url = reverse('paper-blueprint-generate-paper', kwargs={'pk': bp.id})
            response = self.client.post(gen_url)
            self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Confirm rollback: no partial GeneratedPaper record remains
        self.assertEqual(GeneratedPaper.objects.count(), initial_paper_count)
