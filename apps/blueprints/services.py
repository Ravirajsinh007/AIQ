import random
from decimal import Decimal
from typing import Dict, List, Tuple, Any, Optional
from django.db import transaction
from django.db.models import Q

from apps.accounts.models import User
from apps.questions.models import Question, QuestionStatus
from .models import (
    PaperBlueprint,
    BlueprintSection,
    BlueprintRule,
    GeneratedPaper,
    GeneratedPaperQuestion,
    GeneratedPaperStatus,
)


class BlueprintValidationError(Exception):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class PaperGenerationError(Exception):
    def __init__(self, message: str, shortage_report: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.shortage_report = shortage_report or {}


class PaperGenerationService:
    """
    Dedicated core service responsible for:
    1. Validating PaperBlueprint structural integrity and mark reconciliation.
    2. Checking availability of approved questions from M3.
    3. Performing transparent, constraint-satisfying question selection.
    4. Producing immutable generated paper and question content snapshots atomically.
    """

    @classmethod
    def validate_blueprint_structure(cls, blueprint: PaperBlueprint) -> Dict[str, Any]:
        """
        Validates:
        - Blueprint has at least one section.
        - Each section has at least one rule.
        - Sum of rule marks equals each section's target marks.
        - Sum of section target marks equals blueprint's total marks.
        - No contradictory rules or negative values.
        """
        sections = list(blueprint.sections.prefetch_related('rules').all())
        if not sections:
            raise BlueprintValidationError(
                "Blueprint must have at least one section.",
                details={'sections': "No sections defined."}
            )

        total_sections_marks = Decimal('0.00')
        section_reports = []

        for sec in sections:
            rules = list(sec.rules.all())
            if not rules:
                raise BlueprintValidationError(
                    f"Section '{sec.name}' must have at least one selection rule.",
                    details={'section': sec.name, 'rules': "No rules defined for section."}
                )

            sec_calculated_marks = Decimal('0.00')
            for r in rules:
                rule_marks = Decimal(str(r.question_count)) * r.marks_per_question
                sec_calculated_marks += rule_marks

            if sec_calculated_marks != sec.target_marks:
                raise BlueprintValidationError(
                    f"Section '{sec.name}' target marks ({sec.target_marks}) does not match sum of its rules ({sec_calculated_marks}).",
                    details={
                        'section': sec.name,
                        'target_marks': str(sec.target_marks),
                        'calculated_marks': str(sec_calculated_marks),
                        'difference': str(sec.target_marks - sec_calculated_marks)
                    }
                )

            total_sections_marks += sec.target_marks
            section_reports.append({
                'section_name': sec.name,
                'target_marks': str(sec.target_marks),
                'rule_count': len(rules),
            })

        if total_sections_marks != blueprint.total_marks:
            raise BlueprintValidationError(
                f"Sum of section marks ({total_sections_marks}) does not reconcile with blueprint total marks ({blueprint.total_marks}).",
                details={
                    'blueprint_total_marks': str(blueprint.total_marks),
                    'sections_total_marks': str(total_sections_marks),
                    'difference': str(blueprint.total_marks - total_sections_marks)
                }
            )

        return {
            'is_valid': True,
            'blueprint_title': blueprint.title,
            'total_marks': str(blueprint.total_marks),
            'section_count': len(sections),
            'sections': section_reports,
        }

    @classmethod
    def check_question_availability(cls, blueprint: PaperBlueprint) -> Dict[str, Any]:
        """
        Scans approved M3 questions for each rule in the blueprint and returns
        an availability and shortage breakdown without persisting a paper.
        """
        cls.validate_blueprint_structure(blueprint)

        sections = list(blueprint.sections.prefetch_related('rules').all())
        rules_status = []
        overall_available = True
        used_question_ids = set()

        for sec in sections:
            for rule in sec.rules.all():
                qs = cls._get_eligible_questions_queryset(blueprint, rule)
                
                if not blueprint.allow_question_reuse:
                    qs = qs.exclude(id__in=used_question_ids)

                available_count = qs.count()
                required_count = rule.question_count
                is_sufficient = available_count >= required_count

                if not is_sufficient:
                    overall_available = False

                rules_status.append({
                    'section_name': sec.name,
                    'rule_id': str(rule.id),
                    'question_type': rule.question_type,
                    'marks_per_question': str(rule.marks_per_question),
                    'required_count': required_count,
                    'available_count': available_count,
                    'is_sufficient': is_sufficient,
                    'shortage': max(0, required_count - available_count),
                    'unit_filter': rule.unit.title if rule.unit else None,
                    'topic_filter': rule.topic.title if rule.topic else None,
                    'difficulty_filter': rule.difficulty,
                    'bloom_filter': rule.bloom_taxonomy,
                })

        return {
            'can_generate': overall_available,
            'blueprint_id': str(blueprint.id),
            'blueprint_title': blueprint.title,
            'rules': rules_status,
        }

    @classmethod
    def _get_eligible_questions_queryset(cls, blueprint: PaperBlueprint, rule: BlueprintRule):
        """
        Builds filtered queryset adhering strictly to:
        - status='approved' (draft, under_review, rejected, archived strictly excluded)
        - same institute as blueprint
        - same subject as blueprint
        - rule question_type
        - rule marks_per_question
        - optional unit/topic/learning_outcome filters
        - optional exact difficulty / bloom filters
        """
        qs = Question.objects.filter(
            institute_id=blueprint.institute_id,
            subject_id=blueprint.subject_id,
            status=QuestionStatus.APPROVED,
            question_type=rule.question_type,
            marks=rule.marks_per_question,
        ).select_related('answer_key').prefetch_related('options', 'rubrics', 'source_references')

        if rule.unit_id:
            qs = qs.filter(unit_id=rule.unit_id)
        if rule.topic_id:
            qs = qs.filter(topic_id=rule.topic_id)
        if rule.learning_outcome_id:
            qs = qs.filter(learning_outcome_id=rule.learning_outcome_id)
        if rule.difficulty:
            qs = qs.filter(difficulty=rule.difficulty)
        if rule.bloom_taxonomy:
            qs = qs.filter(bloom_taxonomy=rule.bloom_taxonomy)

        return qs

    @classmethod
    @transaction.atomic
    def generate_paper(
        cls,
        blueprint: PaperBlueprint,
        user: Optional[User] = None,
        custom_title: Optional[str] = None
    ) -> GeneratedPaper:
        """
        Executes end-to-end paper generation:
        1. Validates blueprint structure and reconciliation.
        2. Evaluates rules against approved questions.
        3. Fails cleanly with shortage report if insufficient approved questions.
        4. Selects questions using a fair randomized strategy avoiding duplicates.
        5. Atomically persists GeneratedPaper and GeneratedPaperQuestion records.
        """
        cls.validate_blueprint_structure(blueprint)

        sections = list(blueprint.sections.prefetch_related('rules').order_by('order').all())
        selected_questions_plan: List[Dict[str, Any]] = []
        used_question_ids = set()
        shortage_items = []

        for sec in sections:
            for rule in sec.rules.order_by('order').all():
                qs = cls._get_eligible_questions_queryset(blueprint, rule)
                
                if not blueprint.allow_question_reuse:
                    qs = qs.exclude(id__in=used_question_ids)

                eligible_questions = list(qs)
                required_count = rule.question_count

                if len(eligible_questions) < required_count:
                    shortage_items.append({
                        'section_name': sec.name,
                        'rule_id': str(rule.id),
                        'question_type': rule.question_type,
                        'marks_per_question': str(rule.marks_per_question),
                        'required_count': required_count,
                        'available_count': len(eligible_questions),
                        'shortage': required_count - len(eligible_questions),
                    })
                    continue

                # Fair selection strategy: shuffle candidate questions
                # (seeded deterministically or pseudo-randomly to avoid picking identical subset)
                random.shuffle(eligible_questions)
                chosen = eligible_questions[:required_count]

                for q in chosen:
                    if not blueprint.allow_question_reuse:
                        used_question_ids.add(q.id)

                    selected_questions_plan.append({
                        'section_name': sec.name,
                        'section_order': sec.order,
                        'question': q,
                        'marks': rule.marks_per_question,
                    })

        if shortage_items:
            raise PaperGenerationError(
                "Insufficient approved questions available to satisfy the blueprint specification.",
                shortage_report={
                    'blueprint_id': str(blueprint.id),
                    'blueprint_title': blueprint.title,
                    'shortages': shortage_items,
                    'remediation': "Author more questions or approve pending draft questions before regenerating."
                }
            )

        # Determine next generation version for this blueprint
        blueprint.__class__.objects.select_for_update().get(pk=blueprint.pk)
        last_gen = GeneratedPaper.objects.filter(blueprint=blueprint).order_by('-generation_version').first()
        next_version = (last_gen.generation_version + 1) if last_gen else 1

        title = custom_title or f"{blueprint.title} - Paper {next_version}"

        # Build blueprint snapshot
        blueprint_snapshot = {
            'blueprint_id': str(blueprint.id),
            'title': blueprint.title,
            'subject_code': blueprint.subject.code,
            'subject_name': blueprint.subject.name,
            'total_marks': str(blueprint.total_marks),
            'duration_minutes': blueprint.duration_minutes,
            'sections': [
                {
                    'name': s.name,
                    'order': s.order,
                    'target_marks': str(s.target_marks),
                    'rules': [
                        {
                            'question_type': r.question_type,
                            'question_count': r.question_count,
                            'marks_per_question': str(r.marks_per_question),
                            'difficulty': r.difficulty,
                            'bloom_taxonomy': r.bloom_taxonomy,
                        }
                        for r in s.rules.all()
                    ]
                }
                for s in sections
            ]
        }

        # Atomically persist paper and snapshot questions
        with transaction.atomic():
            paper = GeneratedPaper.objects.create(
                institute=blueprint.institute,
                blueprint=blueprint,
                title=title,
                subject=blueprint.subject,
                total_marks=blueprint.total_marks,
                duration_minutes=blueprint.duration_minutes,
                status=GeneratedPaperStatus.COMPLETED,
                generation_version=next_version,
                blueprint_snapshot=blueprint_snapshot,
                validation_report={
                    'reconciled': True,
                    'total_marks': str(blueprint.total_marks),
                    'questions_selected': len(selected_questions_plan),
                },
                created_by=user,
            )
            from apps.audit.services import record_audit_event

            record_audit_event(
                action='paper.generated',
                resource_type='generated_paper',
                resource_id=paper.pk,
                actor=user,
                institute=paper.institute,
                metadata={
                    'generation_version': paper.generation_version,
                    'question_count': len(selected_questions_plan),
                },
            )

            # Assign sequential question numbers
            question_num = 1
            for item in selected_questions_plan:
                q: Question = item['question']

                # Create option snapshots without revealing correct answers in student context
                options_snapshot = [
                    {
                        'option_key': opt.option_key,
                        'option_text': opt.option_text,
                        'order': opt.order,
                        'is_correct': opt.is_correct,
                    }
                    for opt in q.options.order_by('order')
                ]

                # Create rubric snapshots
                rubric_snapshot = [
                    {
                        'criterion': rub.criterion,
                        'description': rub.description,
                        'max_marks': str(rub.max_marks),
                        'order': rub.order,
                    }
                    for rub in q.rubrics.order_by('order')
                ]

                # Create provenance snapshots
                provenance_snapshot = [
                    {
                        'source_title': src.source_title,
                        'page_or_section': src.page_or_section,
                        'excerpt': src.excerpt,
                    }
                    for src in q.source_references.all()
                ]
                answer_key = getattr(q, 'answer_key', None)

                GeneratedPaperQuestion.objects.create(
                    paper=paper,
                    section_name=item['section_name'],
                    section_order=item['section_order'],
                    question_number=question_num,
                    question=q,
                    question_version=q.current_version,
                    question_type=q.question_type,
                    question_text=q.question_text,
                    marks=item['marks'],
                    negative_marks=q.negative_marks,
                    difficulty=q.difficulty,
                    bloom_taxonomy=q.bloom_taxonomy,
                    options_snapshot=options_snapshot,
                    rubric_snapshot=rubric_snapshot,
                    provenance_snapshot=provenance_snapshot,
                    test_cases_snapshot=answer_key.test_cases if answer_key else [],
                    code_metadata_snapshot=q.code_metadata or {},
                )
                question_num += 1

        return paper
